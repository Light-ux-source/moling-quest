"""结算规则：星级、经验、连击、段位、连续学习。

这些函数是纯函数，便于单测，也保证前端展示与服务端一致。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Optional

RANKS: List[Dict[str, Any]] = [
    {"key": "S1", "label": "初入雾林", "min_exp": 0},
    {"key": "S2", "label": "苔径旅人", "min_exp": 100},
    {"key": "S3", "label": "青苔行者", "min_exp": 300},
    {"key": "S4", "label": "雾林向导", "min_exp": 500},
    {"key": "S5", "label": "守林人", "min_exp": 800},
    {"key": "S6", "label": "林间隐者", "min_exp": 1200},
]


def stars_for_accuracy(accuracy: float) -> int:
    """三星制：≥60% 一星、≥80% 二星、100% 三星。"""
    if accuracy >= 1.0:
        return 3
    if accuracy >= 0.8:
        return 2
    if accuracy >= 0.6:
        return 1
    return 0


def exp_for(correct: int, stars: int, daily_bonus: int = 0) -> int:
    """经验 = 答对题数 × 20 + 星级 × 20 + 每日挑战奖励。"""
    return int(correct) * 20 + int(stars) * 20 + int(daily_bonus)


def combo_for(flags: Iterable[bool]) -> int:
    longest = current = 0
    for flag in flags:
        if flag:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def rank_for_exp(exp: int) -> Dict[str, Any]:
    exp = max(0, int(exp))
    current = RANKS[0]
    next_rank: Optional[Dict[str, Any]] = None
    for index, rank in enumerate(RANKS):
        if exp >= rank["min_exp"]:
            current = rank
            next_rank = RANKS[index + 1] if index + 1 < len(RANKS) else None
        else:
            break

    if next_rank:
        span = max(1, next_rank["min_exp"] - current["min_exp"])
        progress = round((exp - current["min_exp"]) / span * 100)
        exp_to_next = max(0, next_rank["min_exp"] - exp)
    else:
        progress = 100
        exp_to_next = 0

    return {
        "key": current["key"],
        "label": current["label"],
        "exp": exp,
        "next_key": next_rank["key"] if next_rank else None,
        "next_label": next_rank["label"] if next_rank else None,
        "exp_to_next": exp_to_next,
        "progress_pct": min(100, max(0, progress)),
    }


def streak_days(days: Iterable[date], today: date) -> int:
    """从今天（或昨天）向前数连续学习天数。"""
    day_set = set(days)
    if not day_set:
        return 0
    cursor = today if today in day_set else date.fromordinal(today.toordinal() - 1)
    if cursor not in day_set:
        return 0
    count = 0
    while cursor in day_set:
        count += 1
        cursor = date.fromordinal(cursor.toordinal() - 1)
    return count


def build_settlement(
    session: Dict[str, Any],
    items: List[Dict[str, Any]],
    previous_exp: int,
    duration_sec: int,
) -> Dict[str, Any]:
    total = len(items)
    correct = sum(1 for item in items if item.get("is_correct"))
    accuracy = round(correct / total, 3) if total else 0.0
    stars = stars_for_accuracy(accuracy)
    combo = combo_for(bool(item.get("is_correct")) for item in items)
    daily_bonus = 30 if session.get("kind") == "daily" and accuracy >= 1.0 else 0
    exp = exp_for(correct, stars, daily_bonus)
    rank_before = rank_for_exp(previous_exp)
    rank_after = rank_for_exp(previous_exp + exp)
    return {
        "session_id": session["id"],
        "chapter_id": session.get("chapter_id"),
        "stars": stars,
        "accuracy": accuracy,
        "correct": correct,
        "total": total,
        "exp": exp,
        "combo": combo,
        "wrong_count": total - correct,
        "duration_sec": int(duration_sec or 0),
        "rank_before": rank_before,
        "rank_after": rank_after,
        "level_up": rank_after["key"] != rank_before["key"],
        "exp_to_next": rank_after["exp_to_next"],
    }