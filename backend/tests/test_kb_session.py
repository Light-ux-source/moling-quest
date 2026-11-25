"""会话与知识库集成测试：选库出题、来源引用、降级、归属与旧链路不变。"""

from __future__ import annotations

import asyncio
import os

import pytest

from app import db
from tests.helpers import BASE, dev_login, headers, submit_correct

os.environ.setdefault("LLM_PROVIDER", "mock")

TEXT = (
    "HTTP 缓存分为强缓存和协商缓存。强缓存直接读取本地副本，不向服务器发请求，"
    "常见响应头是 Cache-Control 和 Expires。协商缓存会向服务器确认资源是否变化，"
    "未变化时返回 304，浏览器继续使用本地副本。理解两者的触发条件，是排查缓存问题的关键。"
    "强缓存适合不常变化的静态资源，协商缓存适合需要及时更新的资源。"
)


async def _ready_kb(client, client_id, token=None, name="缓存资料库"):
    res = await client.post(
        f"{BASE}/kb", json={"name": name}, headers=headers(client_id, token)
    )
    assert res.status_code == 201, res.text
    kb_id = res.json()["id"]
    doc = await client.post(
        f"{BASE}/kb/{kb_id}/documents/text",
        json={"title": "HTTP 缓存笔记", "text": TEXT},
        headers=headers(client_id, token),
    )
    assert doc.status_code == 202, doc.text
    doc_id = doc.json()["id"]
    for _ in range(60):
        current = await client.get(
            f"{BASE}/kb/{kb_id}/documents/{doc_id}", headers=headers(client_id, token)
        )
        body = current.json()
        if body["status"] == "ready":
            return kb_id
        if body["status"] == "failed":
            raise AssertionError(body)
        await asyncio.sleep(0.05)
    raise AssertionError("资料未就绪")


async def _create_session(client, client_id, token, kb_ids=None, mode="model", topic="HTTP 缓存"):
    payload = {
        "topic": topic,
        "level": "basic",
        "question_count": 3,
        "types": ["single_choice", "true_false", "short_answer"],
    }
    if kb_ids:
        payload["kb_ids"] = kb_ids
        payload["source_mode"] = mode
    res = await client.post(f"{BASE}/sessions", json=payload, headers=headers(client_id, token))
    assert res.status_code == 202, res.text
    session_id = res.json()["id"]
    for _ in range(80):
        detail = await client.get(
            f"{BASE}/sessions/{session_id}", headers=headers(client_id, token)
        )
        body = detail.json()
        if body["status"] in {"ready", "failed", "completed"}:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError("会话生成超时")


@pytest.mark.asyncio
async def test_session_kb_only_generates_from_knowledge_base(client):
    kb_id = await _ready_kb(client, "guest-kb-session")
    session = await _create_session(client, "guest-kb-session", None, [kb_id], "kb_only")
    assert session["status"] == "ready", session
    assert session["kb_ids"] == [kb_id]
    assert session["source_mode"] == "kb_only"
    assert session["retrieval"]["chunks"] >= 1
    assert session["retrieval"]["rounds"] >= 1
    assert any(source["kind"] == "kb" for source in session["sources"])
    assert any(source["url"].startswith("kb://") for source in session["sources"])
    assert session["questions"]
    # Mock RAG 出题会把允许的 ref 写入 source_refs
    assert any(question.get("source_refs") for question in db.list_questions(session["id"]))


@pytest.mark.asyncio
async def test_session_defaults_to_kb_only_when_kb_ids_given(client):
    kb_id = await _ready_kb(client, "guest-kb-default")
    payload = {
        "topic": "HTTP 缓存",
        "level": "basic",
        "question_count": 3,
        "kb_ids": [kb_id],
    }
    res = await client.post(f"{BASE}/sessions", json=payload, headers=headers("guest-kb-default"))
    assert res.status_code == 202, res.text
    session_id = res.json()["id"]
    for _ in range(80):
        body = (
            await client.get(f"{BASE}/sessions/{session_id}", headers=headers("guest-kb-default"))
        ).json()
        if body["status"] in {"ready", "failed"}:
            break
        await asyncio.sleep(0.05)
    assert body["source_mode"] == "kb_only"


@pytest.mark.asyncio
async def test_session_without_kb_keeps_old_behavior(client):
    session = await _create_session(client, "guest-old", None)
    assert session["status"] == "ready"
    assert session["kb_ids"] == []
    assert session["source_mode"] == "model"
    assert session["retrieval"] is None
    # Mock 模式仍返回模拟联网来源
    assert session["sources"]
    assert all(source["kind"] == "web" for source in session["sources"])


@pytest.mark.asyncio
async def test_hybrid_merges_web_and_kb_sources(client):
    kb_id = await _ready_kb(client, "guest-kb-hybrid")
    session = await _create_session(client, "guest-kb-hybrid", None, [kb_id], "hybrid")
    assert session["status"] == "ready", session
    kinds = {source["kind"] for source in session["sources"]}
    assert "kb" in kinds
    assert "web" in kinds
    assert session["retrieval"]["web_sources"] >= 1


