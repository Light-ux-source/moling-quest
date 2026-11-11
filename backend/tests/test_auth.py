"""账号：体验登录、微信登录、令牌、退出与越权。"""

from __future__ import annotations

import pytest

from app import db
from app.config import get_settings
from app.services import auth as auth_service
from tests.helpers import BASE, dev_login, headers


@pytest.mark.asyncio
async def test_dev_login_creates_account_and_me(client):
    token, user = await dev_login(client, "auth_client_1", "阿墨")
    assert token
    assert user["id"].startswith("u_")
    assert user["nickname"] == "阿墨"
    assert user["wechat_bound"] is False

    me = await client.get(f"{BASE}/auth/me", headers=headers("auth_client_1", token))
    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    assert me.json()["user"]["id"] == user["id"]

    profile = await client.get(f"{BASE}/profile", headers=headers("auth_client_1", token))
    assert profile.status_code == 200
    body = profile.json()
    assert body["is_logged_in"] is True
    assert body["user_id"] == user["id"]
    assert body["nickname"] == "阿墨"
    assert body["quota"]["period"] == "day"


@pytest.mark.asyncio
async def test_dev_login_same_device_is_stable_different_device_is_new(client):
    token1, user1 = await dev_login(client, "auth_client_same")
    token2, user2 = await dev_login(client, "auth_client_same")
    assert user1["id"] == user2["id"]
    assert token1 != token2

    _, user3 = await dev_login(client, "auth_client_other")
    assert user3["id"] != user1["id"]


@pytest.mark.asyncio
async def test_wechat_login_maps_openid_and_is_idempotent(client, monkeypatch):
    async def fake_exchange(code: str):
        assert code == "code_ok"
        return {"openid": "openid_abc", "unionid": "union_abc", "session_key": "sk"}

    monkeypatch.setattr(auth_service, "wechat_exchange_code", fake_exchange)
    first = await client.post(
        f"{BASE}/auth/wechat",
        json={"code": "code_ok", "nickname": "微信旅人"},
        headers=headers("wx_client_1"),
    )
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["user"]["wechat_bound"] is True
    assert data["user"]["nickname"] == "微信旅人"

    second = await client.post(
        f"{BASE}/auth/wechat",
        json={"code": "code_ok"},
        headers=headers("wx_client_2"),
    )
    assert second.status_code == 200, second.text
    assert second.json()["user"]["id"] == data["user"]["id"]


@pytest.mark.asyncio
async def test_wechat_login_without_secret_returns_503(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "wechat_app_secret", "")
    res = await client.post(
        f"{BASE}/auth/wechat",
        json={"code": "code_ok"},
        headers=headers("wx_client_missing_secret"),
    )
    assert res.status_code == 503
    assert "AppSecret" in res.json()["detail"]


@pytest.mark.asyncio
async def test_dev_login_is_disabled_in_production(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "production")
    res = await client.post(f"{BASE}/auth/dev", json={}, headers=headers("prod_client"))
    assert res.status_code == 403
    assert "开发环境" in res.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_and_expired_tokens_are_rejected(client):
    bad = await client.get(
        f"{BASE}/profile", headers={"Authorization": "Bearer not-a-real-token", "X-Client-Id": "auth_bad"}
    )
    assert bad.status_code == 401

    token, _ = await dev_login(client, "auth_expired")
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE auth_tokens SET expires_at = %s WHERE user_id = (SELECT id FROM users LIMIT 1)",
                ("2000-01-01T00:00:00+00:00",),
            )
    expired = await client.get(f"{BASE}/profile", headers=headers("auth_expired", token))
    assert expired.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_token(client):
    token, _ = await dev_login(client, "auth_logout")
    res = await client.post(f"{BASE}/auth/logout", headers=headers("auth_logout", token))
    assert res.status_code == 200
    me = await client.get(f"{BASE}/auth/me", headers=headers("auth_logout", token))
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_me_without_token_is_guest(client):
    res = await client.get(f"{BASE}/auth/me", headers=headers("guest_me"))
    assert res.status_code == 200
    assert res.json()["authenticated"] is False
    assert res.json()["user"] is None

@pytest.mark.asyncio
async def test_wechat_exchange_uses_official_endpoint_and_params(client, monkeypatch):
    import httpx

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"openid": "openid_shape", "session_key": "sk"})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    class PatchedClient(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(auth_service.httpx, "AsyncClient", PatchedClient)
    res = await client.post(
        f"{BASE}/auth/wechat",
        json={"code": "the_code"},
        headers=headers("wx_shape"),
    )
    assert res.status_code == 200, res.text
    assert captured["url"].startswith("https://api.weixin.qq.com/sns/jscode2session?")
    assert captured["params"]["appid"] == get_settings().wechat_app_id
    assert captured["params"]["secret"] == get_settings().wechat_app_secret
    assert captured["params"]["js_code"] == "the_code"
    assert captured["params"]["grant_type"] == "authorization_code"


@pytest.mark.asyncio
async def test_login_rate_limit(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "login_rate_limit_per_hour", 1)
    first = await client.post(f"{BASE}/auth/dev", json={}, headers=headers("rate_client"))
    assert first.status_code == 200
    second = await client.post(f"{BASE}/auth/dev", json={}, headers=headers("rate_client"))
    assert second.status_code == 429
