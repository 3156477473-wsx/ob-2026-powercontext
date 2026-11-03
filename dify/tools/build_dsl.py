#!/usr/bin/env python3
"""Emit the 「深夜酒馆 · 阿九」 Dify Chatflow DSL."""
import json
import os

import yaml

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dsl", "jiuguan-a-jiu.chatflow.yml")

START = "1810000000001"
RECALL = "1810000000002"
PARSE = "1810000000003"
BARKEEP = "1810000000004"
MEMLLM = "1810000000005"
PARSE_MEM = "1810000000006"
BRANCH = "1810000000007"
REMEMBER = "1810000000008"
ANS_A = "1810000000009"
ANS_B = "1810000000010"

MODEL = {
    "provider": "langgenius/openai_api_compatible/openai_api_compatible",
    "name": "qwen2.5:7b",
    "mode": "chat",
    "completion_params": {"max_tokens": 1024, "temperature": 0.7, "enable_thinking": False},
}


def node(nid, kind, title, x, y, data, width=244, height=110):
    payload = {"desc": "", "selected": False, "title": title, "type": kind}
    payload.update(data)
    return {
        "data": payload,
        "height": height,
        "id": nid,
        "position": {"x": x, "y": y},
        "positionAbsolute": {"x": x, "y": y},
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "type": "custom",
        "width": width,
    }


def edge(src, dst, handle="source", src_type="custom", dst_type="custom"):
    return {
        "data": {"isInIteration": False, "isInLoop": False, "sourceType": src_type, "targetType": dst_type},
        "id": f"{src}-{handle}-{dst}-target",
        "source": src,
        "sourceHandle": handle,
        "target": dst,
        "targetHandle": "target",
        "type": "custom",
        "zIndex": 0,
    }


BARKEEP_SYSTEM = """你是「深夜酒馆」的酒保阿九。说话慢，话不多，语气像一张放过很多遍的旧唱片。

每次回应请遵守：
1. 先为客人调一杯酒，给它起一个 2~6 个字的名字（用《》括住），再写一句台词（不超过两行）。
2. 【这位客人的记忆】里的事实必须用上，但不许编造记忆里没有的过去。记忆为空时，就当他是第一次来，不要假装早就认识。
3. 可以自然引用【酒馆设定】里的店规、酒单或老梗，一次最多引用两条，不要整段背诵。
4. 不要解释你在做什么，不要输出 JSON，不要堆砌表情符号。"""

BARKEEP_USER = """【这位客人的记忆】
{{#1810000000003.memory_block#}}

【酒馆设定】
{{#1810000000003.lore_block#}}

客人刚说：{{#sys.query#}}"""

MEMORY_SYSTEM = """你负责从对话里抽取“值得记住的客人事实”，供酒保下次回忆。

只输出一个 JSON 对象，不要输出任何其它文字：
{"remember": "yes" 或 "no", "fact": "一句话，第三人称，最多 40 字"}

判断规则：
- 记录稳定的信息或重要经历：工作/学业状态、口味与忌口、情绪事件、约定、称呼、正在经历的难事。
- 不记录：寒暄、点单动作、对酒的评价、酒保自己说的话。
- 没有可记的内容时返回 {"remember": "no", "fact": ""}。"""

MEMORY_USER = """客人说：{{#sys.query#}}
阿九回应：{{#1810000000004.text#}}"""

PARSE_RECALL_CODE = '''import json


def main(raw: str) -> dict:
    data = {}
    try:
        data = json.loads(raw or "{}")
    except Exception:
        data = {}
    memory_block = str(data.get("memory_block") or "（这位客人是第一次来，还没有任何记忆）")
    lore_block = str(data.get("lore_block") or "（今晚没有特别的酒单提示）")
    return {
        "memory_block": memory_block,
        "lore_block": lore_block,
        "memory_count": str(data.get("memory_count", 0)),
        "lore_count": str(data.get("lore_count", 0)),
    }
'''

PARSE_MEMORY_CODE = '''import json
import re


def main(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\\n?", "", text)
        text = re.sub(r"\\n?```$", "", text).strip()
    match = re.search(r"\\{[\\s\\S]*\\}", text)
    if match:
        text = match.group(0)
    remember, fact = "no", ""
    try:
        data = json.loads(text)
        remember = "yes" if str(data.get("remember", "")).strip().lower() in ("yes", "true", "1") else "no"
        fact = str(data.get("fact", "")).strip()[:120]
    except Exception:
        remember, fact = "no", ""
    if not fact:
        remember = "no"
    return {"should_remember": remember, "fact": fact}
'''

