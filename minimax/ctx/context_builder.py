"""上下文模块：根据开发任务，从 seekdb 中选出相关规格、代码与测试。

输出结构：
{
  "task": "任务描述",
  "specs":  [{"symbol","doc_path","score","excerpt"}],
  "code":   [{"symbol","doc_path","score","excerpt"}],
  "tests":  [{"symbol","doc_path","score","excerpt"}],
  "task_state": {"from_powercontext": [...], "summary": "..."},
  "sources": {"seekdb": {...}, "powercontext": {...}}
}
"""

from __future__ import annotations

from typing import Dict, List

from .indexer import collect
from .powercontext_client import PowerContextClient
from .seekdb_store import SeekdbStore

EXCERPT_LEN = 220


def _excerpt(text: str, n: int = EXCERPT_LEN) -> str:
    text = " ".join(text.split())
    return text[:n] + ("…" if len(text) > n else "")


class TaskContextBuilder:
    def __init__(self, store: SeekdbStore, pc: PowerContextClient) -> None:
        self.store = store
        self.pc = pc

    def index_project(self, root) -> Dict[str, int]:
        """把工程资料写入 seekdb，返回各类型数量。"""
        self.store.init_schema()
        self.store.clear()
        items = collect(root)
        n = self.store.upsert_many(items)
        return {"indexed": n, **self.store.stats()}

    def build(self, task: str, top_k: int = 4) -> Dict:
        """根据任务构造上下文。"""
        specs = self.store.search(task, top_k=top_k, doc_type="spec")
        code = self.store.search(task, top_k=top_k, doc_type="code")
        tests = self.store.search(task, top_k=top_k, doc_type="test")

        def pack(rows: List[Dict]) -> List[Dict]:
            return [
                {
                    "symbol": r["symbol"],
                    "doc_path": r["doc_path"],
                    "score": round(float(r["score"]), 4),
                    "excerpt": _excerpt(r["content"]),
                }
                for r in rows
            ]

        state = self.pc.search_task_state(task, limit=3)

        return {
            "task": task,
            "specs": pack(specs),
            "code": pack(code),
            "tests": pack(tests),
            "task_state": {
                "from_powercontext": state,
                "summary": state[0]["text"] if state else "无历史任务状态",
            },
            "sources": {
                "seekdb": self.store.stats(),
                "powercontext": {
                    "scope_id": self.pc.scope_id,
                    "task_state_count": len(state),
                },
            },
        }