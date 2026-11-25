"""资料入库流水线：解析 → 分块 → 向量化 → 写入 Qdrant。

所有步骤都在后台任务中执行；失败会把文档置为 failed 并清理半成品，
用户可在资料详情页重试。重试是幂等的：先清旧 chunks/vectors，再重建。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List

from .. import db
from ..config import get_settings
from ..rag.chunking import chunk_blocks
from ..rag.embeddings import EmbeddingError, get_embedding_client
from ..rag.parsers import ParseError, detect_kind, parse_document
from ..rag.types import ParsedDocument, evidence_ref
from ..rag.vector_store import VectorPoint, get_vector_store
from ..rag.web import WebFetchError, fetch_document

logger = logging.getLogger(__name__)


class IngestError(Exception):
    pass


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, (ParseError, WebFetchError, EmbeddingError, IngestError)):
        return str(exc)[:240]
    if isinstance(exc, FileNotFoundError):
        return "源文件不存在，请删除后重新上传"
    if "timeout" in str(exc).lower():
        return "资料处理超时，请稍后重试"
    return "资料处理失败，请稍后重试或换一份资料"


async def _load_parsed(doc: Dict[str, Any]) -> ParsedDocument:
    settings = get_settings()
    kind = doc.get("kind") or "file"
    meta = doc.get("meta") or {}
    if kind == "web":
        url = str(doc.get("source_url") or "").strip()
        if not url:
            raise IngestError("网页链接为空")
        parsed = await fetch_document(
            url,
            max_bytes=settings.kb_max_url_bytes,
            max_pages=settings.kb_max_pages,
        )
        if parsed.title and (not doc.get("title") or str(doc.get("title")).startswith("http")):
            db.update_kb_document(doc["id"], title=parsed.title[:200])
        return parsed

    if kind == "text":
        text = str(doc.get("raw_text") or "").strip()
        if not text:
            raise IngestError("文本内容为空")
        return await asyncio.to_thread(
            parse_document, "text", text.encode("utf-8"), filename=doc.get("title") or "文本资料"
        )

    stored = str(doc.get("stored_path") or "").strip()
    if not stored:
        raise IngestError("源文件路径缺失")
    path = Path(stored)
    if not path.exists():
        raise FileNotFoundError(stored)
    data = await asyncio.to_thread(path.read_bytes)
    parser_kind = str(meta.get("kind") or "").strip()
    if not parser_kind:
        try:
            parser_kind = detect_kind(doc.get("filename") or path.name, doc.get("mime") or "")
        except ParseError as exc:
            raise IngestError(str(exc)) from exc
    return await asyncio.to_thread(
        parse_document,
        parser_kind,
        data,
        filename=doc.get("filename") or path.name,
        mime=doc.get("mime") or "",
        max_pages=settings.kb_max_pages,
    )


async def ingest_document(doc_id: str) -> None:
    """后台入口：任何异常都要落 failed，并尽量清理半成品。"""
    doc = db.get_kb_document(doc_id)
    if not doc:
        return
    settings = get_settings()
    kb_id = doc["kb_id"]
    store = get_vector_store(settings)

    try:
        db.update_kb_document(doc_id, status="parsing", progress=12, error=None)
        parsed = await _load_parsed(doc)
        text = parsed.text.strip()
        if not text:
            raise IngestError("没有提取到可用文字")
        if len(text) > settings.kb_max_text_chars:
            raise IngestError(
                f"资料正文超过 {settings.kb_max_text_chars} 字，请拆分后再上传"
            )
        fresh = db.get_kb_document(doc_id) or doc
        # 文件优先使用解析出的标题（PDF 元数据 / DOCX 标题 / PPT 标题）；
        # 用户手动命名的文本/网页保留用户标题。
        if fresh.get("kind") == "text":
            title = (fresh.get("title") or parsed.title or "未命名资料")[:200]
        else:
            title = (parsed.title or fresh.get("title") or "未命名资料")[:200]
        db.update_kb_document(
            doc_id,
            title=title,
            status="chunking",
            progress=40,
            raw_text=text,
            char_count=len(text),
            meta={**(doc.get("meta") or {}), **(parsed.meta or {}), "parsed_title": parsed.title},
        )

        chunks = chunk_blocks(
            parsed.blocks,
            size=settings.kb_chunk_size,
            overlap=settings.kb_chunk_overlap,
            min_chars=40,
        )
        if not chunks:
            raise IngestError("资料没有生成可用片段，可能是内容过短或格式不受支持")

        doc_code = doc_id[4:] if doc_id.startswith("doc_") else doc_id
        chunk_rows: List[Dict[str, Any]] = []
        for chunk in chunks:
            chunk_id = f"chk_{doc_code}_{chunk.seq}"
            chunk_rows.append(
                {
                    "id": chunk_id,
                    "kb_id": kb_id,
                    "doc_id": doc_id,
                    "seq": chunk.seq,
                    "content": chunk.content,
                    "char_count": chunk.char_count,
                    "locator": chunk.locator,
                    "meta": chunk.meta,
                }
            )
        db.replace_kb_chunks(doc_id, chunk_rows)
        db.update_kb_document(
            doc_id,
            status="embedding",
            progress=60,
            chunk_count=len(chunk_rows),
            char_count=len(text),
        )

        # 重试/覆盖：先清掉旧向量，避免残留片段
        try:
            await store.delete_doc(doc_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("清理旧向量失败 doc=%s err=%s", doc_id, exc)

        embedder = get_embedding_client()
        batch_size = max(1, int(settings.embedding_batch_size))
        total = len(chunk_rows)
        done = 0
        for start in range(0, total, batch_size):
            batch = chunk_rows[start : start + batch_size]
            try:
                vectors = await embedder.embed([row["content"] for row in batch])
            except EmbeddingError as exc:
                raise IngestError(f"资料向量化失败：{exc}") from exc
            if len(vectors) != len(batch):
                raise IngestError("资料向量化返回数量异常")
            points = [
                VectorPoint(
                    id=row["id"],
                    vector=vector,
                    payload={
                        "kb_id": row["kb_id"],
                        "doc_id": row["doc_id"],
                        "chunk_id": row["id"],
                        "seq": row["seq"],
                        "text": row["content"],
                        "locator": row["locator"],
                        "title": title,
                        "doc_title": title,
                        "ref": evidence_ref(row["doc_id"], row["seq"]),
                    },
                )
                for row, vector in zip(batch, vectors)
            ]
            await store.upsert(points)
            done += len(batch)
            progress = 60 + int(35 * done / max(1, total))
            db.update_kb_document(doc_id, progress=min(99, progress))

        db.update_kb_document(
            doc_id,
            status="ready",
            progress=100,
            error=None,
            completed_at=db.now_iso(),
            chunk_count=len(chunk_rows),
            char_count=len(text),
        )
        db.refresh_kb_counts(kb_id)
        logger.info("资料入库完成 doc=%s kb=%s chunks=%s", doc_id, kb_id, len(chunk_rows))
    except Exception as exc:  # noqa: BLE001 - 后台任务必须兜底
        logger.exception("资料入库失败 doc=%s", doc_id)
        try:
            db.replace_kb_chunks(doc_id, [])
        except Exception:  # noqa: BLE001
            pass
        try:
            await store.delete_doc(doc_id)
        except Exception:  # noqa: BLE001
            pass
        db.update_kb_document(
            doc_id,
            status="failed",
            progress=100,
            error=_friendly_error(exc),
            completed_at=db.now_iso(),
        )
        try:
            db.refresh_kb_counts(kb_id)
        except Exception:  # noqa: BLE001
            pass


def enqueue_document(doc_id: str) -> None:
    """兼容同步调用点；真正执行由 FastAPI BackgroundTasks 调度。"""
    asyncio.create_task(ingest_document(doc_id))