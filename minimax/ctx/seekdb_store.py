"""seekdb 索引层：存储工程资料（规格、代码、测试），并提供检索。

表结构：
  eng_docs(id, doc_type, doc_path, symbol, content, vector, FULLTEXT)

doc_type: spec | code | test
检索同时使用向量相似度与全文匹配，结果用于构造任务上下文。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Dict, List, Optional

import pymysql

TABLE = "eng_docs"
DIM = 256

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def _tokens(text: str) -> List[str]:
    text = text.lower()
    tokens = _WORD_RE.findall(text)
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
        for i in range(len(run) - 1):
            tokens.append(run[i : i + 2])
    return tokens


def embed(text: str, dim: int = DIM) -> List[float]:
    """确定性哈希向量：字符 n-gram + 子线性 TF，最后 L2 归一化。"""
    vec = [0.0] * dim
    counts = Counter(_tokens(text))
    if not counts:
        return vec
    for tok, tf in counts.items():
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
        vec[idx] += sign * (1.0 + math.log(tf))
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def to_sql_vector(vec: List[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


class SeekdbStore:
    """seekdb 访问封装。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 2881,
                 user: str = "root", password: str = "", database: str = "test") -> None:
        self.cfg = dict(host=host, port=port, user=user,
                        password=password, database=database, charset="utf8mb4")

    def _conn(self):
        return pymysql.connect(autocommit=True, cursorclass=pymysql.cursors.DictCursor, **self.cfg)

    def init_schema(self) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    doc_type VARCHAR(32) NOT NULL,
                    doc_path VARCHAR(255) NOT NULL,
                    symbol VARCHAR(128) NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    vector VECTOR({DIM}) NOT NULL,
                    FULLTEXT INDEX ft_content (content) WITH PARSER ik
                ) ENGINE=InnoDB
                """
            )

    def clear(self) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {TABLE}")

    def upsert_many(self, items: List[Dict]) -> int:
        """items: [{doc_type, doc_path, symbol, content}]"""
        if not items:
            return 0
        rows = [
            (it["doc_type"], it["doc_path"], it.get("symbol", ""),
             it["content"], to_sql_vector(embed(it["content"])))
            for it in items
        ]
        with self._conn() as conn, conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {TABLE} (doc_type, doc_path, symbol, content, vector) "
                f"VALUES (%s,%s,%s,%s,%s)",
                rows,
            )
        return len(rows)

    def search(self, query: str, top_k: int = 8,
               doc_type: Optional[str] = None) -> List[Dict]:
        """混合检索：全文召回 + 向量重排。"""
        qvec = to_sql_vector(embed(query))

        where = ["MATCH(content) AGAINST(%s)"]
        params: List = [qvec, query, query]
        if doc_type:
            where.append("doc_type = %s")
            params.append(doc_type)

        sql = (
            f"SELECT id, doc_type, doc_path, symbol, content, "
            f"(1 - l2_distance(vector, %s)) AS vec_score, "
            f"MATCH(content) AGAINST(%s) AS kw_score "
            f"FROM {TABLE} WHERE {' AND '.join(where)} LIMIT %s"
        )
        params.append(max(top_k * 4, 12))

        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())

        if not rows:
            return []

        kw_max = max(float(r["kw_score"] or 0) for r in rows) or 1.0
        vs = [float(r["vec_score"] or 0) for r in rows]
        vmin, vmax = min(vs), max(vs)
        span = (vmax - vmin) or 1.0

        for r in rows:
            kw = float(r["kw_score"] or 0) / kw_max
            vec = (float(r["vec_score"] or 0) - vmin) / span
            r["score"] = 0.6 * kw + 0.4 * vec

        rows.sort(key=lambda r: r["score"], reverse=True)
        for r in rows:
            r.pop("vec_score", None)
            r.pop("kw_score", None)
        return rows[:top_k]

    def stats(self) -> Dict[str, int]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT doc_type, COUNT(*) AS n FROM {TABLE} GROUP BY doc_type")
            return {r["doc_type"]: int(r["n"]) for r in cur.fetchall()}