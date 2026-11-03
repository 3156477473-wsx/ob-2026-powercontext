"""FastAPI 入口：上传文档、检索、统计。"""

from __future__ import annotations

from typing import Optional

import pymysql
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import store
from .config import settings
from .ingest import extract_text, split_chunks

app = FastAPI(title="文献笔记智能检索助手", version="1.0.0")


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    doc: Optional[str] = None
    mode: str = "hybrid"


@app.on_event("startup")
def _startup() -> None:
    store.init_schema()


@app.get("/api/health")
def health() -> dict:
    """连通性检查：同时验证 seekdb 是否可用。"""
    try:
        s = store.stats()
        return {"status": "ok", "seekdb": "connected", **s}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"seekdb 不可用: {exc}") from exc


@app.get("/api/stats")
def get_stats() -> dict:
    try:
        return store.stats()
    except pymysql.err.OperationalError as exc:
        raise HTTPException(status_code=503, detail=f"seekdb 不可用，请检查 seekdb 是否启动：{exc}") from exc


@app.get("/api/docs")
def list_docs() -> dict:
    """返回已入库的文档名列表（去重）。"""
    try:
        with store.connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT doc_name FROM {store.TABLE} ORDER BY doc_name")
            rows = cur.fetchall()
        return {"docs": [r["doc_name"] for r in rows]}
    except pymysql.err.OperationalError as exc:
        raise HTTPException(status_code=503, detail=f"seekdb 不可用，请检查 seekdb 是否启动：{exc}") from exc


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    """上传文档，解析、分块后写入 seekdb。"""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")

    text = extract_text(file.filename or "unknown.txt", raw)
    chunks = split_chunks(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="未能从文件中提取到文本")

    try:
        count = store.insert_chunks(file.filename or "unknown.txt", chunks)
    except pymysql.err.OperationalError as exc:
        raise HTTPException(status_code=503, detail=f"seekdb 不可用，请检查 seekdb 是否启动：{exc}") from exc
    return {"doc": file.filename, "chunks": count, "chars": len(text)}


@app.post("/api/search")
def search(req: SearchRequest) -> dict:
    """混合检索：向量 + 全文 + 文档过滤。"""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="查询不能为空")

    try:
        results = store.search(
            req.query, top_k=req.top_k, doc_filter=req.doc, mode=req.mode
        )
    except pymysql.err.OperationalError as exc:
        raise HTTPException(status_code=503, detail=f"seekdb 不可用，请检查 seekdb 是否启动：{exc}") from exc
    return {
        "query": req.query,
        "mode": req.mode,
        "count": len(results),
        "results": [
            {
                "doc": r["doc_name"],
                "chunk_no": r["chunk_no"],
                "score": round(float(r["score"]), 4),
                "content": r["content"],
            }
            for r in results
        ],
    }


@app.post("/api/reset")
def reset() -> dict:
    """清空索引，便于评审重复验证。"""
    try:
        store.clear_all()
    except pymysql.err.OperationalError as exc:
        raise HTTPException(status_code=503, detail=f"seekdb 不可用，请检查 seekdb 是否启动：{exc}") from exc
    return {"status": "cleared"}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()