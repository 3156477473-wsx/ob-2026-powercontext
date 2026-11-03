#!/usr/bin/env python3
"""Structural + behavioural validation for the generated Dify DSL."""
import ast
import os
import json
import re
import sys

import yaml

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dsl", "jiuguan-a-jiu.chatflow.yml")
doc = yaml.safe_load(open(PATH, encoding="utf-8"))
graph = doc["workflow"]["graph"]
nodes = {node["id"]: node for node in graph["nodes"]}
errors = []

# 1. 基本结构
if doc["app"]["mode"] != "advanced-chat":
    errors.append("app.mode 应为 advanced-chat")
for node in graph["nodes"]:
    data = node["data"]
    for key in ("type", "title"):
        if key not in data:
            errors.append(f"节点 {node['id']} 缺少 data.{key}")

# 2. 边
for edge in graph["edges"]:
    if edge["source"] not in nodes:
        errors.append(f"边 source 不存在: {edge['source']}")
    if edge["target"] not in nodes:
        errors.append(f"边 target 不存在: {edge['target']}")
    handle = edge["sourceHandle"]
    if nodes.get(edge["source"], {}).get("data", {}).get("type") == "if-else":
        if handle not in ("true", "false"):
            errors.append(f"if-else 分支 handle 非法: {handle}")

# 3. 分支覆盖
branch = next(n for n in graph["nodes"] if n["data"]["type"] == "if-else")
handles = {e["sourceHandle"] for e in graph["edges"] if e["source"] == branch["id"]}
if handles != {"true", "false"}:
    errors.append(f"if-else 分支不全: {handles}")

# 4. 变量引用
ref_pattern = re.compile(r"\{\{#([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)#\}\}")
used_refs = set()
for node in graph["nodes"]:
    blob = json.dumps(node["data"], ensure_ascii=False)
    for source, name in ref_pattern.findall(blob):
        if source in ("sys", "env", "conversation"):
            continue
        used_refs.add((source, name))
        if source not in nodes:
            errors.append(f"变量引用指向不存在的节点: {source}.{name}")
            continue
        outputs = nodes[source]["data"].get("outputs") or {}
        if outputs and name not in outputs:
            errors.append(f"变量名不在上游输出里: {source}.{name}")

# 5. code 节点：语法 + 签名 + 试跑
samples = {
    "1810000000003": {
        "raw": json.dumps(
            {
                "ok": True,
                "memory_count": 1,
                "lore_count": 3,
                "memory_block": "- 最近连续加班到深夜",
                "lore_block": "- 【招牌 · 加班的海】深蓝色酒液",
            },
            ensure_ascii=False,
        )
    },
    "1810000000006": {"raw": '```json\n{"remember": "yes", "fact": "连续加班到深夜"}\n```'},
}
for node in graph["nodes"]:
    data = node["data"]
    if data["type"] != "code":
        continue
    source = data["code"]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        errors.append(f"代码节点语法错误 {node['id']}: {exc}")
        continue
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    if not funcs:
        errors.append(f"代码节点缺少 main: {node['id']}")
        continue
    params = [a.arg for a in funcs[0].args.args]
    declared = [v["variable"] for v in data.get("variables", [])]
    if params != declared:
        errors.append(f"代码节点参数与变量不一致 {node['id']}: {params} vs {declared}")
    if node["id"] in samples:
        scope = {}
        exec(compile(tree, node["id"], "exec"), scope)  # noqa: S102 - local validation only
        result = scope["main"](**samples[node["id"]])
        outputs = data.get("outputs") or {}
        for key in outputs:
            if key not in result:
                errors.append(f"代码节点 {node['id']} 未返回声明的输出 {key}")
        print(f"code {node['id']} -> {result}")

# 6. LLM 节点
for node in graph["nodes"]:
    data = node["data"]
    if data["type"] != "llm":
        continue
    if not data.get("prompt_template"):
        errors.append(f"LLM 节点缺少 prompt_template: {node['id']}")
    if "model" not in data or "name" not in data["model"]:
        errors.append(f"LLM 节点缺少 model: {node['id']}")

# 7. HTTP 节点
for node in graph["nodes"]:
    data = node["data"]
    if data["type"] != "http-request":
        continue
    if not str(data.get("url", "")).startswith("http"):
        errors.append(f"HTTP 节点 url 非法: {node['id']}")
    if data.get("body", {}).get("type") != "json":
        errors.append(f"HTTP 节点 body 应为 json: {node['id']}")

print(f"nodes={len(nodes)} edges={len(graph['edges'])} refs={len(used_refs)}")
if errors:
    print("FAILED:")
    for item in errors:
        print(" -", item)
    sys.exit(1)
print("DSL 结构校验通过")
