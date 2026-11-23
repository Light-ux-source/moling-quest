"""账号与登录：微信 code2Session、开发体验登录、会话令牌、游客数据迁移。"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from .. import db
from ..config import get_settings

logger = logging.getLogger(__name__)

WECHAT_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean_nickname(value: Optional[str], fallback: str = "旅人") -> str:
    if value is None:
        return fallback
    cleaned = " ".join(str(value).replace("\u3000", " ").split())
    return cleaned[:16] or fallback


def _safe_avatar(value: Optional[str]) -> Optional[str]:
    """只接受服务端可访问的地址；微信临时路径不能直接入库。"""
    if not value:
        return None
    value = str(value).strip()
    if value.startswith("http://") or value.startswith("https://") or value.startswith("/media/"):
        return value[:512]
    return None


def identity_hash_for_identity(kind: str, value: str) -> str:
    """不可逆身份哈希：只用于注销冷却/防重复注册，不落原始 openid。"""
    settings = get_settings()
    pepper = (settings.identity_pepper or settings.wechat_app_secret or settings.app_name).encode("utf-8")
    return hmac.new(pepper, f"{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def identity_hash_for_user(user: Optional[Dict[str, Any]]) -> Optional[str]:
    if not user:
        return None
    openid = user.get("openid")
    if openid:
        return identity_hash_for_identity("wechat", str(openid))
    dev_key = user.get("dev_key")
    if dev_key:
        return identity_hash_for_identity("dev", str(dev_key))
    return None


def clear_expired_deletions() -> int:
    """清理已过冷却期的注销身份哈希（登录/启动时调用）。"""
    settings = get_settings()
    hours = max(0, int(settings.account_delete_cooldown_hours))
    cutoff = (_now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    return db.clear_expired_deletion_hashes(cutoff)


def _assert_not_in_delete_cooldown(identity_hash: Optional[str]) -> None:
    """注销后冷却期内禁止同一微信/体验身份重新注册。"""
    if not identity_hash:
        return
    deleted = db.get_deleted_user_by_identity(identity_hash)
    if not deleted:
        return
    settings = get_settings()
    hours = max(0, int(settings.account_delete_cooldown_hours))
    if hours <= 0:
        db.update_user(deleted["id"], identity_hash=None)
        return

    deleted_at = deleted.get("deleted_at")
    elapsed: Optional[timedelta] = None
    if deleted_at:
        try:
            parsed = datetime.fromisoformat(str(deleted_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            elapsed = _now() - parsed
        except ValueError:
            elapsed = None

    if elapsed is not None and elapsed >= timedelta(hours=hours):
        # 冷却期已过，清除旧身份哈希，允许创建全新账号
        db.update_user(deleted["id"], identity_hash=None)
        return

    raise AuthError(f"该账号刚注销，{hours} 小时后才能重新注册", 403)


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": user["id"],
        "nickname": user.get("nickname") or "旅人",
        "avatar_url": user.get("avatar_url"),
        "wechat_bound": bool(user.get("openid")),
        "is_guest": False,
    }


def issue_token(user_id: str) -> Dict[str, Any]:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(days=settings.auth_token_ttl_days)
    db.create_auth_token(
        {
            "id": f"at_{uuid.uuid4().hex[:16]}",
            "user_id": user_id,
            "token_hash": _hash_token(token),
            "created_at": now.isoformat(timespec="seconds"),
            "expires_at": expires.isoformat(timespec="seconds"),
        }
    )
    return {"token": token, "expires_at": expires.isoformat(timespec="seconds")}


def authenticate_token(token: str) -> Dict[str, Any]:
    if not token:
        raise AuthError("请先登录", 401)
    user = db.get_user_by_token_hash(_hash_token(token), _now().isoformat(timespec="seconds"))
    if not user:
        raise AuthError("登录已过期，请重新登录", 401)
    return user


def logout(token: str) -> None:
    if token:
        db.revoke_auth_token(_hash_token(token))


async def wechat_exchange_code(code: str) -> Dict[str, Any]:
    settings = get_settings()
    if not settings.wechat_login_configured:
        logger.warning("微信登录未配置：缺少 WECHAT_APP_ID 或 WECHAT_APP_SECRET")
        raise AuthError("微信登录暂不可用：服务端尚未配置 AppSecret", 503)
    params = {
        "appid": settings.wechat_app_id.strip(),
        "secret": settings.wechat_app_secret.strip(),
        "js_code": code,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(WECHAT_CODE2SESSION_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("微信 code2Session 请求失败: %s", exc)
        raise AuthError("微信登录服务暂时不可用，请稍后再试", 502) from exc
    except ValueError as exc:
        logger.warning("微信 code2Session 返回非 JSON: %s", exc)
        raise AuthError("微信登录返回异常，请重试", 502) from exc

    errcode = int(data.get("errcode") or 0)
    if errcode:
        message = str(data.get("errmsg") or "")
        mapping = {
            40029: "登录凭证无效，请重试",
            40163: "登录凭证已使用，请重试",
            45011: "登录太频繁，请稍后再试",
            -1: "微信服务繁忙，请稍后再试",
        }
        status = 429 if errcode == 45011 else 400
        raise AuthError(mapping.get(errcode, f"微信登录失败（{errcode}）"), status)
    if not data.get("openid"):
        raise AuthError("微信登录未返回用户标识，请重试", 502)
    return data


async def login_with_wechat(
    code: str,
    client_id: str,
    nickname: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> Dict[str, Any]:
    clear_expired_deletions()
    data = await wechat_exchange_code(code)
    openid = str(data["openid"])
    unionid = str(data["unionid"]) if data.get("unionid") else None
    identity_hash = identity_hash_for_identity("wechat", openid)

    user = db.get_user_by_openid(openid)
    is_new = user is None
    if is_new:
        _assert_not_in_delete_cooldown(identity_hash)
    if not user:
        user_id = f"u_{uuid.uuid4().hex[:16]}"
        db.create_user(
            {
                "id": user_id,
                "openid": openid,
                "unionid": unionid,
                "identity_hash": identity_hash,
                "nickname": _clean_nickname(nickname, "旅人"),
                "avatar_url": _safe_avatar(avatar_url),
            }
        )
        user = db.get_user(user_id)
    else:
        fields: Dict[str, Any] = {}
        if unionid and not user.get("unionid"):
            fields["unionid"] = unionid
        if nickname:
            fields["nickname"] = _clean_nickname(nickname, user.get("nickname") or "旅人")
        if avatar_url and not user.get("avatar_url"):
            fields["avatar_url"] = _safe_avatar(avatar_url)
        if user.get("identity_hash") != identity_hash:
            fields["identity_hash"] = identity_hash
        if fields:
            db.update_user(user["id"], **fields)
        db.touch_user_login(user["id"])
        user = db.get_user(user["id"]) or user

    if not user:
        raise AuthError("账号创建失败，请重试", 500)
    migrated = db.claim_guest_data(client_id, user["id"])
    token_data = issue_token(user["id"])
    return {
        "token": token_data["token"],
        "expires_at": token_data["expires_at"],
        "user": public_user(user),
        "migrated": migrated,
        "is_new": is_new,
    }


def login_dev(client_id: str, nickname: Optional[str] = None) -> Dict[str, Any]:
    settings = get_settings()
    if not settings.dev_login_allowed:
        raise AuthError("体验登录仅在开发环境可用", 403)
    clear_expired_deletions()
    dev_key = f"dev:{client_id}"
    identity_hash = identity_hash_for_identity("dev", dev_key)

    user = db.get_user_by_dev_key(dev_key)
    is_new = user is None
    if is_new:
        _assert_not_in_delete_cooldown(identity_hash)
    if not user:
        user_id = f"u_{uuid.uuid4().hex[:16]}"
        db.create_user(
            {
                "id": user_id,
                "dev_key": dev_key,
                "identity_hash": identity_hash,
                "nickname": _clean_nickname(nickname, "体验旅人"),
                "avatar_url": None,
            }
        )
        user = db.get_user(user_id)
    else:
        fields: Dict[str, Any] = {}
        if nickname:
            fields["nickname"] = _clean_nickname(nickname, user["nickname"])
        if user.get("identity_hash") != identity_hash:
            fields["identity_hash"] = identity_hash
        if fields:
            db.update_user(user["id"], **fields)
        db.touch_user_login(user["id"])
        user = db.get_user(user["id"]) or user
    if not user:
        raise AuthError("体验账号创建失败，请重试", 500)
    migrated = db.claim_guest_data(client_id, user["id"])
    token_data = issue_token(user["id"])
    return {
        "token": token_data["token"],
        "expires_at": token_data["expires_at"],
        "user": public_user(user),
        "migrated": migrated,
        "is_new": is_new,
    }