nodes = [
    node(
        START,
        "start",
        "开始",
        40,
        300,
        {
            "variables": [
                {
                    "label": "你的名字（用于区分不同客人的记忆）",
                    "max_length": 32,
                    "options": [],
                    "required": True,
                    "type": "text-input",
                    "variable": "user_id",
                }
            ]
        },
        height=110,
    ),
    node(
        RECALL,
        "http-request",
        "取记忆与酒馆设定",
        380,
        300,
        {
            "authorization": {"config": None, "type": "no-auth"},
            "body": {
                "data": [
                    {
                        "id": "recall-user",
                        "key": "user_id",
                        "type": "text",
                        "value": "{{#1810000000001.user_id#}}",
                    },
                    {
                        "id": "recall-message",
                        "key": "message",
                        "type": "text",
                        "value": "{{#sys.query#}}",
                    },
                ],
                "type": "json",
            },
            "headers": "Content-Type: application/json",
            "method": "post",
            "params": "",
            "retry_config": {"max_retries": 2, "retry_enabled": True, "retry_interval": 200},
            "ssl_verify": True,
            "timeout": {"max_connect_timeout": 10, "max_read_timeout": 30, "max_write_timeout": 30},
            "url": "http://127.0.0.1:8791/api/recall",
            "variables": [],
        },
        height=140,
    ),
    node(
        PARSE,
        "code",
        "解析召回结果",
        720,
        300,
        {
            "code": PARSE_RECALL_CODE,
            "code_language": "python3",
            "outputs": {
                "memory_block": {"children": None, "type": "string"},
                "lore_block": {"children": None, "type": "string"},
                "memory_count": {"children": None, "type": "string"},
                "lore_count": {"children": None, "type": "string"},
            },
            "variables": [
                {"value_selector": [RECALL, "body"], "value_type": "string", "variable": "raw"}
            ],
        },
        height=140,
    ),
    node(
        BARKEEP,
        "llm",
        "阿九调酒",
        1060,
        300,
        {
            "context": {"enabled": False, "variable_selector": []},
            "model": MODEL,
            "prompt_template": [
                {"id": "p-barkeep-system", "role": "system", "text": BARKEEP_SYSTEM},
                {"id": "p-barkeep-user", "role": "user", "text": BARKEEP_USER},
            ],
            "variables": [],
            "vision": {"enabled": False},
        },
        height=130,
    ),
    node(
        MEMLLM,
        "llm",
        "抽取可记的事",
        1400,
        300,
        {
            "context": {"enabled": False, "variable_selector": []},
            "model": MODEL,
            "prompt_template": [
                {"id": "p-memory-system", "role": "system", "text": MEMORY_SYSTEM},
                {"id": "p-memory-user", "role": "user", "text": MEMORY_USER},
            ],
            "variables": [],
            "vision": {"enabled": False},
        },
        height=130,
    ),
    node(
        PARSE_MEM,
        "code",
        "解析记忆 JSON",
        1740,
        300,
        {
            "code": PARSE_MEMORY_CODE,
            "code_language": "python3",
            "outputs": {
                "should_remember": {"children": None, "type": "string"},
                "fact": {"children": None, "type": "string"},
            },
            "variables": [
                {"value_selector": [MEMLLM, "text"], "value_type": "string", "variable": "raw"}
            ],
        },
        height=130,
    ),
    node(
        BRANCH,
        "if-else",
        "要不要写入记忆",
        2080,
        300,
        {
            "cases": [
                {
                    "case_id": "case-remember-yes",
                    "conditions": [
                        {
                            "comparison_operator": "is",
                            "id": "cond-should-remember",
                            "value": "yes",
                            "varType": "string",
                            "variable_selector": [PARSE_MEM, "should_remember"],
                        }
                    ],
                    "id": "case-remember-yes",
                    "logical_operator": "and",
                }
            ]
        },
        height=200,
    ),
    node(
        REMEMBER,
        "http-request",
        "写入 seekdb 记忆",
        2420,
        180,
        {
            "authorization": {"config": None, "type": "no-auth"},
            "body": {
                "data": [
                    {
                        "id": "remember-user",
                        "key": "user_id",
                        "type": "text",
                        "value": "{{#1810000000001.user_id#}}",
                    },
                    {
                        "id": "remember-fact",
                        "key": "fact",
                        "type": "text",
                        "value": "{{#1810000000006.fact#}}",
                    },
                ],
                "type": "json",
            },
            "headers": "Content-Type: application/json",
            "method": "post",
            "params": "",
            "retry_config": {"max_retries": 2, "retry_enabled": True, "retry_interval": 200},
            "ssl_verify": True,
            "timeout": {"max_connect_timeout": 10, "max_read_timeout": 30, "max_write_timeout": 30},
            "url": "http://127.0.0.1:8791/api/remember",
            "variables": [],
        },
        height=140,
    ),
    node(
        ANS_A,
        "answer",
        "回复（已记住）",
        2760,
        180,
        {"answer": "{{#1810000000004.text#}}", "variables": []},
        height=110,
    ),
    node(
        ANS_B,
        "answer",
        "回复",
        2760,
        420,
        {"answer": "{{#1810000000004.text#}}", "variables": []},
        height=110,
    ),
]

