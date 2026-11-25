"""入库流水线单元测试：网页、失败清理、幂等、超限与隐私删除。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import db
from app.config import get_settings
from app.rag.embeddings import EmbeddingError
from app.rag.parsers import ParseError
from app.rag.types import ParsedDocument, TextBlock
from app.services import ingest as ingest_service
from app.services import kb as kb_service
from tests.helpers import BASE, dev_login, headers

os.environ.setdefault("LLM_PROVIDER", "mock")

TEXT = (
    "HTTP 缓存分为强缓存和协商缓存。强缓存直接读取本地副本，不向服务器发请求。"
    "协商缓存会向服务器确认资源是否变化，未变化时返回 304。"
    "理解两者的触发条件，是排查缓存问题的关键。"
)


async def _guest_kb(client, client_id="guest-ingest"):
    res = await client.post(f"{BASE}/kb", json={"name": "入库测试"}, headers=headers(client_id))
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _wait_doc(client, kb_id, doc_id, client_id, token=None):
    for _ in range(60):
        res = await client.get(
            f"{BASE}/kb/{kb_id}/documents/{doc_id}", headers=headers(client_id, token)
        )
        body = res.json()
        if body["status"] in {"ready", "failed"}:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError("timeout")


@pytest.mark.asyncio
async def test_reingest_is_idempotent(client):
    kb_id = await _guest_kb(client, "guest-idempotent")
    res = await client.post(
        f"{BASE}/kb/{kb_id}/documents/text",
        json={"title": "幂等资料", "text": TEXT},
        headers=headers("guest-idempotent"),
    )
    doc_id = res.json()["id"]
    await _wait_doc(client, kb_id, doc_id, "guest-idempotent")
    first_chunks = db.list_doc_chunks(doc_id)
    assert first_chunks

    await ingest_service.ingest_document(doc_id)
    second_chunks = db.list_doc_chunks(doc_id)
    assert len(second_chunks) == len(first_chunks)
    assert [chunk["content"] for chunk in second_chunks] == [
        chunk["content"] for chunk in first_chunks
    ]


@pytest.mark.asyncio
async def test_ingest_embedding_failure_marks_failed_and_cleans_chunks(client, monkeypatch):
    kb_id = await _guest_kb(client, "guest-embed-fail")
    res = await client.post(
        f"{BASE}/kb/{kb_id}/documents/text",
        json={"title": "会失败的资料", "text": TEXT},
        headers=headers("guest-embed-fail"),
    )
    doc_id = res.json()["id"]
    await _wait_doc(client, kb_id, doc_id, "guest-embed-fail")

    class BrokenEmbedder:
        async def embed(self, texts):
            raise EmbeddingError("模拟向量化故障")

    monkeypatch.setattr(ingest_service, "get_embedding_client", lambda: BrokenEmbedder())
    await ingest_service.ingest_document(doc_id)
    doc = db.get_kb_document(doc_id)
    assert doc["status"] == "failed"
    assert "向量化" in (doc["error"] or "")
    assert db.list_doc_chunks(doc_id) == []


@pytest.mark.asyncio
async def test_ingest_web_document_with_monkeypatch(client, monkeypatch):
    kb_id = await _guest_kb(client, "guest-web")

    async def fake_safe(url):
        return url

    async def fake_fetch(url, **kwargs):
        return ParsedDocument(
            title="网页缓存指南",
            blocks=[
                TextBlock("强缓存命中时直接使用本地副本。", locator="第 1 段"),
                TextBlock("协商缓存未变化时返回 304。", locator="第 2 段"),
            ],
            meta={"kind": "html", "url": url},
        )

    monkeypatch.setattr(kb_service, "assert_safe_url", fake_safe)
    monkeypatch.setattr(ingest_service, "fetch_document", fake_fetch)

    res = await client.post(
        f"{BASE}/kb/{kb_id}/documents/url",
        json={"url": "https://example.com/cache"},
        headers=headers("guest-web"),
    )
    assert res.status_code == 202, res.text
    doc = await _wait_doc(client, kb_id, res.json()["id"], "guest-web")
    assert doc["status"] == "ready", doc
    assert doc["title"] == "网页缓存指南"
    assert doc["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_ingest_oversized_text_fails(client, monkeypatch):
    kb_id = await _guest_kb(client, "guest-too-long")
    res = await client.post(
        f"{BASE}/kb/{kb_id}/documents/text",
        json={"title": "超长资料", "text": TEXT},
        headers=headers("guest-too-long"),
    )
    doc_id = res.json()["id"]
    await _wait_doc(client, kb_id, doc_id, "guest-too-long")

    monkeypatch.setattr(get_settings(), "kb_max_text_chars", 10)
    await ingest_service.ingest_document(doc_id)
    doc = db.get_kb_document(doc_id)
    assert doc["status"] == "failed"
    assert "超过" in (doc["error"] or "")


@pytest.mark.asyncio
async def test_account_deletion_purges_knowledge_base(client):
    token, user = await dev_login(client, "guest-delete-account")
    res = await client.post(
        f"{BASE}/kb",
        json={"name": "待删除资料库"},
        headers=headers("guest-delete-account", token),
    )
    kb_id = res.json()["id"]
    doc = await client.post(
        f"{BASE}/kb/{kb_id}/documents/text",
        json={"title": "待删除资料", "text": TEXT},
        headers=headers("guest-delete-account", token),
    )
    doc_id = doc.json()["id"]
    await _wait_doc(client, kb_id, doc_id, "guest-delete-account", token)
    stored = db.get_kb_document(doc_id).get("stored_path")

    deleted = await client.delete(
        f"{BASE}/profile", headers=headers("guest-delete-account", token)
    )
    assert deleted.status_code == 204
    assert db.get_knowledge_base(kb_id) is None
    assert db.list_kb_documents(kb_id) == []
    if stored:
        assert not Path(stored).exists()


@pytest.mark.asyncio
async def test_delete_kb_removes_vectors(client):
    kb_id = await _guest_kb(client, "guest-delete-vectors")
    res = await client.post(
        f"{BASE}/kb/{kb_id}/documents/text",
        json={"title": "待删向量", "text": TEXT},
        headers=headers("guest-delete-vectors"),
    )
    doc_id = res.json()["id"]
    await _wait_doc(client, kb_id, doc_id, "guest-delete-vectors")

    store = ingest_service.get_vector_store(get_settings())
    before = await store.count(kb_id=kb_id)
    assert before >= 1
    deleted = await client.delete(f"{BASE}/kb/{kb_id}", headers=headers("guest-delete-vectors"))
    assert deleted.status_code == 204
    after = await store.count(kb_id=kb_id)
    assert after == 0


@pytest.mark.asyncio
async def test_ingest_parse_failure_is_actionable(client):
    kb_id = await _guest_kb(client, "guest-parse-fail")
    doc_id = "doc_parse_fail_test"
    db.create_kb_document(
        {
            "id": doc_id,
            "kb_id": kb_id,
            "client_id": "guest-parse-fail",
            "kind": "file",
            "title": "坏文件",
            "filename": "bad.pdf",
            "stored_path": "/tmp/not-a-real-file.pdf",
            "status": "queued",
        }
    )
    await ingest_service.ingest_document(doc_id)
    doc = db.get_kb_document(doc_id)
    assert doc["status"] == "failed"
    assert "源文件" in (doc["error"] or "") or "处理失败" in (doc["error"] or "")