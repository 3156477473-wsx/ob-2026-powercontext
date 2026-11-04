"""PowerContext 客户端：保存并复用任务状态。

通过 HTTP API 接入 PowerContext Server：
- 写入：POST /v1/scopes/{scope}/artifacts （family=atomic-memory）
- 检索：POST /v1/atomic-memory/search
- 列表：POST /v1/atomic-memory/list

任务状态以 kind=task-state 的原子记忆保存，
模块重启后可检索回来，用于构造后续上下文。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import requests


class PowerContextClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8100",
                 scope_id: Optional[str] = None, timeout: int = 10) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.scope_id = scope_id or self._ensure_scope()

    # ---------- Scope ----------
    def _find_custom_scope(self) -> Optional[str]:
        try:
            r = requests.get(f"{self.base}/v1/scopes", timeout=self.timeout)
            r.raise_for_status()
            for it in r.json().get("items", []):
                if it.get("title") == "MiniMax SDD 任务上下文":
                    return it["scope_id"]
        except Exception:
            pass
        return None

    def _ensure_scope(self) -> str:
        existing = self._find_custom_scope()
        if existing:
            return existing
        r = requests.post(
            f"{self.base}/v1/scopes",
            json={
                "title": "MiniMax SDD 任务上下文",
                "summary": "规格驱动开发：为 AI 助手提供任务所需的规格、代码与测试上下文",
                "idempotency_key": "scope-minimax-sdd-demo-v1",
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()["scope_id"]

    # ---------- 任务状态 ----------
    def save_task_state(self, text: str, summary: str) -> Dict:
        """把任务进展写入 PowerContext。"""
        r = requests.post(
            f"{self.base}/v1/scopes/{self.scope_id}/artifacts",
            json={
                "family": "atomic-memory",
                "content": {
                    "kind": "task-state",
                    "text": text,
                    "description": summary,
                },
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def search_task_state(self, query: str, limit: int = 5) -> List[Dict]:
        """检索任务状态，用于重启后恢复。"""
        r = requests.post(
            f"{self.base}/v1/atomic-memory/search",
            json={"scope_id": self.scope_id, "query": query, "limit": limit},
            timeout=self.timeout,
        )
        r.raise_for_status()
        out = []
        for hit in r.json().get("hits", []):
            m = hit.get("memory", {})
            out.append({
                "text": m.get("text", ""),
                "kind": m.get("kind", ""),
                "artifact_id": m.get("artifact", {}).get("artifact_id", ""),
                "state": m.get("state", ""),
                "score": hit.get("score", 0),
            })
        return out

    def list_task_states(self, limit: int = 20) -> List[Dict]:
        r = requests.post(
            f"{self.base}/v1/atomic-memory/list",
            json={"scope_id": self.scope_id, "kind": "task-state", "limit": limit},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return [
            {"text": it.get("text", ""), "artifact_id": it.get("artifact", {}).get("artifact_id", "")}
            for it in r.json().get("items", [])
        ]

    def health(self) -> bool:
        try:
            r = requests.get(f"{self.base}/health/ready", timeout=self.timeout)
            return r.status_code == 200 and r.json().get("status") == "ready"
        except Exception:
            return False