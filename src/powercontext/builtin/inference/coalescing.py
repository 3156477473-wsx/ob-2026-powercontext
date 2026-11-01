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

"""Bounded cross-call embedding coalescing with a successful-vector LRU."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from powercontext.builtin.inference.models import EmbeddingResult, InferenceUsage


@dataclass(slots=True)
class _Batch:
    """One in-flight underlying request shared by every waiter of its texts."""

    texts: tuple[str, ...]
    usage: InferenceUsage | None = None


@dataclass(slots=True)
class _Pending:
    """One text currently being computed or waiting to join a batch."""

    future: asyncio.Future[tuple[float, ...]]
    batch: _Batch | None = None


class CoalescingEmbeddingModel:
    """Share duplicate embedding work across concurrent calls and cache successes."""

    def __init__(
        self,
        model: object,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if not isinstance(max_batch_size, int) or isinstance(max_batch_size, bool) or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")
        if not isinstance(coalesce_ms, (int, float)) or isinstance(coalesce_ms, bool) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be a non-negative number")
        if not isinstance(cache_size, int) or isinstance(cache_size, bool) or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")
        self._model = model
        self.profile = model.profile
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = float(coalesce_ms) / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()
        self._pending: dict[str, _Pending] = {}
        self._flush_task: asyncio.Task[None] | None = None

    async def embed(self, texts: Iterable[str]) -> EmbeddingResult:
        """Return vectors in the caller's original order, sharing duplicate work."""

        values = tuple(texts)
        if not values:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))
        loop = asyncio.get_running_loop()
        entries: list[tuple[tuple[float, ...] | None, _Pending | None]] = []
        awaiting_batch = False
        for text in values:
            if self._cache_size > 0 and text in self._cache:
                self._cache.move_to_end(text)
                entries.append((self._cache[text], None))
                continue
            pending = self._pending.get(text)
            if pending is None:
                pending = _Pending(loop.create_future())
                self._pending[text] = pending
            if pending.batch is None:
                awaiting_batch = True
            entries.append((None, pending))
        if awaiting_batch:
            self._ensure_flush()

        vectors: list[tuple[float, ...]] = []
        batches: dict[int, _Batch] = {}
        for cached, pending in entries:
            if cached is not None:
                vectors.append(cached)
                continue
            assert pending is not None
            vector = await asyncio.shield(pending.future)
            vectors.append(vector)
            if pending.batch is not None:
                batches[id(pending.batch)] = pending.batch
        return EmbeddingResult(vectors=tuple(vectors), usage=_aggregate_usage(tuple(batches.values())))

    def _ensure_flush(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush())

    async def _flush(self) -> None:
        while True:
            waiting = any(pending.batch is None for pending in self._pending.values())
            if not waiting:
                return
            if self._coalesce_seconds > 0:
                await asyncio.sleep(self._coalesce_seconds)
            while True:
                texts = tuple(
                    text for text, pending in self._pending.items() if pending.batch is None
                )[: self._max_batch_size]
                if not texts:
                    break
                self._start_batch(texts)

    def _start_batch(self, texts: tuple[str, ...]) -> None:
        batch = _Batch(texts)
        for text in texts:
            pending = self._pending.get(text)
            if pending is not None:
                pending.batch = batch
        asyncio.create_task(self._run_batch(batch))

    async def _run_batch(self, batch: _Batch) -> None:
        try:
            result = await self._model.embed(batch.texts)
            vectors = tuple(result.vectors)
            if len(vectors) != len(batch.texts):
                raise ValueError("embedding vector count does not match the batch text count")
            batch.usage = result.usage
            for text, vector in zip(batch.texts, vectors, strict=True):
                self._store_cache(text, vector)
                pending = self._pending.get(text)
                if pending is not None and pending.batch is batch:
                    del self._pending[text]
                    if not pending.future.done():
                        pending.future.set_result(vector)
        except asyncio.CancelledError:
            self._fail_batch(batch, RuntimeError("embedding batch was cancelled"))
            raise
        except BaseException as error:  # noqa: BLE001 - propagate the provider failure to every waiter
            self._fail_batch(batch, error)

    def _fail_batch(self, batch: _Batch, error: BaseException) -> None:
        for text in batch.texts:
            pending = self._pending.get(text)
            if pending is not None and pending.batch is batch:
                del self._pending[text]
                if not pending.future.done():
                    pending.future.set_exception(error)

    def _store_cache(self, text: str, vector: tuple[float, ...]) -> None:
        if self._cache_size <= 0:
            return
        self._cache[text] = tuple(vector)
        self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _aggregate_usage(batches: Sequence[_Batch]) -> InferenceUsage:
    if not batches:
        return InferenceUsage(requests=0)
    requests = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    for batch in batches:
        if batch.usage is None:
            continue
        requests += batch.usage.requests
        if batch.usage.input_tokens is not None:
            input_tokens = (input_tokens or 0) + batch.usage.input_tokens
        if batch.usage.output_tokens is not None:
            output_tokens = (output_tokens or 0) + batch.usage.output_tokens
    return InferenceUsage(requests=requests, input_tokens=input_tokens, output_tokens=output_tokens)


__all__ = ["CoalescingEmbeddingModel"]