"""个人中心、资料、头像、设置、记录列表与注销。"""

from __future__ import annotations

import pytest

from app import db
from app.config import get_settings
from tests.helpers import BASE, create_ready, dev_login, headers, submit_correct

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000100ffff03000006000557bfabd40000000049454e44ae426082"
)


@pytest.mark.asyncio
async def test_guest_profile_has_default_identity_and_trial_quota(client):
    res = await client.get(f"{BASE}/profile", headers=headers("profile_guest"))
    assert res.status_code == 200
    body = res.json()
    assert body["is_guest"] is True
    assert body["is_logged_in"] is False
    assert body["nickname"] == "旅人"
    assert body["points"] == 0
    assert body["quota"]["period"] == "trial"
    assert body["settings"]["reminder_enabled"] is False


@pytest.mark.asyncio
async def test_update_nickname_and_settings(client):
    token, _ = await dev_login(client, "profile_update", "旅人")
    res = await client.patch(
        f"{BASE}/profile",
        json={"nickname": "雾林阿墨"},
        headers=headers("profile_update", token),
    )
    assert res.status_code == 200, res.text
    assert res.json()["nickname"] == "雾林阿墨"

    settings = await client.get(
        f"{BASE}/profile/settings", headers=headers("profile_update", token)
    )
    assert settings.status_code == 200
    assert settings.json()["reminder_enabled"] is False

    updated = await client.patch(
        f"{BASE}/profile/settings",
        json={"reminder_enabled": True},
        headers=headers("profile_update", token),
    )
    assert updated.status_code == 200
    assert updated.json()["reminder_enabled"] is True

    profile = await client.get(f"{BASE}/profile", headers=headers("profile_update", token))
    assert profile.json()["settings"]["reminder_enabled"] is True


@pytest.mark.asyncio
async def test_avatar_upload_and_reject_invalid(client):
    token, _ = await dev_login(client, "profile_avatar")
    res = await client.post(
        f"{BASE}/profile/avatar",
        files={"file": ("avatar.png", PNG_1X1, "image/png")},
        headers=headers("profile_avatar", token),
    )
    assert res.status_code == 200, res.text
    url = res.json()["avatar_url"]
    assert url.startswith("/media/avatars/")

    image = await client.get(url)
    assert image.status_code == 200

    bad = await client.post(
        f"{BASE}/profile/avatar",
        files={"file": ("avatar.txt", b"hello", "text/plain")},
        headers=headers("profile_avatar", token),
    )
    assert bad.status_code == 422

    too_big = await client.post(
        f"{BASE}/profile/avatar",
        files={"file": ("huge.png", b"x" * (get_settings().avatar_max_bytes + 1), "image/png")},
        headers=headers("profile_avatar", token),
    )
    assert too_big.status_code == 422


@pytest.mark.asyncio
async def test_records_list_only_and_points(client):
    token, _ = await dev_login(client, "profile_records")
    first, _ = await create_ready(client, "profile_records", token, topic="记录一")
    await submit_correct(client, "profile_records", first["id"], token)
    await create_ready(client, "profile_records", token, topic="记录二")

    res = await client.get(
        f"{BASE}/records?limit=1&offset=0", headers=headers("profile_records", token)
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["has_more"] is True
    item = body["items"][0]
    assert item["topic"] in {"记录一", "记录二"}
    assert item["status"] in {"completed", "ready"}
    assert "points" in item
    assert "status_label" in item

    page2 = await client.get(
        f"{BASE}/records?limit=1&offset=1", headers=headers("profile_records", token)
    )
    assert page2.json()["total"] == 2
    assert page2.json()["has_more"] is False

    profile_res = await client.get(f"{BASE}/profile", headers=headers("profile_records", token))
    profile = profile_res.json()
    completed = [i for i in body["items"] if i["status"] == "completed"]
    if completed:
        assert profile["points"] >= completed[0]["points"]


@pytest.mark.asyncio
async def test_records_are_scoped_by_guest_client(client):
    await create_ready(client, "records_guest_a", topic="A 的记录")
    await create_ready(client, "records_guest_b", topic="B 的记录")
    a = (await client.get(f"{BASE}/records", headers=headers("records_guest_a"))).json()
    b = (await client.get(f"{BASE}/records", headers=headers("records_guest_b"))).json()
    assert a["total"] == 1
    assert b["total"] == 1
    assert a["items"][0]["topic"] == "A 的记录"
    assert b["items"][0]["topic"] == "B 的记录"


@pytest.mark.asyncio
async def test_delete_account_anonymizes_and_requires_new_login(client):
    token, user = await dev_login(client, "profile_delete", "要注销的人")
    await create_ready(client, "profile_delete", token, topic="注销前的记录")

    res = await client.delete(f"{BASE}/profile", headers=headers("profile_delete", token))
    assert res.status_code == 204

    me = await client.get(f"{BASE}/auth/me", headers=headers("profile_delete", token))
    assert me.status_code == 401

    guest_profile = await client.get(f"{BASE}/profile", headers=headers("profile_delete"))
    assert guest_profile.json()["is_guest"] is True

    new_token, new_user = await dev_login(client, "profile_delete")
    assert new_user["id"] != user["id"]
    records = await client.get(f"{BASE}/records", headers=headers("profile_delete", new_token))
    assert records.json()["total"] == 0