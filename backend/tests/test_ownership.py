"""账号隔离：会话、报告、章节、记录不能跨用户读取。"""

from __future__ import annotations

import pytest

from tests.helpers import BASE, create_ready, dev_login, headers, submit_correct


@pytest.mark.asyncio
async def test_sessions_and_reports_are_owner_scoped(client):
    token_a, _ = await dev_login(client, "owner_a")
    token_b, _ = await dev_login(client, "owner_b")
    created, _ = await create_ready(client, "owner_a", token_a, topic="A 的会话")
    await submit_correct(client, "owner_a", created["id"], token_a)

    ok = await client.get(f"{BASE}/sessions/{created['id']}", headers=headers("owner_a", token_a))
    assert ok.status_code == 200

    other = await client.get(f"{BASE}/sessions/{created['id']}", headers=headers("owner_b", token_b))
    assert other.status_code == 404

    guest = await client.get(f"{BASE}/sessions/{created['id']}", headers=headers("owner_a"))
    assert guest.status_code == 404

    report_a = await client.get(
        f"{BASE}/sessions/{created['id']}/report", headers=headers("owner_a", token_a)
    )
    assert report_a.status_code == 200
    report_b = await client.get(
        f"{BASE}/sessions/{created['id']}/report", headers=headers("owner_b", token_b)
    )
    assert report_b.status_code == 404

    records_b = await client.get(f"{BASE}/records", headers=headers("owner_b", token_b))
    assert records_b.json()["total"] == 0


@pytest.mark.asyncio
async def test_chapters_are_owner_scoped(client):
    token_a, _ = await dev_login(client, "chapter_owner_a")
    token_b, _ = await dev_login(client, "chapter_owner_b")
    created, _ = await create_ready(client, "chapter_owner_a", token_a, topic="A 的章节")

    ok = await client.get(
        f"{BASE}/chapters/{created['chapter_id']}", headers=headers("chapter_owner_a", token_a)
    )
    assert ok.status_code == 200

    other = await client.get(
        f"{BASE}/chapters/{created['chapter_id']}", headers=headers("chapter_owner_b", token_b)
    )
    assert other.status_code == 404

    guest = await client.get(
        f"{BASE}/chapters/{created['chapter_id']}", headers=headers("chapter_owner_a")
    )
    assert guest.status_code == 404

    chapters = await client.get(f"{BASE}/chapters", headers=headers("chapter_owner_b", token_b))
    assert chapters.json()["items"] == []


@pytest.mark.asyncio
async def test_guest_session_claim_blocks_old_guest_access(client):
    created, _ = await create_ready(client, "claim_device", topic="迁移前的记录")
    token, user = await dev_login(client, "claim_device")

    claimed = await client.get(
        f"{BASE}/sessions/{created['id']}", headers=headers("claim_device", token)
    )
    assert claimed.status_code == 200

    # 退出/无令牌后，设备游客态不能再读已归属账号的数据
    guest = await client.get(f"{BASE}/sessions/{created['id']}", headers=headers("claim_device"))
    assert guest.status_code == 404

    # 另一个账号也读不到
    other_token, _ = await dev_login(client, "claim_other")
    other = await client.get(
        f"{BASE}/sessions/{created['id']}", headers=headers("claim_other", other_token)
    )
    assert other.status_code == 404

    # 幂等：再次登录不重复迁移
    token2, user2 = await dev_login(client, "claim_device")
    assert user2["id"] == user["id"]
    records = await client.get(f"{BASE}/records", headers=headers("claim_device", token2))
    assert records.json()["total"] == 1