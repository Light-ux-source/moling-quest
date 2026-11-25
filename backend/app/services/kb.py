"""知识库领域服务：归属校验、限额、资料入库、删除与检索调试。

本层不感知 HTTP；路由只做参数解析与状态码映射。
"""

from __future__ import annotations

import hashlib
import logging
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import UploadFile

from .. import db
from ..config import get_settings
from ..rag.embeddings import EmbeddingError, get_embedding_client
from ..rag.parsers import ParseError, detect_kind
from ..rag.vector_store import VectorStoreError, get_vector_store
from ..rag.web import WebFetchError, assert_safe_url

logger = logging.getLogger(__name__)

_ALLOWED_EXTS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".txt",
    ".text",
    ".md",
    ".markdown",
    ".html",
    ".htm",
}
_KIND_TITLES = {
    "file": "文件",
    "web": "网页",
    "text": "文本",
}


class KbError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _new_kb_id() -> str:
    return f"kb_{uuid.uuid4().hex[:12]}"


def _new_doc_id() -> str:
    return f"doc_{uuid.uuid4().hex[:12]}"


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _is_owner(row: Dict[str, Any], user: Optional[Dict[str, Any]], client_id: str) -> bool:
    owner = row.get("user_id")
    if owner:
        return bool(user and user.get("id") == owner)
    return row.get("client_id") == client_id


def _require_kb_owner(
    kb_id: str, user: Optional[Dict[str, Any]], client_id: str
) -> Dict[str, Any]:
    row = db.get_knowledge_base(kb_id)
    if not row or not _is_owner(row, user, client_id):
        raise KbError("资料库不存在或已过期", 404)
    return row


def limits(user: Optional[Dict[str, Any]], client_id: str) -> Dict[str, Any]:
    settings = get_settings()
    is_guest = user is None
    used = db.count_knowledge_bases(user["id"] if user else None, client_id)
    max_kbs = settings.kb_limit_for(is_guest)
    return {
        "max_kbs": max_kbs,
        "used_kbs": used,
        "remaining_kbs": max(0, max_kbs - used),
        "max_docs_per_kb": settings.kb_max_docs_per_kb,
        "max_file_bytes": settings.kb_max_file_bytes,
        "max_text_chars": settings.kb_max_text_chars,
        "max_session_kbs": settings.kb_max_session_kbs,
        "can_create": used < max_kbs,
    }


def summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row.get("name") or "未命名资料库",
        "description": row.get("description"),
        "doc_count": int(row.get("doc_count") or 0),
        "chunk_count": int(row.get("chunk_count") or 0),
        "char_count": int(row.get("char_count") or 0),
        "status": row.get("status") or "active",
        "is_guest": not bool(row.get("user_id")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def document_public(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "kb_id": row["kb_id"],
        "kind": row.get("kind") or "file",
        "title": row.get("title") or "未命名资料",
        "source_url": row.get("source_url"),
        "filename": row.get("filename"),
        "mime": row.get("mime"),
        "size_bytes": int(row.get("size_bytes") or 0),
        "status": row.get("status") or "queued",
        "progress": int(row.get("progress") or 0),
        "error": row.get("error"),
        "char_count": int(row.get("char_count") or 0),
        "chunk_count": int(row.get("chunk_count") or 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "completed_at": row.get("completed_at"),
    }


def list_kb(user: Optional[Dict[str, Any]], client_id: str) -> List[Dict[str, Any]]:
    rows = db.list_knowledge_bases(user["id"] if user else None, client_id)
    return [summary(row) for row in rows]


def create_kb(
    user: Optional[Dict[str, Any]],
    client_id: str,
    name: str,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    settings = get_settings()
    if not settings.kb_enabled:
        raise KbError("知识库功能暂未开放", 503)
    if not settings.rag_available:
        raise KbError("知识库向量化未启用，请检查 EMBEDDING_* 配置", 503)
    current = limits(user, client_id)
    if not current["can_create"]:
        identity = "游客" if user is None else "账号"
        raise KbError(
            f"{identity}最多创建 {current['max_kbs']} 个资料库，删掉一个再试", 429
        )
    cleaned_name = " ".join(str(name or "").replace("\u3000", " ").split())[:40]
    if not cleaned_name:
        raise KbError("资料库名称不能为空", 422)
    kb_id = _new_kb_id()
    provider = settings.effective_embedding_provider
    db.create_knowledge_base(
        {
            "id": kb_id,
            "user_id": user["id"] if user else None,
            "client_id": client_id,
            "name": cleaned_name,
            "description": (description or "").strip()[:120] or None,
            "embedding_model": settings.embedding_model if provider == "openai" else "hash-char-ngram",
            "embedding_dim": settings.embedding_dim,
        }
    )
    row = db.get_knowledge_base(kb_id)
    if not row:
        raise KbError("资料库创建失败，请重试", 500)
    return summary(row)


def update_kb(
    user: Optional[Dict[str, Any]],
    client_id: str,
    kb_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    _require_kb_owner(kb_id, user, client_id)
    fields: Dict[str, Any] = {}
    if name is not None:
        cleaned = " ".join(str(name).replace("\u3000", " ").split())[:40]
        if not cleaned:
            raise KbError("资料库名称不能为空", 422)
        fields["name"] = cleaned
    if description is not None:
        fields["description"] = str(description).strip()[:120] or None
    if not fields:
        raise KbError("没有可更新的内容", 400)
    db.update_knowledge_base(kb_id, **fields)
    row = db.get_knowledge_base(kb_id)
    return summary(row or {})


def detail(
    user: Optional[Dict[str, Any]], client_id: str, kb_id: str
) -> Dict[str, Any]:
    row = _require_kb_owner(kb_id, user, client_id)
    data = summary(row)
    data["documents"] = [document_public(doc) for doc in db.list_kb_documents(kb_id)]
    data["limits"] = limits(user, client_id)
    return data


def _check_doc_quota(kb_id: str) -> None:
    settings = get_settings()
    count = len(db.list_kb_documents(kb_id))
    if count >= settings.kb_max_docs_per_kb:
        raise KbError(
            f"每个资料库最多 {settings.kb_max_docs_per_kb} 份资料，删掉一份再试", 429
        )


def _safe_file_path(kb_id: str, doc_id: str, suffix: str) -> Path:
    settings = get_settings()
    directory = Path(settings.kb_upload_dir) / kb_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{doc_id}{suffix}"


def _check_zip_safety(data: bytes, max_bytes: int) -> None:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 10000:
                raise KbError("文档内部文件过多，已拒绝处理", 422)
            total = sum(info.file_size for info in infos)
            if total > max_bytes * 20:
                raise KbError("文档解压后体积异常，已拒绝处理", 422)
            for info in infos:
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    raise KbError("文档内部路径异常，已拒绝处理", 422)
    except zipfile.BadZipFile as exc:
        raise KbError("文件内容损坏，无法解析", 422) from exc


async def _read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise KbError(f"文件不能超过 {max_bytes // 1024 // 1024}MB", 422)
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise KbError("文件内容为空", 422)
    return data


async def create_file_document(
    user: Optional[Dict[str, Any]],
    client_id: str,
    kb_id: str,
    upload: UploadFile,
) -> Dict[str, Any]:
    settings = get_settings()
    _require_kb_owner(kb_id, user, client_id)
    _check_doc_quota(kb_id)
    filename = str(upload.filename or "").strip()[:255]
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_EXTS:
        raise KbError("暂不支持这种文件类型；支持 PDF、DOCX、PPTX、XLSX、TXT、MD、HTML", 422)
    data = await _read_upload(upload, settings.kb_max_file_bytes)
    try:
        kind = detect_kind(filename, upload.content_type or "")
    except ParseError as exc:
        raise KbError(str(exc), 422) from exc
    if kind == "pdf" and not data.lstrip().startswith(b"%PDF"):
        raise KbError("文件内容与 .pdf 扩展名不符", 422)
    if kind in {"docx", "pptx", "xlsx"}:
        if not data.startswith(b"PK"):
            raise KbError("文件内容与 Office 扩展名不符", 422)
        _check_zip_safety(data, settings.kb_max_file_bytes)

    digest = _hash_bytes(data)
    existing = db.find_kb_document_by_hash(kb_id, digest)
    if existing:
        raise KbError("这份资料已经在资料库里了", 409)

    doc_id = _new_doc_id()
    path = _safe_file_path(kb_id, doc_id, suffix)
    path.write_bytes(data)
    title = Path(filename).stem[:200] or "未命名资料"
    try:
        db.create_kb_document(
            {
                "id": doc_id,
                "kb_id": kb_id,
                "user_id": user["id"] if user else None,
                "client_id": client_id,
                "kind": "file",
                "title": title,
                "filename": filename,
                "mime": (upload.content_type or "")[:100] or None,
                "size_bytes": len(data),
                "content_hash": digest,
                "stored_path": str(path),
                "status": "queued",
                "progress": 0,
                "meta": {"suffix": suffix, "kind": kind},
            }
        )
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise
    db.refresh_kb_counts(kb_id)
    row = db.get_kb_document(doc_id)
    return document_public(row or {})


async def create_url_document(
    user: Optional[Dict[str, Any]],
    client_id: str,
    kb_id: str,
    url: str,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    settings = get_settings()
    _require_kb_owner(kb_id, user, client_id)
    _check_doc_quota(kb_id)
    url = str(url or "").strip()
    try:
        await assert_safe_url(url)
    except WebFetchError as exc:
        raise KbError(str(exc), 422) from exc
    digest = _hash_text(url)
    existing = db.find_kb_document_by_hash(kb_id, digest)
    if existing:
        raise KbError("这个链接已经在资料库里了", 409)
    doc_id = _new_doc_id()
    db.create_kb_document(
        {
            "id": doc_id,
            "kb_id": kb_id,
            "user_id": user["id"] if user else None,
            "client_id": client_id,
            "kind": "web",
            "title": (title or url)[:200],
            "source_url": url[:2048],
            "size_bytes": 0,
            "content_hash": digest,
            "status": "queued",
            "progress": 0,
            "meta": {"max_bytes": settings.kb_max_url_bytes},
        }
    )
    db.refresh_kb_counts(kb_id)
    row = db.get_kb_document(doc_id)
    return document_public(row or {})


def create_text_document(
    user: Optional[Dict[str, Any]],
    client_id: str,
    kb_id: str,
    title: str,
    text: str,
) -> Dict[str, Any]:
    settings = get_settings()
    _require_kb_owner(kb_id, user, client_id)
    _check_doc_quota(kb_id)
    cleaned_title = " ".join(str(title or "").replace("\u3000", " ").split())[:200]
    cleaned_text = str(text or "").strip()
    if not cleaned_title or not cleaned_text:
        raise KbError("标题和正文都不能为空", 422)
    if len(cleaned_text) > settings.kb_max_text_chars:
        raise KbError(f"文本不能超过 {settings.kb_max_text_chars} 字", 422)
    digest = _hash_text(f"{cleaned_title}\n{cleaned_text}")
    existing = db.find_kb_document_by_hash(kb_id, digest)
    if existing:
        raise KbError("这段文本已经在资料库里了", 409)
    doc_id = _new_doc_id()
    db.create_kb_document(
        {
            "id": doc_id,
            "kb_id": kb_id,
            "user_id": user["id"] if user else None,
            "client_id": client_id,
            "kind": "text",
            "title": cleaned_title,
            "size_bytes": len(cleaned_text.encode("utf-8")),
            "content_hash": digest,
            "raw_text": cleaned_text,
            "status": "queued",
            "progress": 0,
            "meta": {"chars": len(cleaned_text)},
        }
    )
    db.refresh_kb_counts(kb_id)
    row = db.get_kb_document(doc_id)
    return document_public(row or {})


def get_document(
    user: Optional[Dict[str, Any]], client_id: str, kb_id: str, doc_id: str
) -> Dict[str, Any]:
    _require_kb_owner(kb_id, user, client_id)
    row = db.get_kb_document(doc_id)
    if not row or row.get("kb_id") != kb_id:
        raise KbError("资料不存在或已过期", 404)
    return document_public(row)


def retry_document(
    user: Optional[Dict[str, Any]], client_id: str, kb_id: str, doc_id: str
) -> Dict[str, Any]:
    _require_kb_owner(kb_id, user, client_id)
    row = db.get_kb_document(doc_id)
    if not row or row.get("kb_id") != kb_id:
        raise KbError("资料不存在或已过期", 404)
    if row.get("status") != "failed":
        raise KbError("只有处理失败的资料可以重试", 409)
    db.update_kb_document(
        doc_id,
        status="queued",
        progress=0,
        error=None,
        completed_at=None,
    )
    db.refresh_kb_counts(kb_id)
    fresh = db.get_kb_document(doc_id) or row
    return document_public(fresh)


async def delete_document(
    user: Optional[Dict[str, Any]], client_id: str, kb_id: str, doc_id: str
) -> None:
    _require_kb_owner(kb_id, user, client_id)
    row = db.get_kb_document(doc_id)
    if not row or row.get("kb_id") != kb_id:
        raise KbError("资料不存在或已过期", 404)
    try:
        await get_vector_store(get_settings()).delete_doc(doc_id)
    except Exception as exc:  # noqa: BLE001 - 向量清理失败不阻塞用户删除
        logger.warning("删除资料向量失败 doc=%s err=%s", doc_id, exc)
    stored = row.get("stored_path")
    if stored:
        try:
            Path(stored).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    db.delete_kb_document(doc_id)
    db.refresh_kb_counts(kb_id)


async def delete_kb(
    user: Optional[Dict[str, Any]], client_id: str, kb_id: str
) -> None:
    row = _require_kb_owner(kb_id, user, client_id)
    docs = db.list_kb_documents(kb_id)
    try:
        await get_vector_store(get_settings()).delete_kb(kb_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除资料库向量失败 kb=%s err=%s", kb_id, exc)
    for doc in docs:
        stored = doc.get("stored_path")
        if stored:
            try:
                Path(stored).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
    db.delete_knowledge_base(kb_id)


async def purge_user_knowledge(user_id: str) -> None:
    """注销账号：删除该用户全部资料库、文件与向量（隐私优先）。"""
    rows = db.list_knowledge_bases(user_id, "", limit=100)
    store = get_vector_store(get_settings())
    for row in rows:
        kb_id = row["id"]
        docs = db.list_kb_documents(kb_id)
        try:
            await store.delete_kb(kb_id)
        except Exception:  # noqa: BLE001
            pass
        for doc in docs:
            stored = doc.get("stored_path")
            if stored:
                try:
                    Path(stored).unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass
    db.delete_user_knowledge_bases(user_id)


def validate_session_kbs(
    user: Optional[Dict[str, Any]], client_id: str, kb_ids: List[str]
) -> List[Dict[str, Any]]:
    settings = get_settings()
    if not kb_ids:
        return []
    if not settings.kb_enabled or not settings.rag_available:
        raise KbError("知识库功能暂未启用", 503)
    if len(kb_ids) > settings.kb_max_session_kbs:
        raise KbError(f"一次最多选择 {settings.kb_max_session_kbs} 个资料库", 422)
    rows = []
    for kb_id in kb_ids:
        row = _require_kb_owner(kb_id, user, client_id)
        if row.get("status") != "active":
            raise KbError("资料库正在处理中，请稍后再试", 409)
        if int(row.get("chunk_count") or 0) <= 0:
            raise KbError("这个资料库还没有可用的资料片段，请先上传并等待处理完成", 409)
        rows.append(row)
    return rows


def names_for(kb_ids: List[str]) -> Dict[str, str]:
    output: Dict[str, str] = {}
    for kb_id in kb_ids:
        row = db.get_knowledge_base(kb_id)
        if row:
            output[kb_id] = row.get("name") or "资料库"
    return output


def doc_titles_for(kb_ids: List[str], limit: int = 12) -> List[str]:
    titles: List[str] = []
    for kb_id in kb_ids:
        for doc in db.list_kb_documents(kb_id):
            title = doc.get("title")
            if title and title not in titles:
                titles.append(title)
            if len(titles) >= limit:
                return titles
    return titles


async def search(
    user: Optional[Dict[str, Any]],
    client_id: str,
    kb_id: str,
    query: str,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    _require_kb_owner(kb_id, user, client_id)
    query = str(query or "").strip()
    if not query:
        raise KbError("检索词不能为空", 422)
    try:
        embedder = get_embedding_client()
        vector = (await embedder.embed([query]))[0]
        hits = await get_vector_store(get_settings()).search([kb_id], vector, limit=top_k)
    except (EmbeddingError, VectorStoreError, Exception) as exc:  # noqa: BLE001
        logger.warning("资料库检索调试向量失败，降级词法: %s", exc)
        rows = db.search_kb_chunks_lexical([kb_id], query, limit=top_k)
        return [
            {
                "chunk_id": row["chunk_id"],
                "doc_id": row["doc_id"],
                "doc_title": row.get("title") or "",
                "locator": row.get("locator") or "",
                "content": row.get("text") or "",
                "score": float(row.get("score") or 0),
            }
            for row in rows
        ]
    output = []
    for hit in hits:
        payload = hit.payload or {}
        output.append(
            {
                "chunk_id": hit.chunk_id,
                "doc_id": payload.get("doc_id") or "",
                "doc_title": payload.get("doc_title") or payload.get("title") or "",
                "locator": payload.get("locator") or "",
                "content": payload.get("text") or "",
                "score": float(hit.score or 0),
            }
        )
    return output