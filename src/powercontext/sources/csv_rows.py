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

"""Row-level CSV Sources that keep every original field value as evidence."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

CSV_ROW_SOURCE_NAME = "csv-row"
CSV_ROW_IDENTITY_PREFIX = "csv"


class CSVDocumentInput(BaseModel):
    """One complete offline CSV document split into primary-keyed rows."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One row of a CSV document, retained exactly as it was captured."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """A captured CSV row addressable through its stable row identity."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Build the delimiter-safe identity shared by a row Source and its citation."""

    document = _require_trimmed(document_id, "document_id")
    key_value = _require_non_blank(primary_key_value, "primary_key_value")
    identity = (
        f"{CSV_ROW_IDENTITY_PREFIX}:{quote(document, safe='')}:{quote(key_value, safe='')}"
    )
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(
            f"csv row identity must not exceed {MAX_SOURCE_ID_LENGTH} characters"
        )
    return identity


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse and fully validate one CSV document before returning any row."""

    document_id = _require_trimmed(value.document_id, "document_id")
    primary_key = _require_non_blank(value.primary_key, "primary_key")
    records = _read_records(_decode(value.content))
    if not records:
        raise ValueError("csv document must contain a header record")
    header = records[0]
    if not header:
        raise ValueError("csv header must not be empty")
    for column in header:
        if not column or not column.strip():
            raise ValueError("csv header fields must be non-empty and non-blank")
    if len(set(header)) != len(header):
        raise ValueError("csv header fields must be unique")
    if primary_key not in header:
        raise ValueError("primary_key must match a header column exactly")
    key_index = header.index(primary_key)

    rows: list[CSVRowInput] = []
    seen_keys: set[str] = set()
    for record in records[1:]:
        if not record:
            # Completely empty physical records carry no data and are ignored.
            continue
        if len(record) != len(header):
            raise ValueError("csv record width must match the header width")
        key_value = record[key_index]
        if not key_value or not key_value.strip():
            raise ValueError("csv primary key values must be non-empty and non-blank")
        if key_value in seen_keys:
            raise ValueError("csv primary key values must be unique within a document")
        seen_keys.add(key_value)
        csv_row_source_id(document_id, key_value)
        rows.append(
            CSVRowInput(
                document_id=document_id,
                primary_key=primary_key,
                primary_key_value=key_value,
                columns=tuple(header),
                values=tuple(record),
            )
        )
    return tuple(rows)


class CSVRowSourceAdapter:
    """Resolve and read row-level CSV Sources without transforming field values."""

    input_class = CSVRowInput
    name = CSV_ROW_SOURCE_NAME
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class CSVRowTextEvidenceProjection:
    """Expose one row as standard text evidence while preserving its columns."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


def _decode(content: object) -> str:
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise ValueError("csv content must be supplied as bytes")
    try:
        return bytes(content).decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("csv content must be valid utf-8") from error


def _read_records(text: str) -> list[list[str]]:
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        return [list(record) for record in reader]
    except csv.Error as error:
        raise ValueError(f"malformed csv document: {error}") from error


def _require_non_blank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _require_trimmed(value: object, field: str) -> str:
    text = _require_non_blank(value, field)
    if text != text.strip():
        raise ValueError(f"{field} must not contain leading or trailing whitespace")
    return text


CSV_ROW_SOURCE_ADAPTER = CSVRowSourceAdapter()
CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(
    CSV_ROW_SOURCE_ADAPTER,
    projections=(CSVRowTextEvidenceProjection(),),
)

__all__ = [
    "CSV_ROW_SOURCE_ADAPTER",
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "CSVRowSourceAdapter",
    "CSVRowTextEvidenceProjection",
    "csv_row_source_id",
    "parse_csv_document",
]