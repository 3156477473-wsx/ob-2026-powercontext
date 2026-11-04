"""工程资料索引器：把规格、代码、测试拆成可检索单元写入 seekdb。

拆分粒度：
- 规格：按 "## SPEC-xxx" 分节
- 代码：按函数/方法（def）拆分，记录所属文件与符号名
- 测试：按 test_ 函数拆分，记录测试名
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

SPEC_HEAD_RE = re.compile(r"^##\s+(SPEC-\d+)", re.MULTILINE)
DEF_RE = re.compile(r"^(?P<indent>\s*)def\s+(?P<name>\w+)\s*\(", re.MULTILINE)


def split_specs(text: str) -> List[Dict]:
    """按 SPEC-xxx 章节拆分规格文档。"""
    parts = []
    matches = list(SPEC_HEAD_RE.finditer(text))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            parts.append({"symbol": m.group(1), "content": body})
    return parts


def split_code(path: Path) -> List[Dict]:
    """按 def 拆分代码文件，包含函数上方的注释与装饰器。"""
    text = path.read_text(encoding="utf-8")
    matches = list(DEF_RE.finditer(text))
    if not matches:
        return [{"symbol": path.stem, "content": text.strip()}]

    parts = []
    for i, m in enumerate(matches):
        # 向上包含紧邻的注释/装饰器
        start = m.start()
        lines_before = text[:start].splitlines()
        j = len(lines_before)
        while j > 0:
            prev = lines_before[j - 1].strip()
            if prev.startswith(("#", "@")) or prev == "":
                j -= 1
            else:
                break
        start = len("\n".join(lines_before[:j]))
        if j > 0:
            start += 1

        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            parts.append({"symbol": m.group("name"), "content": body})
    return parts


def collect(root: Path) -> List[Dict]:
    """收集 root 下所有规格、代码、测试。"""
    items: List[Dict] = []

    for spec_file in (root / "docs").glob("*.md"):
        text = spec_file.read_text(encoding="utf-8")
        for s in split_specs(text):
            items.append({
                "doc_type": "spec",
                "doc_path": str(spec_file.relative_to(root)).replace("\\", "/"),
                "symbol": s["symbol"],
                "content": s["content"],
            })

    for src in (root / "src").rglob("*.py"):
        for s in split_code(src):
            items.append({
                "doc_type": "code",
                "doc_path": str(src.relative_to(root)).replace("\\", "/"),
                "symbol": s["symbol"],
                "content": s["content"],
            })

    for tst in (root / "tests").rglob("*.py"):
        for s in split_code(tst):
            items.append({
                "doc_type": "test",
                "doc_path": str(tst.relative_to(root)).replace("\\", "/"),
                "symbol": s["symbol"],
                "content": s["content"],
            })

    return items