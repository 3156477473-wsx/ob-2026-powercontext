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

"""Capture Pi session branch history as per-event Sources with resumable progress."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Connector,
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    SourceDefinition,
    TextEvidence,
)
from powercontext.sources.models import Source, SourceMaterialization

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
PI_SESSION_CONNECTOR_VERSION = "1"
PI_EVENT_IDENTITY_PREFIX = "pi"

_SESSION_TYPE = "session"
_SESSION_VERSION = 3
_VISIBLE_MESSAGE_ROLES = frozenset({"user", "assistant", "toolResult", "bashExecution"})
_SUMMARY_TYPES = frozenset({"compaction", "branch_summary"})


class PiSessionInput(BaseModel):
    """One complete Pi JSONL session archive and the branch leaf to capture."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible Pi event on the selected branch, kept with its raw record."""

    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """A captured Pi event addressable by its session and event identity."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Build the stable identity shared by a Pi event Source and its citation."""

    session = _require_non_blank(session_id, "session_id")
    event = _require_non_blank(event_id, "event_id")
    identity = f"{PI_EVENT_IDENTITY_PREFIX}:{quote(session, safe='')}:{quote(event, safe='')}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"pi event identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return identity


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse the selected branch and fully validate the archive before returning."""

    records = _load_records(_decode(value.content))
    if not records:
        raise ValueError("pi session must start with a session header")
    header = records[0]
    if header.get("type") != _SESSION_TYPE:
        raise ValueError("pi session must start with a session header")
    version = header.get("version")
    if version != _SESSION_VERSION or isinstance(version, bool):
        raise ValueError("pi session header must declare version 3")
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("pi session header must declare a non-empty id")

    nodes = records[1:]
    if not nodes:
        raise ValueError("pi session must contain at least one graph node")

    by_id: dict[str, dict[str, Any]] = {}
    parents: dict[str, str | None] = {}
    order: list[str] = []
    for node in nodes:
        event_id = node.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("every pi session record must declare a non-empty id")
        if event_id in by_id:
            raise ValueError(f"duplicate pi session id {event_id!r}")
        parent_id = node.get("parentId")
        if parent_id is not None:
            if not isinstance(parent_id, str) or not parent_id:
                raise ValueError("parentId must be null or a known id")
            if parent_id not in by_id:
                raise ValueError(f"parent {parent_id!r} must be defined before {event_id!r}")
        by_id[event_id] = node
        parents[event_id] = parent_id
        order.append(event_id)

    leaf_id = value.leaf_id
    if leaf_id is None:
        leaf_id = order[-1]
    elif not isinstance(leaf_id, str) or leaf_id not in by_id:
        raise ValueError(f"leaf {leaf_id!r} is not present in the pi session")

    chain: list[str] = []
    cursor: str | None = leaf_id
    while cursor is not None:
        chain.append(cursor)
        cursor = parents[cursor]
    chain.reverse()

    events: list[PiEventInput] = []
    for event_id in chain:
        record = by_id[event_id]
        event = _build_event(session_id, event_id, parents[event_id], record)
        if event is not None:
            events.append(event)
    return tuple(events)


class PiEventSourceAdapter:
    """Resolve and read captured Pi events without rewriting their text."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose one captured Pi event as standard text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )



class PiSessionConnector:
    """Import the visible events of the selected Pi branch exactly once."""

    name = PI_SESSION_CONNECTOR_NAME
    version = PI_SESSION_CONNECTOR_VERSION
    source_definitions: frozenset[str] = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        content = self._path.read_bytes()
        events = parse_pi_session(PiSessionInput(content=content, leaf_id=self._leaf_id))
        imported = _load_checkpoint(session.checkpoint)
        for event in events:
            identity = pi_event_source_id(event.session_id, event.event_id)
            digest = _record_digest(event.record)
            known = imported.get(identity)
            if known is not None:
                if known != digest:
                    raise ValueError(
                        f"pi event {event.event_id!r} was modified after it was imported"
                    )
                continue
            await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)
            imported[identity] = digest
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"events": imported},
        )


def _build_event(
    session_id: str,
    event_id: str,
    parent_id: str | None,
    record: dict[str, Any],
) -> PiEventInput | None:
    event_type = record.get("type")
    if not isinstance(event_type, str):
        return None
    role: str | None = None
    body: str | None = None
    if event_type == "message":
        message = record.get("message")
        if isinstance(message, dict):
            role = message.get("role") if isinstance(message.get("role"), str) else None
            body = _message_body(role, message)
    elif event_type in _SUMMARY_TYPES:
        role = event_type
        summary = record.get("summary")
        body = summary if isinstance(summary, str) and summary else None
    elif event_type == "custom_message":
        role = "custom"
        body = _content_text(record.get("content"))
    if role is None or not body:
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=event_id,
        parent_id=parent_id,
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _message_body(role: str | None, message: dict[str, Any]) -> str | None:
    if role in {"user", "assistant"}:
        return _content_text(message.get("content")) or None
    if role == "toolResult":
        tool_name = _string_or_empty(message.get("toolName"))
        tool_call_id = _string_or_empty(message.get("toolCallId"))
        text = _content_text(message.get("content"))
        return f"[tool_result {tool_name} {tool_call_id}] {text}"
    if role == "bashExecution":
        command = _string_or_empty(message.get("command"))
        output = _string_or_empty(message.get("output"))
        return f"$ {command}\n{output}"
    return None


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif block_type == "toolCall":
                name = _string_or_empty(block.get("name"))
                call_id = _string_or_empty(block.get("id"))
                arguments = block.get("arguments")
                parts.append(f"[tool_call {name} {call_id}] {_compact_json(arguments)}")
        return "\n".join(parts)
    return ""


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(content: object) -> str:
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise ValueError("pi session content must be supplied as bytes")
    try:
        return bytes(content).decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("pi session content must be valid utf-8") from error


def _load_records(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"pi session line is not valid json: {error}") from error
        if not isinstance(record, dict):
            raise ValueError("every pi session line must be a json object")
        records.append(record)
    return records


def _record_digest(record: dict[str, JsonValue]) -> str:
    return hashlib.sha256(_compact_json(record).encode("utf-8")).hexdigest()


def _load_checkpoint(checkpoint: object) -> dict[str, str]:
    if checkpoint is None:
        return {}
    if not isinstance(checkpoint, dict):
        raise ValueError("pi session checkpoint must be a json object")
    events = checkpoint.get("events", {})
    if not isinstance(events, dict):
        raise ValueError("pi session checkpoint events must be a json object")
    imported: dict[str, str] = {}
    for identity, digest in events.items():
        if not isinstance(identity, str) or not isinstance(digest, str):
            raise ValueError("pi session checkpoint entries must be string pairs")
        imported[identity] = digest
    return imported


def _string_or_empty(value: object) -> str:
    return value if isinstance(value, str) else ""


def _require_non_blank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


PI_EVENT_SOURCE_ADAPTER = PiEventSourceAdapter()
PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = AdapterSourceDefinition(
    PI_EVENT_SOURCE_ADAPTER,
    projections=(PiEventTextEvidenceProjection(),),
)

__all__ = [
    "PI_EVENT_SOURCE_ADAPTER",
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_SESSION_CONNECTOR_NAME",
    "PI_SESSION_CONNECTOR_VERSION",
    "PiEventInput",
    "PiEventSource",
    "PiEventSourceAdapter",
    "PiEventTextEvidenceProjection",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]