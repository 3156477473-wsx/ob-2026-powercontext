"""seekdb 访问层：建表、写入、混合检索。

seekdb 兼容 MySQL 协议，并支持向量类型、全文索引与结构化条件组合。
本模块承担项目的核心检索能力，是整个项目的数据底座。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pymysql

from .config import settings
from .embedding import embed, to_sql_vector

TABLE = "doc_chunks"


def connect() -> pymysql.connections.Connection:
    """建立到 seekdb 的连接。"""
    return pymysql.connect(
        host=settings.seekdb_host,
        port=settings.seekdb_port,
        user=settings.seekdb_user,
        password=settings.seekdb_password,
        database=settings.seekdb_database,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def init_schema() -> None:
    """创建数据表与索引，可重复执行。"""
    dim = settings.embedding_dim
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INT PRIMARY KEY AUTO_INCREMENT,
                doc_name VARCHAR(255) NOT NULL,
                chunk_no INT NOT NULL,
                content TEXT NOT NULL,
                vector VECTOR({dim}) NOT NULL,
                FULLTEXT INDEX ft_content (content) WITH PARSER ik
            ) ENGINE=InnoDB
            """
        )


def clear_all() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {TABLE}")


def insert_chunks(doc_name: str, chunks: List[str]) -> int:
    """批量写入分块及其向量，返回写入条数。"""
    rows = []
    for i, chunk in enumerate(chunks):
        vec = to_sql_vector(embed(chunk, settings.embedding_dim))
        rows.append((doc_name, i, chunk, vec))

    if not rows:
        return 0

    sql = f"INSERT INTO {TABLE} (doc_name, chunk_no, content, vector) VALUES (%s, %s, %s, %s)"
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def _cosine_score(sql_expr: str, query_vec: str) -> str:
    """构造余弦相似度表达式：1 - 距离。"""
    return f"(1 - {sql_expr})"


def search(
    query: str,
    top_k: int = 5,
    doc_filter: Optional[str] = None,
    mode: str = "hybrid",
) -> List[Dict[str, Any]]:
    """混合检索。

    mode:
      - vector  : 仅向量相似度
      - keyword : 仅全文匹配
      - hybrid  : 向量 + 全文 + 结构化过滤（默认）
    """
    qvec = to_sql_vector(embed(query, settings.embedding_dim))

    # 混合模式采用「全文召回 + 向量精排」的两阶段策略：
    # 第一阶段用 seekdb 全文索引保证有命中的块不会漏，
    # 第二阶段在这些候选块上计算向量相似度重排，兼顾精确匹配与语义相关。
    if mode == "hybrid":
        return _hybrid_search(query, qvec, top_k, doc_filter)

    where: List[str] = []
    params: List[Any] = []

    if mode == "keyword":
        select_score = "MATCH(content) AGAINST(%s) AS score"
        params.append(query)

        where.append("MATCH(content) AGAINST(%s)")
        params.append(query)
    else:
        select_score = "(1 - l2_distance(vector, %s)) AS score"
        params.append(qvec)

    if doc_filter:
        where.append("doc_name = %s")
        params.append(doc_filter)

    sql = f"SELECT id, doc_name, chunk_no, content, {select_score} FROM {TABLE}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY score DESC LIMIT %s"
    params.append(top_k)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def _hybrid_search(
    query: str,
    qvec: str,
    top_k: int,
    doc_filter: Optional[str],
) -> List[Dict[str, Any]]:
    """两阶段混合检索：全文召回候选，向量相似度重排。

    算法：
      1. 用 MATCH...AGAINST 取回候选块（最多候选池 4×top_k）
      2. 对每个候选计算 (1 - l2_distance)，得到向量相似度
      3. 最终得分 = 0.5 × 归一化全文分 + 0.5 × 归一化向量分
      4. 按最终得分排序取 top_k
    """
    pool = max(top_k * 4, 10)

    # 参数严格按 SQL 中占位符出现顺序追加：
    # SELECT 的 l2_distance → SELECT 的 MATCH → WHERE 的 MATCH → 文档过滤 → LIMIT
    where = ["MATCH(content) AGAINST(%s)"]
    params: List[Any] = [qvec, query, query]

    if doc_filter:
        where.append("doc_name = %s")
        params.append(doc_filter)

    sql = (
        f"SELECT id, doc_name, chunk_no, content, "
        f"(1 - l2_distance(vector, %s)) AS vec_score, "
        f"MATCH(content) AGAINST(%s) AS kw_score "
        f"FROM {TABLE} WHERE {' AND '.join(where)} LIMIT %s"
    )
    params.append(pool)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())

    if not rows:
        return []

    # 归一化：全文分按最大值缩放；向量分映射到 [0,1] 并保留区分度
    kw_max = max(float(r["kw_score"] or 0.0) for r in rows) or 1.0
    vec_values = [float(r["vec_score"] or 0.0) for r in rows]
    vec_min, vec_max = min(vec_values), max(vec_values)
    vec_span = (vec_max - vec_min) or 1.0

    for r in rows:
        kw_norm = float(r["kw_score"] or 0.0) / kw_max
        vec_norm = (float(r["vec_score"] or 0.0) - vec_min) / vec_span
        # 全文权重略高，保证关键词精确命中优先；向量负责语义补位
        r["score"] = 0.6 * kw_norm + 0.4 * vec_norm
        # 保留原始分，便于前端展示与调试
        r["kw"] = round(float(r["kw_score"] or 0.0), 4)

    rows.sort(key=lambda r: r["score"], reverse=True)
    for r in rows:
        r.pop("vec_score", None)
        r.pop("kw_score", None)

    return rows[:top_k]


def _keyword_search(
    query: str, top_k: int, doc_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """纯全文检索，作为混合模式的兜底召回。"""
    where = ["MATCH(content) AGAINST(%s)"]
    params: List[Any] = [query, query]

    if doc_filter:
        where.append("doc_name = %s")
        params.append(doc_filter)

    sql = (
        f"SELECT id, doc_name, chunk_no, content, "
        f"MATCH(content) AGAINST(%s) AS score FROM {TABLE} "
        f"WHERE {' AND '.join(where)} ORDER BY score DESC LIMIT %s"
    )
    params.append(top_k)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def stats() -> Dict[str, int]:
    """返回文档数与分块数，用于首页展示。"""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS chunks, COUNT(DISTINCT doc_name) AS docs FROM {TABLE}")
        row = cur.fetchone()
    return {"docs": int(row["docs"] or 0), "chunks": int(row["chunks"] or 0)}