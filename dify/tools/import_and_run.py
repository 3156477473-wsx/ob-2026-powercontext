#!/usr/bin/env python3
"""Import the chatflow into a running Dify, publish it, then drive four turns and
save every raw SSE stream as evidence.

Usage:
    python3 tools/import_and_run.py --console http://127.0.0.1:18080 \
        --email ajiu@example.com --password 'Jiuguan#2026' \
        --dsl dsl/jiuguan-a-jiu.chatflow.yml --out samples/evidence

The script only uses Dify's public console API + Service API.  Everything it prints
or writes is produced by the running Dify engine.
"""
import argparse
import base64
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request

TURNS = [
    ("老周", "我叫老周，做审计的，喜欢苦一点的酒。", "new"),
    ("老周", "还记得我叫什么、做什么工作的吗？", "same"),
    ("小林", "第一次来，有什么推荐？", "new"),
    ("阿旺", '他说：“来杯"苦"的”。\n顺便问下，你们有「烟熏」味道的吗？', "new"),
]


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _cookie(self, name):
        for c in self.jar:
            if c.name == name:
                return c.value
        return ""

    def call(self, method, path, body=None, timeout=120):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-CSRF-Token", self._cookie("csrf_token"))
        if self._cookie("access_token"):
            req.add_header("Authorization", "Bearer " + self._cookie("access_token"))
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", "replace")
            raise RuntimeError(f"{method} {path} -> {err.code}: {raw[:400]}")
        return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw

    def login(self, email, password):
        payload = {"email": email, "password": base64.b64encode(password.encode()).decode(), "remember_me": True}
        self.call("POST", "/console/api/login", payload)
        if not self._cookie("access_token"):
            raise RuntimeError("login returned no access_token cookie")


def import_app(client, dsl_path):
    yaml_text = open(dsl_path, encoding="utf-8").read()
    res = client.call("POST", "/console/api/apps/imports", {"mode": "yaml-content", "yaml_content": yaml_text})
    return res["app_id"]


def publish(client, app_id):
    client.call("POST", f"/console/api/apps/{app_id}/workflows/publish")


def new_key(client, app_id):
    res = client.call("POST", f"/console/api/apps/{app_id}/api-keys", {})
    return res["token"]


def sse(base, key, query, user, conversation_id=""):
    body = {
        "inputs": {"user_id": user},
        "query": query,
        "response_mode": "streaming",
        "conversation_id": conversation_id,
        "user": user,
    }
    req = urllib.request.Request(
        base + "/v1/chat-messages",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    events, text, wf, conv = [], [], None, conversation_id
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            events.append(ev)
            wf = wf or ev.get("workflow_run_id")
            conv = ev.get("conversation_id") or conv
            if ev.get("event") == "message":
                text.append(ev.get("answer", ""))
    return {"conversation_id": conv, "workflow_run_id": wf, "answer": "".join(text), "events": events}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--console", default="http://127.0.0.1:18080")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--dsl", default="dsl/jiuguan-a-jiu.chatflow.yml")
    ap.add_argument("--out", default="samples/evidence")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    client = Client(args.console)
    client.login(args.email, args.password)
    app_id = import_app(client, args.dsl)
    publish(client, app_id)
    key = new_key(client, app_id)
    print("app_id", app_id, "key", key)

    summary, conv = [], ""
    for i, (user, query, mode) in enumerate(TURNS, 1):
        t0 = time.time()
        res = sse(args.console, key, query, user, conv if mode == "same" else "")
        dt = round(time.time() - t0, 2)
        conv = res["conversation_id"] or conv
        with open(os.path.join(args.out, f"run{i}.sse.jsonl"), "w", encoding="utf-8") as fh:
            for ev in res["events"]:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        recall, remember, nodes = {}, {}, []
        for ev in res["events"]:
            if ev.get("event") != "node_finished":
                continue
            data = ev.get("data") or {}
            nodes.append({"title": data.get("title"), "node_type": data.get("node_type"),
                          "status": data.get("status"), "elapsed_time": data.get("elapsed_time")})
            if data.get("title") == "解析召回结果":
                recall = data.get("outputs") or {}
            if data.get("title") == "写入 seekdb 记忆":
                outs = data.get("outputs") or {}
                remember = {"status": data.get("status"), "status_code": outs.get("status_code")}
        summary.append({
            "turn": i, "user": user, "query": query,
            "conversation_id": res["conversation_id"], "workflow_run_id": res["workflow_run_id"],
            "elapsed_sec": dt, "answer": res["answer"],
            "recall": {"memory_count": recall.get("memory_count"), "lore_count": recall.get("lore_count"),
                       "memory_block": recall.get("memory_block")},
            "remember": remember, "node_finished": nodes,
        })
        print(f"[turn {i}] user={user} wf={res['workflow_run_id']} mem={recall.get('memory_count')} {dt}s")
        print("   answer:", res["answer"][:120].replace("\n", " "))

    with open(os.path.join(args.out, "chat_transcript.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print("saved", os.path.join(args.out, "chat_transcript.json"))


if __name__ == "__main__":
    main()