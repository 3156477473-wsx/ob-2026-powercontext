# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Propagate Source availability through a per-scope evidence dependency DAG."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.runtime.models import RetireMemoryEntryRequest
from powercontext.sources.models import SourceRef

_TABLE = "pc_source_lifecycle_nodes"
_KINDS = frozenset({"source", "memory", "topic"})
_POLICIES = frozenset({"all", "any"})
_PURPOSES = frozenset({"generation", "audit"})


class SourceLifecycleError(ValueError):
    """Report an invalid lifecycle registration, event, or resolution."""


class SourceLifecycleEvent(BaseModel):
    """One caller-supplied availability change for a registered Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    reason: str
    revision: int = Field(gt=0, strict=True)
    sequence: int = Field(gt=0, strict=True)
    available: bool = Field(strict=True)

    @field_validator("node_id", "reason")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError("lifecycle text must be a non-empty trimmed string")  # noqa: TRY003
        return value


class LifecycleApplication:
    """Expose the per-scope lifecycle service and scope-wide topic filtering."""

    def __init__(self, runtime: object, database: object) -> None:
        self._runtime = runtime
        self._database = database
        self._table_ready = False

    async def initialize(self) -> None:
        await self._ensure_table()

    async def _ensure_table(self) -> None:
        if self._table_ready:
            return
        from sqlalchemy import text

        async with self._database.transaction() as connection:
            await connection.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                    " scope_id TEXT NOT NULL,"
                    " node_id TEXT NOT NULL,"
                    " ordinal INTEGER NOT NULL,"
                    " kind TEXT NOT NULL,"
                    " ref_json TEXT NOT NULL,"
                    " parents_json TEXT NOT NULL,"
                    " policy TEXT NOT NULL,"
                    " revision INTEGER NOT NULL,"
                    " available INTEGER NOT NULL,"
                    " active INTEGER NOT NULL,"
                    " sequence INTEGER NOT NULL,"
                    " last_event_json TEXT NOT NULL,"
                    " PRIMARY KEY (scope_id, node_id))"
                )
            )
        self._table_ready = True

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self, scope_id)

    async def inactive_topic_artifact_ids(self, scope_id: str, /) -> frozenset[str]:
        await self._ensure_table()
        from sqlalchemy import text

        async with self._database.transaction() as connection:
            rows = (
                await connection.execute(
                    text(f"SELECT ref_json FROM {_TABLE} WHERE scope_id = :scope_id AND kind = 'topic' AND active = 0"),
                    {"scope_id": scope_id},
                )
            ).all()
        identifiers: set[str] = set()
        for (ref_json,) in rows:
            try:
                identifiers.add(str(json.loads(ref_json)["artifact_id"]))
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
        return frozenset(identifiers)


class _Node:
    __slots__ = (
        "node_id",
        "ordinal",
        "kind",
        "ref_json",
        "parents",
        "policy",
        "revision",
        "available",
        "active",
        "sequence",
        "last_event_json",
    )

    def __init__(self, row: Any) -> None:
        self.node_id = row[0]
        self.ordinal = int(row[1])
        self.kind = row[2]
        self.ref_json = row[3]
        self.parents = tuple(json.loads(row[4]))
        self.policy = row[5]
        self.revision = int(row[6])
        self.available = bool(row[7])
        self.active = bool(row[8])
        self.sequence = int(row[9])
        self.last_event_json = row[10]


_COLUMNS = (
    "node_id, ordinal, kind, ref_json, parents_json, policy, revision, available, active, sequence, last_event_json"
)


class ScopedSourceLifecycle:
    """Register evidence nodes and apply availability events for one scope."""

    def __init__(self, application: LifecycleApplication, scope_id: str) -> None:
        self._application = application
        self._runtime = application._runtime
        self._database = application._database
        self.scope_id = scope_id

    async def register_source(self, node_id: str, source_ref: SourceRef, /, revision: int) -> list[str]:
        self._require_positive(revision, "revision")
        records = self._runtime.records.for_scope(self.scope_id)
        try:
            await records.get_source(source_ref.source_type, source_ref.source_id)
        except Exception as error:
            raise SourceLifecycleError("registered Source must be readable") from error
        return await self._register(
            node_id,
            kind="source",
            ref_json=source_ref.model_dump(mode="json"),
            parents=(),
            policy="all",
            revision=revision,
            available=True,
        )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: tuple[str, ...],
        policy: str,
    ) -> list[str]:
        from powercontext.builtin.runtime import GetMemoryEntryRequest

        try:
            await self._runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=citation))
        except Exception as error:
            raise SourceLifecycleError("registered Memory entry must be readable") from error
        return await self._register(
            node_id,
            kind="memory",
            ref_json=citation.model_dump(mode="json"),
            parents=parents,
            policy=policy,
            revision=1,
            available=True,
        )

    async def register_topic(
        self,
        node_id: str,
        reference: ArtifactRef,
        /,
        *,
        parents: tuple[str, ...],
        policy: str,
    ) -> list[str]:
        records = self._runtime.records.for_scope(self.scope_id)
        try:
            await records.get_artifact_revision(reference.family, reference.artifact_id, reference.revision)
        except Exception as error:
            raise SourceLifecycleError("registered Topic Memory artifact must be readable") from error
        return await self._register(
            node_id,
            kind="topic",
            ref_json=reference.model_dump(mode="json"),
            parents=parents,
            policy=policy,
            revision=1,
            available=True,
        )

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("apply requires a SourceLifecycleEvent")
        await self._application._ensure_table()
        node = await self._load(event.node_id)
        if node is None:
            raise SourceLifecycleError(f"unknown lifecycle node {event.node_id!r}")
        if node.kind != "source":
            raise SourceLifecycleError("availability events apply only to registered Sources")
        if event.revision != node.revision:
            raise SourceLifecycleError("event revision does not match the registered Source revision")
        if event.sequence < node.sequence:
            raise SourceLifecycleError("event sequence must increase monotonically")
        if event.sequence == node.sequence:
            if node.last_event_json == self._event_json(event):
                return await self._active_ids()
            raise SourceLifecycleError("event sequence was already used by a different event")

        rows = await self._load_all()
        available = {node.node_id: event.available}
        states: dict[str, bool] = {}
        for row in rows:
            if row.kind == "source":
                states[row.node_id] = available.get(row.node_id, row.available)
            else:
                support = [states.get(parent, False) for parent in row.parents]
                states[row.node_id] = all(support) if row.policy == "all" else any(support)

        for row in rows:
            target = states[row.node_id]
            if target == row.active:
                continue
            if row.kind == "memory":
                await self._sync_memory(row, target)
            await self._set_active(row, target)

        await self._finish_event(node, event)
        return sorted(node_id for node_id, active in states.items() if active)

    async def resolve(self, node_id: str, /, *, purpose: str) -> object:
        if purpose not in _PURPOSES:
            raise SourceLifecycleError(f"unsupported lifecycle purpose {purpose!r}")
        node = await self._load(node_id)
        if node is None:
            raise SourceLifecycleError(f"unknown lifecycle node {node_id!r}")
        if purpose == "generation" and not node.active:
            raise SourceLifecycleError(f"lifecycle node {node_id!r} is unavailable for generation")
        payload = json.loads(node.ref_json)
        if node.kind == "memory":
            return MemoryCitation.model_validate(payload)
        if node.kind == "topic":
            return ArtifactRef.model_validate(payload)
        return SourceRef.model_validate(payload)

    async def _register(
        self,
        node_id: str,
        *,
        kind: str,
        ref_json: dict[str, Any],
        parents: tuple[str, ...],
        policy: str,
        revision: int,
        available: bool,
    ) -> list[str]:
        if kind not in _KINDS:
            raise SourceLifecycleError("unsupported lifecycle node kind")
        self._require_text(node_id, "node_id")
        if policy not in _POLICIES:
            raise SourceLifecycleError("lifecycle policy must be 'all' or 'any'")
        if kind != "source":
            if not parents:
                raise SourceLifecycleError("derived nodes require at least one parent")
            if len(set(parents)) != len(parents):
                raise SourceLifecycleError("derived nodes must not repeat a parent")
            for parent in parents:
                self._require_text(parent, "parent")
                if parent == node_id:
                    raise SourceLifecycleError("a node may not depend on itself")
        await self._application._ensure_table()

        rows = await self._load_all()
        existing = next((row for row in rows if row.node_id == node_id), None)
        ref_text = json.dumps(ref_json, sort_keys=True, separators=(",", ":"))
        parents_json = json.dumps(list(parents), sort_keys=True, separators=(",", ":"))
        if existing is not None:
            if (
                existing.kind == kind
                and existing.ref_json == ref_text
                and existing.parents == parents
                and existing.policy == policy
            ):
                return sorted(row.node_id for row in rows if row.active)
            raise SourceLifecycleError("lifecycle node is already registered with a different binding")

        by_id = {row.node_id: row for row in rows}
        for parent in parents:
            if parent not in by_id:
                raise SourceLifecycleError(f"parent {parent!r} must be registered before its child")
        support = [by_id[parent].active for parent in parents]
        active = available if kind == "source" else (all(support) if policy == "all" else any(support))
        ordinal = max((row.ordinal for row in rows), default=0) + 1

        from sqlalchemy import text

        async with self._database.transaction() as connection:
            await connection.execute(
                text(
                    f"INSERT INTO {_TABLE} (scope_id, node_id, ordinal, kind, ref_json, parents_json, policy,"
                    " revision, available, active, sequence, last_event_json)"
                    " VALUES (:scope_id, :node_id, :ordinal, :kind, :ref_json, :parents_json, :policy,"
                    " :revision, :available, :active, 0, '')"
                ),
                {
                    "scope_id": self.scope_id,
                    "node_id": node_id,
                    "ordinal": ordinal,
                    "kind": kind,
                    "ref_json": ref_text,
                    "parents_json": parents_json,
                    "policy": policy,
                    "revision": revision,
                    "available": 1 if available else 0,
                    "active": 1 if active else 0,
                },
            )
        if kind == "memory" and not active:
            node = await self._load(node_id)
            if node is not None:
                await self._sync_memory(node, False)
        return sorted(row.node_id for row in rows if row.active) + ([node_id] if active else [])

    async def _sync_memory(self, node: _Node, target_active: bool) -> None:
        payload = json.loads(node.ref_json)
        entry_id = str(payload.get("entry_id", ""))
        memory = self._runtime.memory.for_scope(self.scope_id)
        page = await memory.list(include_inactive=True)
        record = next((row for row in page.entries if row.entry.entry_id == entry_id), None)
        if record is None:
            raise SourceLifecycleError(f"Memory entry {entry_id!r} is no longer readable")
        citation = MemoryCitation(
            memory_ref=record.memory_ref,
            entry_id=record.entry.entry_id,
            entry_version_id=record.entry.entry_version_id,
        )
        if target_active:
            await memory.reactivate(citation)
        else:
            await memory.retire(RetireMemoryEntryRequest(citation=citation, reason="source lifecycle"))

    async def _set_active(self, node: _Node, active: bool) -> None:
        from sqlalchemy import text

        async with self._database.transaction() as connection:
            await connection.execute(
                text(f"UPDATE {_TABLE} SET active = :active WHERE scope_id = :scope_id AND node_id = :node_id"),
                {"active": 1 if active else 0, "scope_id": self.scope_id, "node_id": node.node_id},
            )

    async def _finish_event(self, node: _Node, event: SourceLifecycleEvent) -> None:
        from sqlalchemy import text

        async with self._database.transaction() as connection:
            await connection.execute(
                text(
                    f"UPDATE {_TABLE} SET available = :available, sequence = :sequence, last_event_json = :event_json"
                    " WHERE scope_id = :scope_id AND node_id = :node_id"
                ),
                {
                    "available": 1 if event.available else 0,
                    "sequence": event.sequence,
                    "event_json": self._event_json(event),
                    "scope_id": self.scope_id,
                    "node_id": node.node_id,
                },
            )

    async def _active_ids(self) -> list[str]:
        return sorted(row.node_id for row in await self._load_all() if row.active)

    async def _load(self, node_id: str) -> _Node | None:
        from sqlalchemy import text

        await self._application._ensure_table()
        async with self._database.transaction() as connection:
            row = (
                await connection.execute(
                    text(f"SELECT {_COLUMNS} FROM {_TABLE} WHERE scope_id = :scope_id AND node_id = :node_id"),
                    {"scope_id": self.scope_id, "node_id": node_id},
                )
            ).first()
        return None if row is None else _Node(row)

    async def _load_all(self) -> list[_Node]:
        from sqlalchemy import text

        await self._application._ensure_table()
        async with self._database.transaction() as connection:
            rows = (
                await connection.execute(
                    text(f"SELECT {_COLUMNS} FROM {_TABLE} WHERE scope_id = :scope_id ORDER BY ordinal"),
                    {"scope_id": self.scope_id},
                )
            ).all()
        return [_Node(row) for row in rows]

    @staticmethod
    def _event_json(event: SourceLifecycleEvent) -> str:
        return json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _require_text(value: object, field: str) -> None:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise SourceLifecycleError(f"{field} must be a non-empty trimmed string")

    @staticmethod
    def _require_positive(value: object, field: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise SourceLifecycleError(f"{field} must be a positive integer")


__all__ = ["LifecycleApplication", "ScopedSourceLifecycle", "SourceLifecycleError", "SourceLifecycleEvent"]