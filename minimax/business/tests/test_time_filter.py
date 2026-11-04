"""目标测试：SPEC-005 时间范围过滤。

这些测试在本次任务开始前必须全部失败（功能未实现），
在 MiniMax 参与完成代码修改后必须全部通过。
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.task_service import ValidationError


@pytest.fixture
def svc():
    s = TaskServiceWithTime()
    # 用固定时间构造三条任务，便于断言
    base = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
    s.create("一月的任务", tags=["work"], created_at=base)
    s.create("二月上旬", tags=["work"], created_at=base + timedelta(days=25))
    s.create("二月中旬", tags=["study"], created_at=base + timedelta(days=40))
    return s


from src.task_service import TaskService as TaskServiceWithTime  # noqa: E402


# ---------- 单边界 ----------
def test_created_from_only(svc):
    result = svc.list(created_from="2026-02-01T00:00:00+00:00")
    assert [t.title for t in result] == ["二月上旬", "二月中旬"]


def test_created_to_only(svc):
    result = svc.list(created_to="2026-02-01T00:00:00+00:00")
    assert [t.title for t in result] == ["一月的任务"]


# ---------- 双边界 ----------
def test_both_bounds(svc):
    result = svc.list(
        created_from="2026-01-01T00:00:00+00:00",
        created_to="2026-02-10T00:00:00+00:00",
    )
    assert [t.title for t in result] == ["一月的任务", "二月上旬"]


def test_bounds_are_inclusive(svc):
    result = svc.list(
        created_from="2026-01-10T12:00:00+00:00",
        created_to="2026-01-10T12:00:00+00:00",
    )
    assert [t.title for t in result] == ["一月的任务"]


# ---------- 与既有过滤组合（AND） ----------
def test_time_with_status(svc):
    svc.update(1, status="done")
    result = svc.list(status="done", created_from="2026-01-01T00:00:00+00:00")
    assert [t.title for t in result] == ["一月的任务"]


def test_time_with_tag(svc):
    result = svc.list(tag="work", created_from="2026-02-01T00:00:00+00:00")
    assert [t.title for t in result] == ["二月上旬"]


# ---------- 非法输入 ----------
def test_invalid_time_format_rejected(svc):
    with pytest.raises(ValidationError):
        svc.list(created_from="2026/01/01")


# ---------- 兼容性：不传时间参数时行为不变 ----------
def test_no_time_params_returns_all(svc):
    assert len(svc.list()) == 3