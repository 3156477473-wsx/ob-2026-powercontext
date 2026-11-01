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

"""Cross-encoder reranking through a caller-supplied HTTP scoring endpoint."""

from __future__ import annotations

import math
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

_DEFAULT_POLICY_ID = "http-cross-encoder-v1"


class HTTPMemoryReranker:
    """Score coarse candidates over HTTP in bounded batches and order them globally."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = _DEFAULT_POLICY_ID,
    ) -> None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("reranker endpoint must be a non-empty string")
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise ValueError("policy_id must be a non-empty string")
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Score every candidate exactly once and return the globally best ranks."""

        candidate_count = len(candidates)
        if candidate_count < 1:
            raise ValueError("rerank requires at least one candidate")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= candidate_count:
            raise ValueError("limit must be between 1 and the candidate count")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")

        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, candidate_count, self._batch_size):
            stop = min(start + self._batch_size, candidate_count)
            batch = tuple((rank, candidates[rank - 1]) for rank in range(start + 1, stop + 1))
            body = {
                "query": query,
                "candidates": [
                    {"rank": rank, "text": candidate.text}
                    for rank, candidate in batch
                ],
            }
            response = await self._client.post(self._endpoint, json=body)
            requests += 1
            response.raise_for_status()
            payload: Any = response.json()
            scores.update(_validated_scores(payload, frozenset(rank for rank, _ in batch)))

        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        selected_ranks = tuple(rank for rank, _score in ordered[:limit])
        return MemoryRerankDecision(
            selected_ranks=selected_ranks,
            usage=InferenceUsage(requests=requests),
            discarded_rank_count=candidate_count - len(selected_ranks),
        )


def _validated_scores(payload: object, expected_ranks: frozenset[int]) -> dict[int, float]:
    if not isinstance(payload, dict) or set(payload) != {"scores"}:
        raise ValueError("rerank response must contain exactly one 'scores' field")
    raw_scores = payload["scores"]
    if not isinstance(raw_scores, list):
        raise ValueError("rerank response 'scores' must be a list")
    scored: dict[int, float] = {}
    for entry in raw_scores:
        if not isinstance(entry, dict) or set(entry) != {"rank", "score"}:
            raise ValueError("every rerank score must contain exactly 'rank' and 'score'")
        rank = entry["rank"]
        score = entry["score"]
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ValueError("rerank score rank must be an integer")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise ValueError("rerank score must be a number")
        value = float(score)
        if not math.isfinite(value):
            raise ValueError("rerank score must be finite")
        if rank in scored:
            raise ValueError("rerank response must not repeat a rank")
        scored[rank] = value
    if frozenset(scored) != expected_ranks:
        raise ValueError("rerank response must cover exactly the ranks of its batch")
    return scored


__all__ = ["HTTPMemoryReranker"]