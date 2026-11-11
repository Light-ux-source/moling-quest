"""配额：游客 1 组、登录 3 组/日、失败返还、重试不重复扣。"""

from __future__ import annotations

import pytest

from app import db
from app.api import routes
from app.config import get_settings
from app.services import quota
from tests.helpers import BASE, create_ready, dev_login, headers


def _enable(monkeypatch, *, guest=1, daily=3):
    settings = get_settings()
    monkeypatch.setattr(settings, "quota_enforced", True)
    monkeypatch.setattr(settings, "guest_trial_limit", guest)
    monkeypatch.setattr(settings, "daily_quota_user", daily)


@pytest.mark.asyncio
async def test_guest_can_only_use_one_trial(client, monkeypatch):
    _enable(monkeypatch)
    created, _ = await create_ready(client, "quota_guest")
    assert created["id"]

    second = await client.post(
        f"{BASE}/sessions",
        json={"topic": "第二组", "level": "basic", "question_count": 3},
        headers=headers("quota_guest"),
    )
    assert second.status_code == 429
    assert "登录" in second.json()["detail"]

    profile = (await client.get(f"{BASE}/profile", headers=headers("quota_guest"))).json()
    assert profile["is_guest"] is True
    assert profile["quota"]["used"] == 1
    assert profile["quota"]["limit"] == 1
    assert profile["quota"]["period"] == "trial"


@pytest.mark.asyncio
async def test_guest_failure_refunds_trial_and_allows_retry(client, monkeypatch):
    _enable(monkeypatch)

    async def fail(session_id: str) -> None:
        session = db.get_session(session_id)
        db.update_session(session_id, status="failed", stage="failed", progress=100, error="boom")
        quota.refund_failure(session or {})

    monkeypatch.setattr(routes, "generate_for_session", fail)
    first = await client.post(
        f"{BASE}/sessions",
        json={"topic": "会失败的组", "level": "basic", "question_count": 3},
        headers=headers("quota_guest_fail"),
    )
    assert first.status_code == 202
    session_id = first.json()["id"]
    detail = (
        await client.get(f"{BASE}/sessions/{session_id}", headers=headers("quota_guest_fail"))
    ).json()
    assert detail["status"] == "failed"

    # 失败已退回试用：可以重新创建一组
    retry = await client.post(
        f"{BASE}/sessions/{session_id}/retry",
        headers=headers("quota_guest_fail"),
    )
    assert retry.status_code == 202, retry.text


@pytest.mark.asyncio
async def test_logged_in_user_has_three_groups_per_day_and_resets(client, monkeypatch):
    _enable(monkeypatch, guest=1, daily=3)
    token, user = await dev_login(client, "quota_user")

    created_ids = []
    for index in range(3):
        created, _ = await create_ready(
            client, "quota_user", token, topic=f"主题 {index}"
        )
        created_ids.append(created["id"])

    fourth = await client.post(
        f"{BASE}/sessions",
        json={"topic": "第四组", "level": "basic", "question_count": 3},
        headers=headers("quota_user", token),
    )
    assert fourth.status_code == 429
    assert "3 组" in fourth.json()["detail"]

    profile = (await client.get(f"{BASE}/profile", headers=headers("quota_user", token))).json()
    assert profile["quota"] == {
        "used": 3,
        "limit": 3,
        "remaining": 0,
        "period": "day",
        "source": "daily",
        "reset_at": profile["quota"]["reset_at"],
        "is_guest": False,
    }
    assert profile["quota"]["reset_at"]

    # 把所有会话移到昨天，模拟跨日重置
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET created_at = %s WHERE user_id = %s",
                ("2000-01-01T00:00:00+00:00", user["id"]),
            )
    profile = (await client.get(f"{BASE}/profile", headers=headers("quota_user", token))).json()
    assert profile["quota"]["used"] == 0
    assert profile["quota"]["remaining"] == 3

    again, _ = await create_ready(client, "quota_user", token, topic="跨日后主题")
    assert again["id"] in created_ids or again["id"]


@pytest.mark.asyncio
async def test_guest_trial_is_not_counted_against_daily_quota_after_login(client, monkeypatch):
    _enable(monkeypatch, guest=1, daily=3)
    guest, _ = await create_ready(client, "quota_migrate")
    assert guest["id"]

    token, user = await dev_login(client, "quota_migrate")
    profile = (await client.get(f"{BASE}/profile", headers=headers("quota_migrate", token))).json()
    assert profile["is_logged_in"] is True
    assert profile["quota"]["used"] == 0
    assert profile["quota"]["limit"] == 3

    records = (
        await client.get(f"{BASE}/records?limit=20", headers=headers("quota_migrate", token))
    ).json()
    assert records["total"] == 1
    assert records["items"][0]["id"] == guest["id"]


@pytest.mark.asyncio
async def test_user_failure_refund_and_retry_does_not_double_count(client, monkeypatch):
    _enable(monkeypatch, guest=1, daily=3)
    token, _ = await dev_login(client, "quota_retry")
    created, _ = await create_ready(client, "quota_retry", token, topic="会失败的登录组")
    session = db.get_session(created["id"])
    db.update_session(created["id"], status="failed", error="boom")
    quota.refund_failure(session or {})

    profile = (await client.get(f"{BASE}/profile", headers=headers("quota_retry", token))).json()
    assert profile["quota"]["used"] == 0

    retry = await client.post(
        f"{BASE}/sessions/{created['id']}/retry",
        headers=headers("quota_retry", token),
    )
    assert retry.status_code == 202, retry.text
    profile = (await client.get(f"{BASE}/profile", headers=headers("quota_retry", token))).json()
    assert profile["quota"]["used"] == 1