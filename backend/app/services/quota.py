"""配额：游客试用 1 组；登录用户 3 组/日；失败返还；重试不重复扣。"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, Optional

from .. import db
from ..config import get_settings

try:  # Python 3.9+
    from zoneinfo import ZoneInfo

    def _tz():
        return ZoneInfo(get_settings().quota_timezone)

except Exception:  # pragma: no cover - 极端环境回退 UTC+8
    def _tz():
        return timezone(timedelta(hours=8))


class QuotaError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def day_start_utc(now: Optional[datetime] = None) -> str:
    current = (now or _now()).astimezone(_tz())
    start = datetime.combine(current.date(), time.min, tzinfo=_tz())
    return start.astimezone(timezone.utc).isoformat(timespec="seconds")


def next_reset_utc(now: Optional[datetime] = None) -> str:
    current = (now or _now()).astimezone(_tz())
    tomorrow = datetime.combine(current.date() + timedelta(days=1), time.min, tzinfo=_tz())
    return tomorrow.astimezone(timezone.utc).isoformat(timespec="seconds")


def snapshot(user: Optional[Dict[str, Any]], client_id: str) -> Dict[str, Any]:
    settings = get_settings()
    if user:
        used = db.count_sessions_for_quota(user["id"], None, day_start_utc())
        limit = settings.daily_quota_user
        return {
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "period": "day",
            "source": "daily",
            "reset_at": next_reset_utc(),
            "is_guest": False,
        }
    limit = max(0, int(settings.guest_trial_limit))
    used = 1 if limit > 0 and db.guest_trial_used(client_id) else 0
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "period": "trial",
        "source": "guest_trial",
        "reset_at": None,
        "is_guest": True,
    }


def ensure_can_create(user: Optional[Dict[str, Any]], client_id: str) -> Dict[str, Any]:
    settings = get_settings()
    quota = snapshot(user, client_id)
    if not settings.quota_enforced or quota["remaining"] > 0:
        return quota
    if user:
        raise QuotaError(
            f"今天的 {quota['limit']} 组已经用完，明天 00:00 恢复。"
            "先去复习一下已学的内容吧。"
        )
    raise QuotaError("已体验 1 组。登录后可继续造关，学习记录也会跟着账号走。")


def refund_failure(session: Dict[str, Any]) -> None:
    """整组最终失败：返还额度（游客退回试用，登录用户标记不计数）。"""
    if not session:
        return
    if session.get("guest_trial"):
        db.refund_guest_trial(session.get("client_id") or "anonymous", session["id"])
    else:
        db.set_quota_refunded(session["id"], True)


def reset_retry(session_id: str) -> None:
    """失败重试：重新计入一次；若再次失败会再次返还。"""
    db.set_quota_refunded(session_id, False)