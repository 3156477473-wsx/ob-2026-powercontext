"""轻量文本向量化。

为了让评审无需外部模型或 API Key 即可复现，这里用「词项哈希 + 子线性 TF 权重」
构造确定性向量：

- 英文按单词切分，中文按 2-gram 切分（覆盖中文无空格的特点）
- 词频使用 1 + log(tf)，抑制高频词主导
- 哈希到固定维度，带符号散列降低碰撞偏置
- 最后 L2 归一化，使 l2_distance 与余弦相似度单调对应

同一输入永远得到同一向量。生产环境可替换为任意 embedding 服务，
只需保持输出维度与 EMBEDDING_DIM 一致。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import List

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def _tokens(text: str) -> List[str]:
    """中英混合分词：英文按单词，中文按字符 2-gram。"""
    text = text.lower()

    tokens: List[str] = _WORD_RE.findall(text)

    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
        for i in range(len(run) - 1):
            tokens.append(run[i : i + 2])

    return tokens


def embed(text: str, dim: int = 256) -> List[float]:
    """把文本映射为 dim 维单位向量。"""
    vec = [0.0] * dim
    counts = Counter(_tokens(text))
    if not counts:
        return vec

    for tok, tf in counts.items():
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
        # 子线性词频，降低长文本中高频词的权重
        weight = 1.0 + math.log(tf)
        vec[idx] += sign * weight

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def to_sql_vector(vec: List[float]) -> str:
    """转换为 seekdb 可解析的向量字面量。"""
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"