"""章节地图与个人统计的组装层（不感知 HTTP）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .. import db
from ..config import get_settings
from .quota import snapshot as quota_snapshot
from .settlement import rank_for_exp, streak_days

try:  # Python 3.9+ 自带 zoneinfo；macOS 有系统时区数据
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - 极端环境回退到 UTC+8
    TZ = timezone(timedelta(hours=8))


def _local_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(TZ).date()


def _node_stars(answer: Optional[Dict[str, Any]]) -> int:
    if not answer:
        return 0
    if answer.get("is_correct"):
        return 3
    return 1 if float(answer.get("score") or 0) > 0 else 0


def _question_nodes(
    questions: List[Dict[str, Any]],
    answers: List[Dict[str, Any]],
    session: Dict[str, Any],
) -> List[Dict[str, Any]]:
    answer_map = {a["question_id"]: a for a in answers}
    total = len(questions)
    current_seq = int(session.get("current_seq") or 1)
    current_seq = max(1, min(current_seq, total or 1))
    status = session.get("status")
    completed = status == "completed"

    nodes: List[Dict[str, Any]] = []
    for question in questions:
        seq = int(question["seq"])
        answer = answer_map.get(question["id"])
        if completed:
            node_status = "done"
        elif status == "ready":
            if seq < current_seq:
                node_status = "done"
            elif seq == current_seq:
                node_status = "current"
            else:
                node_status = "locked"
        else:
            node_status = "current" if seq == 1 else "locked"

        nodes.append(
            {
                "seq": seq,
                "title": question.get("title") or f"第 {seq} 关",
                "kind": "question",
                "status": node_status,
                "stars": _node_stars(answer) if completed else 0,
                "score": round(float(answer.get("score") or 0), 2) if answer else 0.0,
                "is_correct": bool(answer.get("is_correct")) if answer else False,
                "question_id": question["id"],
            }
        )
    return nodes


def build_chapter_detail(chapter_id: str) -> Optional[Dict[str, Any]]:
    chapter = db.get_chapter(chapter_id)
    if not chapter:
        return None
    session = db.get_session(chapter["session_id"])
    if not session:
        return None
    questions = db.list_questions(session["id"])
    answers = db.list_answers(session["id"])
    nodes = _question_nodes(questions, answers, session)
    completed = session.get("status") == "completed"
    question_count = len(questions)
    kind = chapter.get("kind") or "standard"

    comprehensive_node: Optional[Dict[str, Any]] = None
    comprehensive_done = 0
    if kind == "standard":
        comp = db.get_comprehensive_chapter(chapter["id"])
        if comp:
            comp_session = db.get_session(comp["session_id"]) or {}
            comp_status = comp_session.get("status", "ready")
            if comp_status == "completed":
                comp_node_status = "done"
                comprehensive_done = 1
            elif comp_status in {"ready", "queued", "searching", "digesting", "generating"}:
                comp_node_status = "current"
            else:
                comp_node_status = "unlocked"
            comprehensive_node = {
                "seq": question_count + 1,
                "title": "章末 · 综合",
                "kind": "comprehensive",
                "status": comp_node_status,
                "stars": int(comp.get("stars") or 0),
                "score": 0.0,
                "is_correct": comp_status == "completed" and int(comp.get("stars") or 0) >= 3,
                "question_id": None,
                "chapter_id": comp["id"],
                "session_id": comp["session_id"],
            }
        else:
            all_three = bool(nodes) and all(node["stars"] >= 3 for node in nodes)
            comprehensive_node = {
                "seq": question_count + 1,
                "title": "章末 · 综合",
                "kind": "comprehensive",
                "status": "unlocked" if completed and all_three else "locked",
                "stars": 0,
                "score": 0.0,
                "is_correct": False,
                "question_id": None,
            }
        nodes.append(comprehensive_node)

    if completed:
        done = question_count + comprehensive_done
    elif session.get("status") == "ready":
        done = min(max(0, int(session.get("current_seq") or 1) - 1), question_count)
    else:
        done = 0

    current_node = 1
    for node in nodes:
        if node["status"] in {"current", "unlocked"}:
            current_node = node["seq"]
            break
    else:
        current_node = question_count or 1

    return {
        "id": chapter["id"],
        "session_id": chapter["session_id"],
        "parent_chapter_id": chapter.get("parent_chapter_id"),
        "title": chapter.get("title") or session.get("topic", ""),
        "topic": chapter.get("topic") or session.get("topic", ""),
        "level": chapter.get("level") or session.get("level", "basic"),
        "question_count": question_count,
        "kind": kind,
        "status": session.get("status"),
        "error": session.get("error"),
        "stars": int(chapter.get("stars") or 0),
        "accuracy": round(float(chapter.get("accuracy") or 0), 3),
        "exp": int(chapter.get("exp") or 0),
        "progress": {"done": done, "total": question_count + (1 if kind == "standard" else 0)},
        "current_node": current_node,
        "nodes": nodes,
        "comprehensive": comprehensive_node,
        "sources": session.get("sources") or [],
        "created_at": chapter.get("created_at"),
        "completed_at": chapter.get("completed_at") or session.get("completed_at"),
    }


def build_chapter_summary(chapter: Dict[str, Any]) -> Dict[str, Any]:
    detail = build_chapter_detail(chapter["id"])
    if detail is None:
        return {
            "id": chapter["id"],
            "session_id": chapter["session_id"],
            "title": chapter.get("title", ""),
            "topic": chapter.get("topic", ""),
            "level": chapter.get("level", "basic"),
            "question_count": int(chapter.get("question_count") or 0),
            "kind": chapter.get("kind", "standard"),
            "status": chapter.get("session_status"),
            "stars": int(chapter.get("stars") or 0),
            "accuracy": float(chapter.get("accuracy") or 0),
            "exp": int(chapter.get("exp") or 0),
            "progress": {"done": 0, "total": 0},
            "next_title": "",
            "created_at": chapter.get("created_at"),
            "completed_at": chapter.get("completed_at"),
        }
    nodes = detail["nodes"]
    next_node = next((n for n in nodes if n["status"] in {"current", "unlocked"}), None)
    return {
        "id": detail["id"],
        "session_id": detail["session_id"],
        "title": detail["title"],
        "topic": detail["topic"],
        "level": detail["level"],
        "question_count": detail["question_count"],
        "kind": detail["kind"],
        "status": detail["status"],
        "stars": detail["stars"],
        "accuracy": detail["accuracy"],
        "exp": detail["exp"],
        "progress": detail["progress"],
        "next_title": next_node["title"] if next_node else "",
        "created_at": detail["created_at"],
        "completed_at": detail["completed_at"],
    }


def list_chapter_summaries(
    client_id: str, limit: int = 10, user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    return [build_chapter_summary(c) for c in db.list_chapters(client_id, limit, user_id=user_id)]


def build_profile(client_id: str, user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    settings = get_settings()
    user_id = user["id"] if user else None
    completed = db.list_completed_sessions(client_id, user_id=user_id)
    total_exp = sum(int(s.get("exp") or 0) for s in completed)
    total_stars = sum(int(s.get("stars") or 0) for s in completed)

    dates = [d for d in (_local_date(s.get("completed_at") or s.get("created_at")) for s in completed) if d]
    today = datetime.now(TZ).date()
    streak = streak_days(dates, today)

    now = datetime.now(TZ)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = db.count_sessions_since(
        client_id,
        month_start.astimezone(timezone.utc).isoformat(timespec="seconds"),
        user_id=user_id,
    )

    weekly: List[Dict[str, Any]] = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        day_exp = sum(
            int(s.get("exp") or 0)
            for s in completed
            if _local_date(s.get("completed_at") or s.get("created_at")) == day
        )
        weekly.append({"date": day.isoformat(), "exp": day_exp})

    rank = rank_for_exp(total_exp)
    quota = quota_snapshot(user, client_id)
    user_settings = db.get_user_settings(user_id) if user_id else {"reminder_enabled": False}
    return {
        "client_id": client_id,
        "user_id": user_id,
        "nickname": (user or {}).get("nickname") or "旅人",
        "avatar_url": (user or {}).get("avatar_url"),
        "is_guest": user is None,
        "is_logged_in": user is not None,
        "wechat_bound": bool((user or {}).get("openid")),
        "chapters_completed": len(completed),
        "total_stars": total_stars,
        "total_exp": total_exp,
        "points": total_exp,
        "leaf_count": total_exp,
        "streak_days": streak,
        "rank": rank,
        "quota": quota,
        "settings": {"reminder_enabled": bool(user_settings.get("reminder_enabled"))},
        "weekly": weekly,
        "recent_chapters": list_chapter_summaries(client_id, 3, user_id=user_id),
        "monthly_used": used,
    }