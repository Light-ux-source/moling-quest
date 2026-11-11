"""重新生成：复用同一会话，不额外消耗额度；失败返还、重试只计一次。"""

from __future__ import annotations

import pytest

from app import db
from app.api import routes
from app.config import get_settings
from app.services import quota
from tests.helpers import BASE, create_ready, dev_login, headers, submit_correct


def _enable(monkeypatch, *, guest=1, daily=3):
    settings = get_settings()
    monkeypatch.setattr(settings, "quota_enforced", True)
    monkeypatch.setattr(settings, "guest_trial_limit", guest)
    monkeypatch.setattr(settings, "daily_quota_user", daily)


async def _profile(client, client_id, token=None):
    res = await client.get(f"{BASE}/profile", headers=headers(client_id, token))
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_regenerate_reuses_session_chapter_and_does_not_consume_quota(client, monkeypatch):
    _enable(monkeypatch, daily=3)
    token, _ = await dev_login(client, "regen_user")
    created, detail = await create_ready(client, "regen_user", token, topic="HTTP 缓存")
    old_question_ids = [q["id"] for q in detail["questions"]]

    chapters_before = (
        await client.get(f"{BASE}/chapters", headers=headers("regen_user", token))
    ).json()["items"]
    assert len(chapters_before) == 1

    res = await client.post(
        f"{BASE}/sessions/{created['id']}/regenerate",
        headers=headers("regen_user", token),
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["id"] == created["id"]
    assert body["chapter_id"] == created["chapter_id"]

    fresh = (
        await client.get(f"{BASE}/sessions/{created['id']}", headers=headers("regen_user", token))
    ).json()
    assert fresh["status"] == "ready"
    assert fresh["chapter_id"] == created["chapter_id"]
    new_question_ids = [q["id"] for q in fresh["questions"]]
    assert len(new_question_ids) == len(old_question_ids)
    assert set(new_question_ids).isdisjoint(old_question_ids)

    profile = await _profile(client, "regen_user", token)
    assert profile["quota"]["used"] == 1
    assert profile["quota"]["remaining"] == 2

    chapters_after = (
        await client.get(f"{BASE}/chapters", headers=headers("regen_user", token))
    ).json()["items"]
    assert len(chapters_after) == 1
    assert chapters_after[0]["id"] == created["chapter_id"]

    # 仍可再用 2 次；第 4 次创建才被拦截。
    for index in range(2):
        await create_ready(client, "regen_user", token, topic=f"额外主题 {index}")
    profile = await _profile(client, "regen_user", token)
    assert profile["quota"]["used"] == 3
    fourth = await client.post(
        f"{BASE}/sessions",
        json={"topic": "第四组", "level": "basic", "question_count": 3},
        headers=headers("regen_user", token),
    )
    assert fourth.status_code == 429
    assert "3 组" in fourth.json()["detail"]


@pytest.mark.asyncio
async def test_guest_regenerate_keeps_single_trial(client, monkeypatch):
    _enable(monkeypatch, guest=1)
    created, _ = await create_ready(client, "regen_guest", topic="游客重生成")

    res = await client.post(
        f"{BASE}/sessions/{created['id']}/regenerate",
        headers=headers("regen_guest"),
    )
    assert res.status_code == 202, res.text

    profile = await _profile(client, "regen_guest")
    assert profile["is_guest"] is True
    assert profile["quota"]["used"] == 1
    assert profile["quota"]["remaining"] == 0

    second = await client.post(
        f"{BASE}/sessions",
        json={"topic": "游客第二组", "level": "basic", "question_count": 3},
        headers=headers("regen_guest"),
    )
    assert second.status_code == 429
    assert "登录" in second.json()["detail"]


@pytest.mark.asyncio
async def test_regenerate_rejects_completed_failed_and_foreign_sessions(client, monkeypatch):
    _enable(monkeypatch)
    token, _ = await dev_login(client, "regen_owner")
    created, _ = await create_ready(client, "regen_owner", token, topic="归属测试")
    session_id = created["id"]

    await submit_correct(client, "regen_owner", session_id, token)
    completed = (
        await client.get(f"{BASE}/sessions/{session_id}", headers=headers("regen_owner", token))
    ).json()
    assert completed["status"] == "completed"

    done = await client.post(
        f"{BASE}/sessions/{session_id}/regenerate",
        headers=headers("regen_owner", token),
    )
    assert done.status_code == 409
    assert "待答题" in done.json()["detail"]

    # 失败会话也不能走 regenerate（应走 /retry）。
    db.update_session(session_id, status="failed", error="boom")
    failed = await client.post(
        f"{BASE}/sessions/{session_id}/regenerate",
        headers=headers("regen_owner", token),
    )
    assert failed.status_code == 409

    other_token, _ = await dev_login(client, "regen_other")
    foreign = await client.post(
        f"{BASE}/sessions/{session_id}/regenerate",
        headers=headers("regen_other", other_token),
    )
    assert foreign.status_code == 404

    anonymous = await client.post(
        f"{BASE}/sessions/{session_id}/regenerate",
        headers=headers("regen_anonymous"),
    )
    assert anonymous.status_code == 404


@pytest.mark.asyncio
async def test_regenerate_failure_refunds_and_retry_counts_only_once(client, monkeypatch):
    _enable(monkeypatch, daily=3)
    token, _ = await dev_login(client, "regen_fail")
    created, _ = await create_ready(client, "regen_fail", token, topic="重生成失败")

    original_generate = routes.generate_for_session

    async def fail(session_id: str) -> None:
        session = db.get_session(session_id)
        db.update_session(session_id, status="failed", stage="failed", progress=100, error="boom")
        quota.refund_failure(session or {})

    monkeypatch.setattr(routes, "generate_for_session", fail)
    res = await client.post(
        f"{BASE}/sessions/{created['id']}/regenerate",
        headers=headers("regen_fail", token),
    )
    assert res.status_code == 202, res.text

    failed = (
        await client.get(f"{BASE}/sessions/{created['id']}", headers=headers("regen_fail", token))
    ).json()
    assert failed["status"] == "failed"

    profile = await _profile(client, "regen_fail", token)
    assert profile["quota"]["used"] == 0
    assert profile["quota"]["remaining"] == 3

    monkeypatch.setattr(routes, "generate_for_session", original_generate)
    retry = await client.post(
        f"{BASE}/sessions/{created['id']}/retry",
        headers=headers("regen_fail", token),
    )
    assert retry.status_code == 202, retry.text
    profile = await _profile(client, "regen_fail", token)
    assert profile["quota"]["used"] == 1
    assert profile["quota"]["remaining"] == 2