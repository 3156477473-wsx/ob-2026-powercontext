"""上下文模块 CLI。

用法：
  python -m ctx.cli index  --project <业务工程路径>
  python -m ctx.cli build  --task "为任务列表增加时间范围过滤"
  python -m ctx.cli save   --task "..." --summary "..." --status in_progress \
                           --done "..." --todo "..."
  python -m ctx.cli resume --task "..."      # 重启后读取任务状态
  python -m ctx.cli status
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .context_builder import TaskContextBuilder
from .powercontext_client import PowerContextClient
from .seekdb_store import SeekdbStore

DEFAULT_PROJECT = Path(__file__).resolve().parent.parent / "business"


def _store() -> SeekdbStore:
    return SeekdbStore(
        host=os.getenv("SEEKDB_HOST", "127.0.0.1"),
        port=int(os.getenv("SEEKDB_PORT", "2881")),
        user=os.getenv("SEEKDB_USER", "root"),
        password=os.getenv("SEEKDB_PASSWORD", ""),
        database=os.getenv("SEEKDB_DATABASE", "test"),
    )


def _pc() -> PowerContextClient:
    return PowerContextClient(
        base_url=os.getenv("POWERCONTEXT_URL", "http://127.0.0.1:8100"),
        scope_id=os.getenv("POWERCONTEXT_SCOPE"),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="SDD 任务上下文模块")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index", help="索引工程资料到 seekdb")
    p_index.add_argument("--project", default=str(DEFAULT_PROJECT))

    p_build = sub.add_parser("build", help="根据任务构造上下文")
    p_build.add_argument("--task", required=True)
    p_build.add_argument("--top-k", type=int, default=4)

    p_save = sub.add_parser("save", help="保存任务状态到 PowerContext")
    p_save.add_argument("--task", required=True)
    p_save.add_argument("--summary", required=True)
    p_save.add_argument("--status", default="in_progress")
    p_save.add_argument("--done", default="")
    p_save.add_argument("--todo", default="")

    p_resume = sub.add_parser("resume", help="重启后读取任务状态")
    p_resume.add_argument("--task", required=True)

    sub.add_parser("status", help="查看 seekdb 与 PowerContext 状态")

    args = ap.parse_args()

    if args.cmd == "index":
        pc = _pc()
        builder = TaskContextBuilder(_store(), pc)
        result = builder.index_project(Path(args.project))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.cmd == "build":
        pc = _pc()
        builder = TaskContextBuilder(_store(), pc)
        ctx = builder.build(args.task, top_k=args.top_k)
        print(json.dumps(ctx, ensure_ascii=False, indent=2))
        return

    if args.cmd == "save":
        text = (
            f"任务：{args.task}。"
            f"已完成：{args.done or '无'}。"
            f"待办：{args.todo or '无'}。"
            f"状态：{args.status}。"
        )
        pc = _pc()
        resp = pc.save_task_state(text, args.summary)
        print(json.dumps(resp, ensure_ascii=False, indent=2))
        return

    if args.cmd == "resume":
        pc = _pc()
        states = pc.search_task_state(args.task, limit=5)
        print(json.dumps({"scope_id": pc.scope_id, "states": states},
                         ensure_ascii=False, indent=2))
        return

    if args.cmd == "status":
        store = _store()
        pc = _pc()
        try:
            stats = store.stats()
        except Exception as exc:
            stats = {"error": str(exc)}
        print(json.dumps({
            "seekdb": {"stats": stats},
            "powercontext": {
                "healthy": pc.health(),
                "scope_id": pc.scope_id,
                "task_states": len(pc.list_task_states()),
            },
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()