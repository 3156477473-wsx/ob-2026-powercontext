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


_PAGE_TYPE_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "balance": (re.compile(r"consolidated balance sheets?"), re.compile(r"\bbalance sheets?\b")),
    "income": (
        re.compile(r"consolidated statements? of (income|operations|earnings)"),
        re.compile(r"\bstatements? of (income|operations|earnings)\b"),
        re.compile(r"summary of financial performance"),
        re.compile(r"financial highlights"),
    ),
    "cashflow": (re.compile(r"statements? of cash flows"),),
    "segment": (
        re.compile(r"by business segment"),
        re.compile(r"segment data"),
        re.compile(r"geographic operations"),
        re.compile(r"segment information"),
    ),
    "legal": (re.compile(r"legal proceedings"),),
}

_INTENT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "balance": (
        re.compile(r"quick ratio"),
        re.compile(r"current ratio"),
        re.compile(r"inventory"),
        re.compile(r"balance sheet"),
        re.compile(r"liabilit"),
        re.compile(r"total assets"),
        re.compile(r"return on assets"),
        re.compile(r"\broa\b"),
    ),
    "income": (
        re.compile(r"gross margin"),
        re.compile(r"operating margin"),
        re.compile(r"net margin"),
        re.compile(r"\bmargin\b"),
        re.compile(r"revenue"),
        re.compile(r"net sales"),
        re.compile(r"\bsales\b"),
        re.compile(r"earnings"),
        re.compile(r"income statement"),
        re.compile(r"operating income"),
        re.compile(r"\beps\b"),
        re.compile(r"profit"),
        re.compile(r"return on assets"),
        re.compile(r"\broa\b"),
        re.compile(r"ebitda"),
        re.compile(r"tax"),
        re.compile(r"provision for income"),
    ),
    "cashflow": (
        re.compile(r"ebitda"),
        re.compile(r"cash flow"),
        re.compile(r"capex"),
        re.compile(r"capital expenditure"),
        re.compile(r"free cash"),
        re.compile(r"capital[- ]intensive"),
        re.compile(r"depreciation"),
        re.compile(r"amortization"),
        re.compile(r"dividend"),
        re.compile(r"repurchase"),
    ),
    "segment": (
        re.compile(r"geograph"),
        re.compile(r"\bregion"),
        re.compile(r"segment"),
        re.compile(r"business unit"),
        re.compile(r"acquisition"),
        re.compile(r"m&a"),
        re.compile(r"merger"),
        re.compile(r"divestiture"),
        re.compile(r"product categor"),
        re.compile(r"service categor"),
    ),
    "legal": (
        re.compile(r"legal"),
        re.compile(r"litigation"),
        re.compile(r"lawsuit"),
        re.compile(r"battle"),
        re.compile(r"proceeding"),
        re.compile(r"claim"),
        re.compile(r"investigation"),
        re.compile(r"regulatory"),
    ),
}

_TYPE_QUERIES: dict[str, tuple[str, ...]] = {
    "balance": ("consolidated balance sheets",),
    "income": (
        "summary of financial performance",
        "consolidated statements of income",
        "consolidated statements of operations",
        "consolidated statement of earnings",
    ),
    "cashflow": ("consolidated statements of cash flows",),
    "segment": ("business segment", "geographic operations"),
    "legal": ("legal proceedings",),
}

_STRUCTURE_WEIGHT = 0.8
_SIBLING_WEIGHT = 0.3
_SCORE_SCALE = 5.0
_STATEMENT_TYPES = frozenset({"balance", "income", "cashflow"})


def _wanted_page_types(question: str) -> tuple[str, ...]:
    lowered = question.casefold()
    wanted = [
        name
        for name, patterns in _INTENT_PATTERNS.items()
        if any(pattern.search(lowered) for pattern in patterns)
    ]
    return tuple(wanted)


def _page_types(text: str) -> frozenset[str]:
    head = re.sub(r"[^a-z0-9]+", " ", text[:600].casefold())
    found = {name for name, patterns in _PAGE_TYPE_PATTERNS.items() if any(p.search(head) for p in patterns)}
    if not found:
        body = text.casefold()
        if any(token in body for token in ("legal proceeding", "litigation", "claims and litigation")):
            found.add("legal")
    return frozenset(found)


def _name_overlap(terms: tuple[str, ...], name: str) -> int:
    """Count question terms that name this document, tolerating ticker-style short forms."""

    words = _tokenize(name)
    hits = 0
    for term in terms:
        for word in words:
            if term == word or (len(term) >= 3 and word.startswith(term[:3])) or (
                len(term) >= 4 and term in word
            ):
                hits += 1
                break
    return hits


