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

"""Parse every physical PDF page into a Source and retrieve evidence pages."""

from __future__ import annotations

import hashlib
import math
import io
import re
from typing import TYPE_CHECKING
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    SourceDefinition,
    TextEvidence,
)
from powercontext.sources.models import Source, SourceMaterialization

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import MemoryCitation

PDF_PAGE_SOURCE_NAME = "pdf-page"
PDF_PAGE_IDENTITY_PREFIX = "pdf"

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "for", "of", "to", "in", "on", "at", "by", "from",
        "with", "as", "is", "are", "was", "were", "be", "been", "being", "what", "which",
        "who", "how", "why", "when", "where", "do", "does", "did", "can", "could", "should",
        "would", "i", "we", "you", "it", "its", "our", "your", "this", "that", "these",
        "those", "please", "s", "company", "fiscal", "year", "fy",
    }
)


class PDFDocumentInput(BaseModel):
    """One complete original PDF and the identity of the document it belongs to."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical page of a PDF document, numbered from one."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """A captured physical PDF page addressable together with its document revision."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Build the stable identity of one page inside one exact document revision."""

    document = _require_non_blank(document_id, "document_id")
    digest = _require_sha256(document_sha256)
    if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number < 1:
        raise ValueError("page_number must be a positive integer")
    identity = f"{PDF_PAGE_IDENTITY_PREFIX}:{quote(document, safe='')}:{digest}:{page_number}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"pdf page identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return identity


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of one PDF document, or fail without partial output."""

    from pypdf import PdfReader

    document_id = _require_non_blank(value.document_id, "document_id")
    content = value.content
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise ValueError("pdf content must be supplied as bytes")
    raw = bytes(content)
    if not raw:
        raise ValueError("pdf content must not be empty")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted:
            # Empty user passwords are legitimate: no password is required to read them.
            if not reader.decrypt(""):
                raise ValueError("pdf document requires a user password")
        pages = list(reader.pages)
    except ValueError:
        raise
    except Exception as error:  # pypdf raises many parser-specific error types
        raise ValueError(f"pdf document cannot be parsed: {error}") from error
    if not pages:
        raise ValueError("pdf document must contain at least one page")
    result: list[PDFPageInput] = []
    for index, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as error:
            raise ValueError(f"pdf page {index} cannot be extracted: {error}") from error
        result.append(
            PDFPageInput(
                document_id=document_id,
                document_sha256=digest,
                page_number=index,
                text=text.strip(),
            )
        )
    return tuple(result)


class PDFPageSourceAdapter:
    """Resolve and read captured PDF pages without rewriting their extracted text."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose one page as standard text evidence prefixed by its document id."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


async def search_pdf_pages(memory: object, question: str, limit: int = 20) -> tuple[MemoryCitation, ...]:
    """Return up to ``limit`` distinct evidence-page citations from the scoped Memory."""

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime import GetMemoryEntryRequest, SearchMemoryRequest

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")

    terms = _question_terms(question)
    candidates: dict[tuple[str, int], dict[str, object]] = {}
    order: dict[tuple[str, int], int] = {}
    for _weight, query in _search_queries(question):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=max(limit * 3, 60)))
        for rank, hit in enumerate(page.hits):
            citation = MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            for reference in entry.sources:
                location = _page_location(reference.source_id)
                if location is None or location in candidates:
                    continue
                candidates[location] = {"citation": citation, "text": entry.text}
                order[location] = rank

    if not candidates and not terms:
        return ()
    lowered = {location: str(item["text"]).casefold() for location, item in candidates.items()}
    total = max(1, len(lowered))
    weights: dict[str, float] = {}
    for term in terms:
        frequency = sum(1 for text in lowered.values() if term in text)
        weights[term] = 1.0 + math.log(1.0 + total / (1.0 + frequency))
    bigrams = tuple(zip(terms, terms[1:]))

    scored: list[tuple[float, int, tuple[str, int]]] = []
    for location, text in lowered.items():
        score = 0.0
        matched = 0
        for term in terms:
            if term in text:
                score += weights[term]
                matched += 1
        if matched == 0:
            continue
        score += 2.0 * sum(1 for left, right in bigrams if f"{left} {right}" in text)
        score += 1.5 * (matched / max(1, len(terms)))
        scored.append((score, order.get(location, 10_000), location))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(candidates[location]["citation"] for _score, _rank, location in scored[:limit])


def _question_terms(question: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN.findall(question.casefold()):
        if token in _STOP_WORDS or token in seen or len(token) < 2:
            continue
        seen.add(token)
        terms.append(token)
    return tuple(terms)


def _search_queries(question: str) -> tuple[tuple[float, str], ...]:
    terms = _question_terms(question)
    if not terms:
        return ((1.0, question),)
    queries: list[tuple[float, str]] = [(1.0, " ".join(terms))]
    for index in range(len(terms) - 1):
        queries.append((0.7, f"{terms[index]} {terms[index + 1]}"))
    # Rare/long terms are the most selective single-term probes.
    singles = sorted(terms, key=len, reverse=True)[:6]
    for term in singles:
        queries.append((0.5, term))
    return tuple(queries)


def _page_location(source_id: str) -> tuple[str, int] | None:
    prefix, _, rest = source_id.partition(":")
    if prefix != PDF_PAGE_IDENTITY_PREFIX or ":" not in rest:
        return None
    document, _, page = rest.rpartition(":")
    if not document or not page.isdigit():
        return None
    from urllib.parse import unquote

    return unquote(document), int(page)


def _require_sha256(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("document_sha256 must be a lowercase sha-256 hex digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError("document_sha256 must be a lowercase sha-256 hex digest")
    return value


def _require_non_blank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


PDF_PAGE_SOURCE_ADAPTER = PDFPageSourceAdapter()
PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = AdapterSourceDefinition(
    PDF_PAGE_SOURCE_ADAPTER,
    projections=(PDFPageTextEvidenceProjection(),),
)

__all__ = [
    "PDF_PAGE_SOURCE_ADAPTER",
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "PDFPageSourceAdapter",
    "PDFPageTextEvidenceProjection",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]