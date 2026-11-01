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

"""Versioned context packs with prefix-reuse deltas for incremental transport."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CHUNK_BYTES = 512

_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})


class ContextPackError(Exception):
    """Report a context pack or delta that violates the wire protocol."""


@dataclass(frozen=True, slots=True)
class ContextPack:
    """One complete context body split into ordered, valid UTF-8 chunks."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...] | list[bytes], /) -> ContextPack:
        chunks = _coerce_items(items)
        digest = _pack_digest(chunks)
        return cls(chunks, digest, _pack_byte_count(chunks, digest))

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> ContextPack:
        return cls.build(_split_text(content, chunk_bytes))

    def to_bytes(self) -> bytes:
        return _canonical_json(_pack_payload(self.items, self.digest, self.byte_count))

    @classmethod
    def from_bytes(cls, payload: bytes | bytearray | memoryview, /) -> ContextPack:
        raw = _require_bytes(payload, "context pack")
        body = _load_object(raw, "context pack")
        if set(body) != _PACK_FIELDS:
            raise ContextPackError("context pack must contain exactly its four fields")
        if body["schema"] != PACK_SCHEMA:
            raise ContextPackError("context pack schema is not supported")
        items = _decode_items(body["items"], "context pack items")
        digest = _require_digest(body["digest"], "digest")
        byte_count = _require_count(body["byte_count"], "byte_count")
        if _pack_digest(items) != digest:
            raise ContextPackError("context pack digest does not match its items")
        if byte_count != len(raw):
            raise ContextPackError("context pack byte_count does not match its serialized size")
        return cls(items, digest, byte_count)


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A prefix of an existing pack plus the chunks needed to reach the next pack."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack, /) -> ContextPackDelta:
        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("delta endpoints must be context packs")
        prefix = 0
        limit = min(len(base.items), len(target.items))
        while prefix < limit and base.items[prefix] == target.items[prefix]:
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    def to_bytes(self) -> bytes:
        return _canonical_json(
            {
                "schema": DELTA_SCHEMA,
                "base_digest": self.base_digest,
                "target_digest": self.target_digest,
                "prefix_items": self.prefix_items,
                "appended": [base64.b64encode(item).decode("ascii") for item in self.appended],
            }
        )

    @classmethod
    def from_bytes(cls, payload: bytes | bytearray | memoryview, /) -> ContextPackDelta:
        raw = _require_bytes(payload, "context pack delta")
        body = _load_object(raw, "context pack delta")
        if set(body) != _DELTA_FIELDS:
            raise ContextPackError("context pack delta must contain exactly its five fields")
        if body["schema"] != DELTA_SCHEMA:
            raise ContextPackError("context pack delta schema is not supported")
        base_digest = _require_digest(body["base_digest"], "base_digest")
        target_digest = _require_digest(body["target_digest"], "target_digest")
        prefix_items = _require_count(body["prefix_items"], "prefix_items")
        appended = _decode_items(body["appended"], "context pack delta appended")
        return cls(base_digest, target_digest, prefix_items, appended)


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta, /) -> ContextPack:
    """Rebuild the target pack from a received base pack and its delta."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("delta application requires a pack and a delta")
    if base.digest != delta.base_digest:
        raise ContextPackError("delta base digest does not match the received pack")
    if not 0 <= delta.prefix_items <= len(base.items):
        raise ContextPackError("delta prefix exceeds the base pack")
    items = base.items[: delta.prefix_items] + delta.appended
    target = ContextPack.build(items)
    if target.digest != delta.target_digest:
        raise ContextPackError("delta target digest does not match the rebuilt pack")
    return target


def _split_text(content: str, chunk_bytes: int) -> tuple[bytes, ...]:
    if not isinstance(content, str):
        raise ContextPackError("context content must be text")
    if not isinstance(chunk_bytes, int) or isinstance(chunk_bytes, bool) or chunk_bytes < 1:
        raise ContextPackError("chunk_bytes must be a positive integer")
    items: list[bytes] = []
    current = bytearray()
    for character in content:
        encoded = character.encode("utf-8")
        if len(encoded) > chunk_bytes:
            raise ContextPackError("chunk_bytes cannot hold one encoded character")
        if len(current) + len(encoded) > chunk_bytes:
            items.append(bytes(current))
            current = bytearray()
        current.extend(encoded)
    if current:
        items.append(bytes(current))
    return tuple(items)


def _coerce_items(items: object) -> tuple[bytes, ...]:
    if not isinstance(items, (tuple, list)):
        raise ContextPackError("context pack items must be a tuple of bytes")
    chunks: list[bytes] = []
    for item in items:
        if not isinstance(item, (bytes, bytearray, memoryview)):
            raise ContextPackError("context pack items must be bytes")
        chunks.append(bytes(item))
    return tuple(chunks)


def _pack_payload(items: tuple[bytes, ...], digest: str, byte_count: int) -> dict[str, Any]:
    return {
        "schema": PACK_SCHEMA,
        "items": [base64.b64encode(item).decode("ascii") for item in items],
        "digest": digest,
        "byte_count": byte_count,
    }


def _pack_unsigned(items: tuple[bytes, ...]) -> dict[str, Any]:
    return {
        "schema": PACK_SCHEMA,
        "items": [base64.b64encode(item).decode("ascii") for item in items],
    }


def _pack_digest(items: tuple[bytes, ...]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(_pack_unsigned(items))).hexdigest()


def _pack_byte_count(items: tuple[bytes, ...], digest: str) -> int:
    byte_count = 0
    while True:
        size = len(_canonical_json(_pack_payload(items, digest, byte_count)))
        if size == byte_count:
            return size
        byte_count = size


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _require_bytes(payload: object, label: str) -> bytes:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ContextPackError(f"{label} must be serialized bytes")
    return bytes(payload)


def _load_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(body, dict):
        raise ContextPackError(f"{label} must be a JSON object")
    return body


def _decode_items(value: object, label: str) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError(f"{label} must be a list")
    items: list[bytes] = []
    for encoded in value:
        if not isinstance(encoded, str):
            raise ContextPackError(f"{label} must contain Base64 strings")
        try:
            items.append(base64.b64decode(encoded.encode("ascii"), validate=True))
        except (UnicodeEncodeError, binascii.Error) as error:
            raise ContextPackError(f"{label} contains invalid Base64") from error
    return tuple(items)


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ContextPackError(f"{field} must be a sha256 digest")
    if any(character not in "0123456789abcdef" for character in value[7:]):
        raise ContextPackError(f"{field} must be lowercase hexadecimal")
    return value


def _require_count(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContextPackError(f"{field} must be a non-negative integer")
    return value


__all__ = [
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "DEFAULT_CHUNK_BYTES",
    "DELTA_SCHEMA",
    "PACK_SCHEMA",
    "apply_context_pack_delta",
]