def _target_document(
    documents: list[str],
    rows: list[tuple[float, float, int, int]],
    terms: tuple[str, ...],
) -> str:
    """Pick the document a question is most likely about when the scope holds several."""

    stats: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    for value, coverage, _rank, index in rows:
        name = documents[index]
        counts[name] = counts.get(name, 0) + 1
        entry = stats.setdefault(name, [0.0, 0.0, 0.0])
        entry[0] += value
        entry[1] = max(entry[1], value)
        entry[2] = max(entry[2], coverage)
    candidates = [name for name in stats if counts[name] >= 3]
    if not candidates:
        return ""
    return max(
        candidates,
        key=lambda name: (
            _name_overlap(terms, name),
            stats[name][2],
            stats[name][1],
            stats[name][0],
        ),
    )


def _question_terms(question: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN.findall(question.casefold()):
        if token in _STOP_WORDS or token in seen or len(token) < 2:
            continue
        seen.add(token)
        terms.append(token)
    return tuple(terms)


def _search_query_plan(question: str, wanted: tuple[str, ...]) -> tuple[str, ...]:
    terms = _question_terms(question)
    queries: list[str] = []
    if terms:
        queries.append(" ".join(terms))
    for name in wanted:
        queries.extend(_TYPE_QUERIES.get(name, ()))
    queries.extend(sorted(terms, key=len, reverse=True)[:3])
    queries.append("total")
    return tuple(dict.fromkeys(query for query in queries if query.strip()))


def _bm25_scores(documents: list[list[str]], query_terms: list[str]) -> list[float]:
    total = len(documents)
    lengths = [len(document) for document in documents]
    average = sum(lengths) / max(1, total)
    document_frequency: dict[str, int] = {}
    counters: list[dict[str, int]] = []
    for document in documents:
        counter: dict[str, int] = {}
        for token in document:
            counter[token] = counter.get(token, 0) + 1
        counters.append(counter)
        for token in counter:
            document_frequency[token] = document_frequency.get(token, 0) + 1
    scores: list[float] = []
    for counter, length in zip(counters, lengths):
        score = 0.0
        for term in query_terms:
            frequency = counter.get(term, 0)
            if not frequency:
                continue
            frequency_in_documents = document_frequency.get(term, 0)
            inverse = math.log(1.0 + (total - frequency_in_documents + 0.5) / (frequency_in_documents + 0.5))
            score += inverse * frequency * 2.2 / (frequency + 1.2 * (1 - 0.75 + 0.75 * length / max(1.0, average)))
        scores.append(score)
    return scores


async def search_pdf_pages(memory: object, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Return up to ``limit`` distinct evidence-page citations from the scoped Memory."""

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime import SearchMemoryRequest

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")

    terms = _question_terms(question)
    wanted = _wanted_page_types(question)
    depth = max(limit * 25, 500)
    hits: dict[str, object] = {}
    best_rank: dict[str, int] = {}
    for query in _search_query_plan(question, wanted):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=depth))
        for rank, hit in enumerate(page.hits):
            previous = best_rank.get(hit.entry_id)
            if previous is not None and previous <= rank:
                continue
            hits[hit.entry_id] = hit
            best_rank[hit.entry_id] = rank

    if not hits:
        return ()

    entries = list(hits.values())
    texts = [str(hit.text) for hit in entries]
    lowered = [text.casefold() for text in texts]
    tokens = [_tokenize(text) for text in texts]
    scores = _bm25_scores(tokens, list(terms))
    types = [_page_types(text) for text in texts]
    documents = [text.split("\n", 1)[0] for text in texts]
    bigrams = tuple(zip(terms, terms[1:]))

    rows: list[tuple[float, float, int, int]] = []
    for index, (score, text, page_types) in enumerate(zip(scores, lowered, types)):
        normalised = score / (score + _SCORE_SCALE) if score else 0.0
        coverage = sum(1 for term in terms if term in text) / max(1, len(terms))
        structure = len(set(wanted) & page_types) / max(1, len(wanted)) if wanted else 0.0
        sibling = 1.0 if wanted and page_types & _STATEMENT_TYPES else 0.0
        phrase = sum(1 for left, right in bigrams if f"{left} {right}" in text)
        value = (
            normalised
            + _STRUCTURE_WEIGHT * structure
            + _SIBLING_WEIGHT * sibling
            + 0.1 * coverage
            + 0.02 * phrase
        )
        rows.append((value, coverage, best_rank[entries[index].entry_id], index))

    target = _target_document(documents, rows, terms)
    ranked = [
        (0 if not target or documents[index] == target else 1, value, rank, index)
        for value, _coverage, rank, index in rows
    ]
    ranked.sort(key=lambda item: (item[0], -item[1], item[2]))

    chosen = [index for _order, _value, _rank, index in ranked[:limit]]
    return tuple(
        MemoryCitation(
            memory_ref=entries[index].memory_ref,
            entry_id=entries[index].entry_id,
            entry_version_id=entries[index].entry_version_id,
        )
        for index in chosen
    )


def _tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.casefold()) if token not in _STOP_WORDS]


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