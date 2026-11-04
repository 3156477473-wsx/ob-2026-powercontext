"""SPEC-005 参考实现：时间范围过滤。

本文件是「修改后」的目标代码，用于：
1. 验证目标测试确实能检验 SPEC-005；
2. 作为 MiniMax 生成结果的对照基准。

评审可以直接把本文件覆盖到 business/src/task_service.py 复现「修改后」状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

VALID_STATUS = ("todo", "doing", "done", "archived")


class ValidationError(ValueError):
    """输入校验失败，对应 HTTP 400。"""


class NotFoundError(LookupError):
    """资源不存在，对应 HTTP 404。"""


def _parse_iso(value: str, field_name: str) -> datetime:
    """解析 ISO 8601 时间字符串，失败抛 ValidationError（SPEC-005 约束 3）。"""
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            f"{field_name} 不是合法的 ISO 8601 时间：{value!r}"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class Task:
    id: int
    title: str
    description: str = ""
    status: str = "todo"
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "tags": list(self.tags),
            "created_at": self.created_at.isoformat(),
        }


class TaskService:
    """内存实现的任务服务，便于测试复现。"""

    def __init__(self) -> None:
        self._tasks: Dict[int, Task] = {}
        self._next_id = 1

    # ---------- SPEC-001 ----------
    def create(self, title: str, description: str = "",
               tags: Optional[List[str]] = None,
               created_at: Optional[datetime] = None) -> Task:
        title = (title or "").strip()
        if not title or len(title) > 200:
            raise ValidationError("title 必填，长度 1-200 字符")

        task = Task(
            id=self._next_id,
            title=title,
            description=description or "",
            tags=self._normalize_tags(tags),
        )
        if created_at is not None:
            task.created_at = created_at

        self._tasks[task.id] = task
        self._next_id += 1
        return task

    # ---------- SPEC-002 ----------
    @staticmethod
    def _validate_status(status: str) -> str:
        if status not in VALID_STATUS:
            raise ValidationError(
                f"非法状态 {status!r}，允许的取值：{', '.join(VALID_STATUS)}"
            )
        return status

    # ---------- SPEC-006 ----------
    @staticmethod
    def _normalize_tags(tags: Optional[List[str]]) -> List[str]:
        if not tags:
            return []
        seen: List[str] = []
        for t in tags:
            t = str(t).strip()
            if t and t not in seen:
                seen.append(t)
        return seen

    # ---------- SPEC-003 + SPEC-005 ----------
    def list(
        self,
        status: Optional[str] = None,
        tag: Optional[str] = None,
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
    ) -> List[Task]:
        """按状态、标签与创建时间范围过滤任务。

        SPEC-003：status 与 tag 同时存在时是 AND 语义。
        SPEC-005：新增 created_from / created_to，边界含，与既有条件 AND。
        """
        if status is not None:
            self._validate_status(status)

        lower = _parse_iso(created_from, "created_from") if created_from else None
        upper = _parse_iso(created_to, "created_to") if created_to else None

        result: List[Task] = []
        for task in self._tasks.values():
            if status is not None and task.status != status:
                continue
            if tag is not None and tag not in task.tags:
                continue
            if lower is not None and task.created_at < lower:
                continue
            if upper is not None and task.created_at > upper:
                continue
            result.append(task)

        result.sort(key=lambda t: t.id)
        return result

    # ---------- SPEC-004 ----------
    def update(
        self,
        task_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise NotFoundError(f"任务 {task_id} 不存在")

        if title is not None:
            title = title.strip()
            if not title or len(title) > 200:
                raise ValidationError("title 长度 1-200 字符")
            task.title = title
        if description is not None:
            task.description = description
        if status is not None:
            task.status = self._validate_status(status)
        if tags is not None:
            task.tags = self._normalize_tags(tags)

        return task

    def get(self, task_id: int) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise NotFoundError(f"任务 {task_id} 不存在")
        return task