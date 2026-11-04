"""回归测试：SPEC-001 ~ SPEC-004、SPEC-006 的既有行为。

这些测试在本次任务前后都必须通过——用于证明修改没有破坏原有行为。
"""

from datetime import datetime, timezone

import pytest

from src.task_service import NotFoundError, TaskService, ValidationError


@pytest.fixture
def svc():
    s = TaskService()
    s.create("写周报", tags=["work"])
    s.create("复习数据库", tags=["study", "db"])
    s.create("整理实验数据", tags=["study"])
    return s


# ---------- SPEC-001 ----------
def test_create_requires_title():
    with pytest.raises(ValidationError):
        TaskService().create("   ")


def test_create_returns_task_with_id():
    s = TaskService()
    t = s.create("第一件事")
    assert t.id == 1
    assert t.title == "第一件事"
    assert t.status == "todo"


def test_create_rejects_long_title():
    with pytest.raises(ValidationError):
        TaskService().create("x" * 201)


# ---------- SPEC-002 ----------
def test_default_status_is_todo(svc):
    assert all(t.status == "todo" for t in svc.list())


def test_invalid_status_rejected_on_update(svc):
    with pytest.raises(ValidationError) as exc:
        svc.update(1, status="unknown")
    assert "todo" in str(exc.value)


def test_valid_status_update(svc):
    t = svc.update(1, status="doing")
    assert t.status == "doing"


# ---------- SPEC-003 ----------
def test_list_filters_by_status(svc):
    svc.update(1, status="done")
    done = svc.list(status="done")
    assert [t.id for t in done] == [1]


def test_list_filters_by_tag(svc):
    study = svc.list(tag="study")
    assert sorted(t.id for t in study) == [2, 3]


def test_list_status_and_tag_is_and(svc):
    svc.update(2, status="done")
    result = svc.list(status="done", tag="study")
    assert [t.id for t in result] == [2]


def test_list_without_filter_returns_all(svc):
    assert len(svc.list()) == 3


# ---------- SPEC-004 ----------
def test_update_missing_task_raises(svc):
    with pytest.raises(NotFoundError):
        svc.update(999, title="x")


def test_partial_update_keeps_other_fields(svc):
    svc.update(1, description="补充说明")
    t = svc.get(1)
    assert t.description == "补充说明"
    assert t.title == "写周报"
    assert t.tags == ["work"]


# ---------- SPEC-006 ----------
def test_duplicate_tags_removed(svc):
    t = svc.create("测试标签", tags=["a", "a", "b"])
    assert t.tags == ["a", "b"]