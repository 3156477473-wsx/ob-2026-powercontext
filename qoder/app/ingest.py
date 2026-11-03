"""文档解析与分块。"""

from __future__ import annotations

import io
import re
from typing import List

from pypdf import PdfReader


def extract_text(filename: str, data: bytes) -> str:
    """从 PDF / TXT / Markdown 中提取纯文本。"""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    # txt / md / 其他文本文件
    return data.decode("utf-8", errors="ignore")


def split_chunks(text: str, chunk_size: int = 150, overlap: int = 40) -> List[str]:
    """按段落优先、长度兜底的方式切块。

    先按标题/空行/段落切分，再合并到接近 chunk_size 的粒度，
    避免整段 400 字的长文本稀释关键词，提升检索召回精度。
    """
    text = text.strip()
    if not text:
        return []

    # 按标题与空行切成自然段
    raw_parts = re.split(r"\n\s*\n|(?=^#{1,6}\s)", text, flags=re.MULTILINE)

    chunks: List[str] = []
    buffer = ""

    for part in raw_parts:
        part = " ".join(part.split())
        if not part:
            continue

        # 单个自然段过长，按长度再切
        if len(part) > chunk_size:
            if buffer:
                chunks.append(buffer.strip())
                buffer = ""
            start = 0
            step = max(1, chunk_size - overlap)
            while start < len(part):
                piece = part[start : start + chunk_size].strip()
                if piece:
                    chunks.append(piece)
                start += step
            continue

        # 能塞进当前块就合并，否则另起一块
        if len(buffer) + len(part) + 1 <= chunk_size:
            buffer = f"{buffer} {part}".strip()
        else:
            if buffer:
                chunks.append(buffer.strip())
            buffer = part

    if buffer:
        chunks.append(buffer.strip())

    return [c for c in chunks if c]