@pytest.mark.asyncio
async def test_session_rejects_other_users_kb(client):
    kb_id = await _ready_kb(client, "guest-owner")
    res = await client.post(
        f"{BASE}/sessions",
        json={
            "topic": "HTTP 缓存",
            "level": "basic",
            "question_count": 3,
            "kb_ids": [kb_id],
            "source_mode": "kb_only",
        },
        headers=headers("guest-thief"),
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_session_rejects_empty_kb(client):
    res = await client.post(f"{BASE}/kb", json={"name": "空资料库"}, headers=headers("guest-empty"))
    kb_id = res.json()["id"]
    created = await client.post(
        f"{BASE}/sessions",
        json={
            "topic": "HTTP 缓存",
            "level": "basic",
            "question_count": 3,
            "kb_ids": [kb_id],
            "source_mode": "kb_only",
        },
        headers=headers("guest-empty"),
    )
    assert created.status_code == 409
    assert "资料" in created.json()["detail"]


@pytest.mark.asyncio
async def test_kb_only_empty_retrieval_fails_and_refunds_guest_trial(client):
    res = await client.post(
        f"{BASE}/kb", json={"name": "无向量资料库"}, headers=headers("guest-vector-empty")
    )
    kb_id = res.json()["id"]
    # 伪造“有片段”的计数，但不写 chunks / vectors，触发真实空检索
    db.update_knowledge_base(kb_id, chunk_count=1)

    created = await client.post(
        f"{BASE}/sessions",
        json={
            "topic": "完全不存在的主题",
            "level": "basic",
            "question_count": 3,
            "kb_ids": [kb_id],
            "source_mode": "kb_only",
        },
        headers=headers("guest-vector-empty"),
    )
    assert created.status_code == 202
    session_id = created.json()["id"]
    for _ in range(80):
        body = (
            await client.get(
                f"{BASE}/sessions/{session_id}", headers=headers("guest-vector-empty")
            )
        ).json()
        if body["status"] in {"ready", "failed"}:
            break
        await asyncio.sleep(0.05)
    assert body["status"] == "failed"
    assert "资料库" in (body["error"] or "")
    # 游客失败后试用额度被退回
    assert db.guest_trial_used("guest-vector-empty") is False


@pytest.mark.asyncio
async def test_regenerate_preserves_kb_selection(client):
    kb_id = await _ready_kb(client, "guest-kb-regen")
    session = await _create_session(client, "guest-kb-regen", None, [kb_id], "kb_only")
    assert session["status"] == "ready"

    regen = await client.post(
        f"{BASE}/sessions/{session['id']}/regenerate", headers=headers("guest-kb-regen")
    )
    assert regen.status_code == 202, regen.text
    for _ in range(80):
        body = (
            await client.get(f"{BASE}/sessions/{session['id']}", headers=headers("guest-kb-regen"))
        ).json()
        if body["status"] in {"ready", "failed"}:
            break
        await asyncio.sleep(0.05)
    assert body["status"] == "ready"
    assert body["kb_ids"] == [kb_id]
    assert body["source_mode"] == "kb_only"


@pytest.mark.asyncio
async def test_report_keeps_kb_sources_and_refs(client):
    kb_id = await _ready_kb(client, "guest-kb-report")
    session = await _create_session(client, "guest-kb-report", None, [kb_id], "kb_only")
    assert session["status"] == "ready"
    await submit_correct(client, "guest-kb-report", session["id"])

    report = await client.get(
        f"{BASE}/sessions/{session['id']}/report", headers=headers("guest-kb-report")
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert any(source["kind"] == "kb" for source in body["sources"])
    assert any(
        ref.startswith("kb://")
        for item in body["items"]
        for ref in (item.get("source_refs") or [])
    )


@pytest.mark.asyncio
async def test_daily_rejects_kb(client):
    kb_id = await _ready_kb(client, "guest-kb-daily")
    res = await client.post(
        f"{BASE}/sessions",
        json={
            "topic": "今日挑战",
            "level": "basic",
            "question_count": 3,
            "kind": "daily",
            "kb_ids": [kb_id],
            "source_mode": "kb_only",
        },
        headers=headers("guest-kb-daily"),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_max_three_kbs_per_session(client):
    token, _ = await dev_login(client, "guest-many-kbs")
    ids = []
    for index in range(4):
        ids.append(
            await _ready_kb(client, "guest-many-kbs", token=token, name=f"资料库 {index}")
        )
    res = await client.post(
        f"{BASE}/sessions",
        json={
            "topic": "HTTP 缓存",
            "level": "basic",
            "question_count": 3,
            "kb_ids": ids,
            "source_mode": "kb_only",
        },
        headers=headers("guest-many-kbs", token),
    )
    assert res.status_code == 422