edges = [
    edge(START, RECALL, "source", "start", "http-request"),
    edge(RECALL, PARSE, "source", "http-request", "code"),
    edge(PARSE, BARKEEP, "source", "code", "llm"),
    edge(BARKEEP, MEMLLM, "source", "llm", "llm"),
    edge(MEMLLM, PARSE_MEM, "source", "llm", "code"),
    edge(PARSE_MEM, BRANCH, "source", "code", "if-else"),
    edge(BRANCH, REMEMBER, "true", "if-else", "http-request"),
    edge(BRANCH, ANS_B, "false", "if-else", "answer"),
    edge(REMEMBER, ANS_A, "source", "http-request", "answer"),
]

doc = {
    "app": {
        "description": "深夜酒馆·阿九：用 Dify 编排、seekdb 存记忆的跨会话角色互动小游戏。",
        "icon": "🥃",
        "icon_background": "#FFEAD5",
        "mode": "advanced-chat",
        "name": "深夜酒馆 · 阿九",
        "use_icon_as_answer_icon": False,
    },
    "dependencies": [],
    "kind": "app",
    "version": "0.3.0",
    "workflow": {
        "conversation_variables": [],
        "environment_variables": [],
        "features": {
            "file_upload": {
                "allowed_file_extensions": [".JPG", ".JPEG", ".PNG", ".GIF", ".WEBP", ".SVG"],
                "allowed_file_types": ["image"],
                "allowed_file_upload_methods": ["local_file", "remote_url"],
                "enabled": False,
                "fileUploadConfig": {
                    "audio_file_size_limit": 500,
                    "batch_count_limit": 5,
                    "file_size_limit": 15,
                    "image_file_size_limit": 100,
                    "video_file_size_limit": 500,
                    "workflow_file_upload_limit": 10,
                },
                "image": {
                    "enabled": False,
                    "number_limits": 3,
                    "transfer_methods": ["local_file", "remote_url"],
                },
                "number_limits": 3,
            },
            "opening_statement": "（门上的铜铃响了一下）阿九擦着杯子抬头：“外边冷吧？坐。今天想喝点什么，还是先说说今天怎么了？”",
            "retriever_resource": {"enabled": False},
            "sensitive_word_avoidance": {"enabled": False},
            "speech_to_text": {"enabled": False},
            "suggested_questions": [
                "今天加班到十一点，老板还在群里发消息",
                "我又来了，老样子",
                "上周我是不是跟你说过一件很丢脸的事？",
            ],
            "suggested_questions_after_answer": {"enabled": False},
            "text_to_speech": {"enabled": False, "language": "", "voice": ""},
        },
        "graph": {
            "edges": edges,
            "nodes": nodes,
            "viewport": {"x": 0, "y": 0, "zoom": 0.6},
        },
    },
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as handle:
    yaml.safe_dump(doc, handle, allow_unicode=True, sort_keys=False, width=100000)

print("wrote", OUT)
print("nodes", len(nodes), "edges", len(edges))
print("bytes", os.path.getsize(OUT))
back = yaml.safe_load(open(OUT, encoding="utf-8"))
print("reparse ok:", back["app"]["mode"], len(back["workflow"]["graph"]["nodes"]))
print("json-serialisable:", bool(json.dumps(back)))