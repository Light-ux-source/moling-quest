"""知识库 API 测试：CRUD、归属、限额、入库、检索与删除。"""

from __future__ import annotations

import asyncio
import os

import pytest

from app import db
from app.config import get_settings
from tests.helpers import BASE, dev_login, headers

os.environ.setdefault("LLM_PROVIDER", "mock")

TEXT = (
    "HTTP 缓存分为强缓存和协商缓存。强缓存直接读取本地副本，不向服务器发请求，"
    "常见响应头是 Cache-Control 和 Expires。协商缓存会向服务器确认资源是否变化，"
    "未变化时返回 304，浏览器继续使用本地副本。理解两者的触发条件，是排查缓存问题的关键。"
)


async def _create_kb(client, client_id, name="前端资料库", token=None):
    res = await client.post(
        f"{BASE}/kb",
        json={"name": name, "description": "测试用"},
        headers=headers(client_id, token),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _wait_doc(client, kb_id, doc_id, client_id, token=None):
    for _ in range(60):
        res = await client.get(
            f"{BASE}/kb/{kb_id}/documents/{doc_id}", headers=headers(client_id, token)
        )
        assert res.status_code == 200, res.text
        doc = res.json()
        if doc["status"] in {"ready", "failed"}:
            return doc
        await asyncio.sleep(0.05)
    raise AssertionError("资料处理超时")


@pytest.mark.asyncio
async def test_kb_crud_and_guest_limit(client):
    created = await _create_kb(client, "guest-crud")
    kb_id = created["id"]
    assert created["doc_count"] == 0

    listing = (await client.get(f"{BASE}/kb", headers=headers("guest-crud"))).json()
    assert len(listing["items"]) == 1
    assert listing["limits"]["max_kbs"] == 1
    assert listing["limits"]["can_create"] is False

    detail = (await client.get(f"{BASE}/kb/{kb_id}", headers=headers("guest-crud"))).json()
    assert detail["documents"] == []
    assert detail["limits"]["max_docs_per_kb"] >= 1

    updated = await client.patch(
        f"{BASE}/kb/{kb_id}",
        json={"name": "改名后的资料库"},
        headers=headers("guest-crud"),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "改名后的资料库"

    second = await client.post(
        f"{BASE}/kb", json={"name": "第二个"}, headers=headers("guest-crud")
    )
    assert second.status_code == 429

    deleted = await client.delete(f"{BASE}/kb/{kb_id}", headers=headers("guest-crud"))
    assert deleted.status_code == 204
    missing = await client.get(f"{BASE}/kb/{kb_id}", headers=headers("guest-crud"))
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_kb_ownership_and_login_migration(client):
    created = await _create_kb(client, "guest-migrate", name="迁移资料库")
    kb_id = created["id"]

    other_guest = await client.get(f"{BASE}/kb/{kb_id}", headers=headers("other-guest"))
    assert other_guest.status_code == 404

    token, user = await dev_login(client, "guest-migrate", nickname="迁移旅人")
    listing = (await client.get(f"{BASE}/kb", headers=headers("guest-migrate", token))).json()
    assert len(listing["items"]) == 1
    assert listing["items"][0]["is_guest"] is False

    guest_view = (await client.get(f"{BASE}/kb", headers=headers("guest-migrate"))).json()
    assert guest_view["items"] == []

    other_token, _ = await dev_login(client, "another-user")
    forbidden = await client.get(f"{BASE}/kb/{kb_id}", headers=headers("another-user", other_token))
    assert forbidden.status_code == 404


@pytest.mark.asyncio
async def test_text_ingest_search_and_duplicate(client):
    kb = await _create_kb(client, "guest-text")
    kb_id = kb["id"]
    res = await client.post(
        f"{BASE}/kb/{kb_id}/documents/text",
        json={"title": "HTTP 缓存笔记", "text": TEXT},
        headers=headers("guest-text"),
    )
    assert res.status_code == 202, res.text
    doc = await _wait_doc(client, kb_id, res.json()["id"], "guest-text")
    assert doc["status"] == "ready", doc
    assert doc["chunk_count"] >= 1
    assert doc["char_count"] >= len(TEXT)

    chunks = db.list_doc_chunks(doc["id"])
    assert chunks and chunks[0]["locator"]

    search = await client.post(
        f"{BASE}/kb/{kb_id}/search",
        json={"query": "强缓存", "top_k": 3},
        headers=headers("guest-text"),
    )
    assert search.status_code == 200, search.text
    assert search.json()["items"]

    duplicate = await client.post(
        f"{BASE}/kb/{kb_id}/documents/text",
        json={"title": "HTTP 缓存笔记", "text": TEXT},
        headers=headers("guest-text"),
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_file_upload_and_delete_document(client):
    kb = await _create_kb(client, "guest-file")
    kb_id = kb["id"]
    res = await client.post(
        f"{BASE}/kb/{kb_id}/documents/file",
        files={"file": ("notice.txt", TEXT.encode("utf-8"), "text/plain")},
        headers=headers("guest-file"),
    )
    assert res.status_code == 202, res.text
    doc = await _wait_doc(client, kb_id, res.json()["id"], "guest-file")
    assert doc["status"] == "ready", doc
    assert db.list_doc_chunks(doc["id"])

    deleted = await client.delete(
        f"{BASE}/kb/{kb_id}/documents/{doc['id']}", headers=headers("guest-file")
    )
    assert deleted.status_code == 204
    assert db.list_doc_chunks(doc["id"]) == []
    detail = (await client.get(f"{BASE}/kb/{kb_id}", headers=headers("guest-file"))).json()
    assert detail["documents"] == []
    assert detail["chunk_count"] == 0


@pytest.mark.asyncio
async def test_upload_rejects_bad_type_and_magic(client):
    kb = await _create_kb(client, "guest-bad")
    kb_id = kb["id"]

    bad_ext = await client.post(
        f"{BASE}/kb/{kb_id}/documents/file",
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
        headers=headers("guest-bad"),
    )
    assert bad_ext.status_code == 422

    fake_pdf = await client.post(
        f"{BASE}/kb/{kb_id}/documents/file",
        files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
        headers=headers("guest-bad"),
    )
    assert fake_pdf.status_code == 422


@pytest.mark.asyncio
async def test_url_ssrf_is_rejected(client):
    kb = await _create_kb(client, "guest-url")
    res = await client.post(
        f"{BASE}/kb/{kb['id']}/documents/url",
        json={"url": "http://127.0.0.1/secret"},
        headers=headers("guest-url"),
    )
    assert res.status_code == 422
    assert "内网" in res.json()["detail"] or "本机" in res.json()["detail"]


@pytest.mark.asyncio
async def test_retry_failed_document(client):
    kb = await _create_kb(client, "guest-retry")
    kb_id = kb["id"]
    created = await client.post(
        f"{BASE}/kb/{kb_id}/documents/text",
        json={"title": "重试资料", "text": TEXT},
        headers=headers("guest-retry"),
    )
    doc_id = created.json()["id"]
    db.update_kb_document(doc_id, status="failed", progress=100, error="模拟失败")

    retried = await client.post(
        f"{BASE}/kb/{kb_id}/documents/{doc_id}/retry", headers=headers("guest-retry")
    )
    assert retried.status_code == 202, retried.text
    doc = await _wait_doc(client, kb_id, doc_id, "guest-retry")
    assert doc["status"] == "ready"
    assert doc["error"] is None


@pytest.mark.asyncio
async def test_user_limit_is_five(client):
    token, _ = await dev_login(client, "guest-user-limit")
    ids = []
    for index in range(5):
        kb = await _create_kb(client, "guest-user-limit", name=f"资料库 {index}", token=token)
        ids.append(kb["id"])
    sixth = await client.post(
        f"{BASE}/kb", json={"name": "第六个"}, headers=headers("guest-user-limit", token)
    )
    assert sixth.status_code == 429


@pytest.mark.asyncio
async def test_file_size_limit(client, monkeypatch):
    kb = await _create_kb(client, "guest-size")
    monkeypatch.setattr(get_settings(), "kb_max_file_bytes", 64)
    res = await client.post(
        f"{BASE}/kb/{kb['id']}/documents/file",
        files={"file": ("big.txt", b"x" * 128, "text/plain")},
        headers=headers("guest-size"),
    )
    assert res.status_code == 422
    assert "超过" in res.json()["detail"] or "不能超过" in res.json()["detail"]