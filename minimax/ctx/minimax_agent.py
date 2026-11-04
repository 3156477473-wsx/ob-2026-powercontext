"""MiniMax 接入：把任务上下文交给模型生成代码修改。

采用 MiniMax 开放平台 HTTP API（OpenAI 兼容协议）：
  POST https://api.minimaxi.com/v1/text/chatcompletion_v2

用法：
  python -m ctx.minimax_agent --task "..." --file src/task_service.py

设计：
- 无 API Key 或额度不足时，明确报错并给出提示，不静默失败
- 请求与响应都落盘到 records/，作为「MiniMax 实际参与」的证据
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

API_URL = os.getenv("MINIMAX_API_URL", "https://api.minimaxi.com/v1/text/chatcompletion_v2")
MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M1")

SYSTEM_PROMPT = """你是一个严谨的软件开发助手，负责按规格修改 Python 代码。

规则：
1. 只修改任务要求的范围，不改无关代码。
2. 必须保持已有行为和测试不变。
3. 输出格式：先给出完整的新文件内容，用 ```python 代码块包裹；再给出修改说明。
4. 不要省略代码，不要写 ... 占位。"""


class MiniMaxError(RuntimeError):
    """MiniMax 调用失败。"""


class MiniMaxAgent:
    def __init__(self, api_key: Optional[str] = None,
                 record_dir: Optional[Path] = None,
                 model: str = MODEL) -> None:
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY", "")
        self.model = model
        self.record_dir = Path(record_dir or Path(__file__).resolve().parent.parent / "records")
        self.record_dir.mkdir(parents=True, exist_ok=True)

    def _check_key(self) -> None:
        if not self.api_key:
            raise MiniMaxError(
                "未配置 MINIMAX_API_KEY 环境变量。请设置后重试：\n"
                "  export MINIMAX_API_KEY=sk-..."
            )

    def complete(self, messages: List[Dict[str, str]], max_tokens: int = 4000) -> str:
        """调用 MiniMax 对话接口，返回模型文本。"""
        self._check_key()
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        try:
            r = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )
        except requests.RequestException as exc:
            raise MiniMaxError(f"网络请求失败：{exc}") from exc

        if r.status_code != 200:
            raise MiniMaxError(f"HTTP {r.status_code}：{r.text[:400]}")

        data = r.json()
        base = data.get("base_resp", {})
        if base.get("status_code") not in (0, None):
            raise MiniMaxError(
                f"MiniMax 返回错误 {base.get('status_code')}：{base.get('status_msg')}"
            )

        choices = data.get("choices") or []
        if not choices:
            raise MiniMaxError(f"响应中没有 choices：{json.dumps(data, ensure_ascii=False)[:400]}")
        return choices[0]["message"]["content"]

    def propose_patch(self, task: str, context: Dict, target_file: Path,
                      extra_note: str = "") -> Dict:
        """根据上下文生成代码修改方案并落盘记录。"""
        original = Path(target_file).read_text(encoding="utf-8")

        ctx_text = _render_context(context)
        user = f"""## 开发任务
{task}

## 适用的规格
{ctx_text['specs']}

## 相关代码
{ctx_text['code']}

## 用于验证的测试
{ctx_text['tests']}

## 当前文件：{target_file}
```python
{original}
```

{('## 补充说明\n' + extra_note) if extra_note else ''}

请按规格完成修改，输出完整的新文件内容。"""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

        reply = self.complete(messages)
        new_code = _extract_code(reply)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        rec = {
            "timestamp": stamp,
            "model": self.model,
            "task": task,
            "target_file": str(target_file),
            "context_specs": [s["symbol"] for s in context.get("specs", [])],
            "context_code": [c["symbol"] for c in context.get("code", [])],
            "context_tests": [t["symbol"] for t in context.get("tests", [])],
            "request": messages,
            "response": reply,
            "extracted_code": new_code,
        }
        out = self.record_dir / f"minimax-{stamp}.json"
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

        return {"record": str(out), "code": new_code, "raw": reply}


def _extract_code(reply: str) -> str:
    """从回复中提取 python 代码块。"""
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", reply, re.DOTALL)
    if not blocks:
        return ""
    return max(blocks, key=len).strip() + "\n"


def _render_context(ctx: Dict) -> Dict[str, str]:
    def fmt(rows: List[Dict], label: str) -> str:
        if not rows:
            return f"（无相关{label}）"
        lines = []
        for r in rows:
            lines.append(f"- [{r['symbol']}] {r['doc_path']}（相关度 {r['score']}）")
            lines.append(f"  {r['excerpt']}")
        return "\n".join(lines)

    return {
        "specs": fmt(ctx.get("specs", []), "规格"),
        "code": fmt(ctx.get("code", []), "代码"),
        "tests": fmt(ctx.get("tests", []), "测试"),
    }


def main() -> None:
    """CLI：根据任务与上下文，让 MiniMax 生成代码修改。"""
    import argparse
    from pathlib import Path as _P

    from .context_builder import TaskContextBuilder
    from .powercontext_client import PowerContextClient
    from .seekdb_store import SeekdbStore

    ap = argparse.ArgumentParser(description="MiniMax 代码修改助手")
    ap.add_argument("--task", required=True, help="开发任务描述")
    ap.add_argument("--file", required=True, help="要修改的目标文件")
    ap.add_argument("--note", default="", help="补充说明")
    ap.add_argument("--dry-run", action="store_true", help="只打印上下文，不调用模型")
    args = ap.parse_args()

    store = SeekdbStore(
        host=os.getenv("SEEKDB_HOST", "127.0.0.1"),
        port=int(os.getenv("SEEKDB_PORT", "2881")),
        user=os.getenv("SEEKDB_USER", "root"),
        password=os.getenv("SEEKDB_PASSWORD", ""),
        database=os.getenv("SEEKDB_DATABASE", "test"),
    )
    pc = PowerContextClient(base_url=os.getenv("POWERCONTEXT_URL", "http://127.0.0.1:8100"))
    ctx = TaskContextBuilder(store, pc).build(args.task)

    print("=== 本次上下文 ===")
    for key in ("specs", "code", "tests"):
        print(f"[{key}]")
        for r in ctx.get(key, []):
            print(f"  - {r['symbol']} ({r['doc_path']}) score={r['score']}")
    if ctx.get("task_state", {}).get("summary"):
        print(f"[task_state] {ctx['task_state']['summary'][:120]}")

    if args.dry_run:
        return

    agent = MiniMaxAgent()
    result = agent.propose_patch(args.task, ctx, _P(args.file), args.note)
    print(f"\n=== 记录已保存: {result['record']} ===")
    print(f"=== 提取代码长度: {len(result['code'])} 字符 ===")
    print("\n=== 模型说明（前 800 字）===")
    print(result["raw"][:800])


if __name__ == "__main__":
    main()