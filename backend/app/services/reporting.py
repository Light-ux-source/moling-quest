"""报告阶段：确定性统计 + LLM 学习教练点评，LLM 失败时回退到规则文案。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from .. import db
from ..config import get_settings
from ..llm import LLMError, get_llm
from ..schemas import LEVEL_LABELS, TYPE_LABELS
from .settlement import build_settlement

logger = logging.getLogger(__name__)


def _duration_sec(session: Dict[str, Any]) -> int:
    start = session.get("submitted_at") or session.get("created_at")
    try:
        start_dt = datetime.fromisoformat(str(start))
    except (TypeError, ValueError):
        return 0
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - start_dt).total_seconds()))


def _build_items(
    questions: List[Dict[str, Any]], answers: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    answer_map = {a["question_id"]: a for a in answers}
    items: List[Dict[str, Any]] = []
    for q in questions:
        a = answer_map.get(q["id"], {})
        items.append(
            {
                "question_id": q["id"],
                "seq": q["seq"],
                "type": q["type"],
                "type_label": TYPE_LABELS.get(q["type"], q["type"]),
                "stem": q["stem"],
                "options": q["options"],
                "user_answer": a.get("user_answer", ""),
                "correct_answer": q["correct_answer"],
                "is_correct": bool(a.get("is_correct")),
                "score": float(a.get("score", 0) or 0),
                "feedback": a.get("feedback", ""),
                "explanation": q["explanation"],
                "rubric": q["rubric"],
                "source_refs": q["source_refs"],
            }
        )
    return items


def _stats(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(items)
    correct = sum(1 for i in items if i["is_correct"])
    accuracy = correct / total if total else 0.0
    by_type: Dict[str, Dict[str, int]] = {}
    for item in items:
        bucket = by_type.setdefault(item["type_label"], {"total": 0, "correct": 0})
        bucket["total"] += 1
        bucket["correct"] += 1 if item["is_correct"] else 0
    return {"total": total, "correct": correct, "accuracy": accuracy, "by_type": by_type}


def _fallback_narrative(
    topic: str, level: str, stats: Dict[str, Any], items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    accuracy = stats["accuracy"]
    wrong = [i for i in items if not i["is_correct"]]
    if accuracy >= 0.9:
        summary = f"「{topic}」这组题你答对了 {stats['correct']}/{stats['total']}，概念理解和应用都比较扎实，可以尝试更高难度或更偏实战的题目。"
        tag = "掌握扎实"
    elif accuracy >= 0.6:
        summary = f"「{topic}」这组题你答对了 {stats['correct']}/{stats['total']}，主干概念已经建立，但细节和边界条件还不稳定，错题值得逐条重看。"
        tag = "基础达标"
    else:
        summary = f"「{topic}」这组题你答对了 {stats['correct']}/{stats['total']}，说明基础概念还存在明显空缺，建议先回到解析重建框架，不要急着刷更多题。"
        tag = "建议重学"

    gaps = [f"第 {w['seq']} 题（{w['type_label']}）相关知识点掌握不牢" for w in wrong[:3]] or [
        f"{topic} 的细节仍需巩固"
    ]
    return {
        "summary": summary,
        "level_tag": tag,
        "knowledge_gaps": gaps,
        "next_steps": [
            "逐题对照解析，用自己的话复述一遍正确答案",
            "把错题涉及的概念整理成 3 条笔记",
            "隔天再练一组同主题题目，检验记忆留存",
        ],
        "suggested_topics": [f"{topic} 进阶", f"{topic} 常见误区", f"{topic} 实战案例"],
    }


async def build_and_save_report(session_id: str) -> Dict[str, Any]:
    settings = get_settings()
    session = db.get_session(session_id)
    if not session:
        raise RuntimeError("session 不存在")
    questions = db.list_questions(session_id)
    answers = db.list_answers(session_id)
    items = _build_items(questions, answers)
    stats = _stats(items)

    narrative = _fallback_narrative(session["topic"], session["level"], stats, items)
    model = session.get("model")
    try:
        compact_items = [
            {
                "seq": it["seq"],
                "type_label": it["type_label"],
                "stem": it["stem"][:120],
                "is_correct": it["is_correct"],
                "score": it["score"],
                "feedback": it.get("feedback", "")[:80],
            }
            for it in items
        ]
        result = await get_llm().run(
            "report",
            {
                "topic": session["topic"],
                "level": session["level"],
                "total": stats["total"],
                "correct": stats["correct"],
                "accuracy_pct": f"{stats['accuracy']:.0%}",
                "duration": _duration_sec(session),
                "items_json": json.dumps(compact_items, ensure_ascii=False),
            },
            context={
                "topic": session["topic"],
                "accuracy": stats["accuracy"],
                "wrong_topics": [i["stem"][:20] for i in items if not i["is_correct"]],
                "wrong_seqs": [
                    {"seq": i["seq"], "type_label": i["type_label"]}
                    for i in items
                    if not i["is_correct"]
                ],
            },
            temperature=0.4,
            max_tokens=1200,
        )
        db.add_usage(session_id, result.tokens_in, result.tokens_out, result.cost_cny)
        data = result.data
        for key in ("summary", "level_tag", "knowledge_gaps", "next_steps", "suggested_topics"):
            value = data.get(key)
            if key in ("summary", "level_tag") and isinstance(value, str) and value.strip():
                narrative[key] = value.strip()
            elif isinstance(value, (list, tuple)) and value:
                narrative[key] = [str(v).strip()[:80] for v in value][:4]
        model = result.model or model
    except LLMError as exc:
        logger.warning("报告 LLM 生成失败，使用规则文案: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("报告生成异常，使用规则文案: %s", exc)

    fresh = db.get_session(session_id) or session
    duration_sec = _duration_sec(fresh)
    client_id = fresh.get("client_id") or "anonymous"
    previous_exp = sum(
        int(item.get("exp") or 0)
        for item in db.list_completed_sessions(client_id)
        if item.get("id") != session_id
    )
    settlement = build_settlement(fresh, items, previous_exp, duration_sec)
    completed_at = db.now_iso()

    db.update_session(
        session_id,
        stars=settlement["stars"],
        exp=settlement["exp"],
        accuracy=settlement["accuracy"],
        combo=settlement["combo"],
        completed_at=completed_at,
    )
    if fresh.get("chapter_id"):
        db.update_chapter(
            fresh["chapter_id"],
            stars=settlement["stars"],
            accuracy=settlement["accuracy"],
            exp=settlement["exp"],
            completed_at=completed_at,
        )

    payload = {
        "session_id": session_id,
        "topic": session["topic"],
        "level": session["level"],
        "level_label": LEVEL_LABELS.get(session["level"], session["level"]),
        "score": int(round(stats["accuracy"] * 100)),
        "total": stats["total"],
        "correct": stats["correct"],
        "accuracy": round(stats["accuracy"], 3),
        "summary": narrative["summary"],
        "level_tag": narrative["level_tag"],
        "by_type": stats["by_type"],
        "items": items,
        "knowledge_gaps": narrative["knowledge_gaps"],
        "next_steps": narrative["next_steps"],
        "suggested_topics": narrative["suggested_topics"],
        "sources": session.get("sources") or [],
        "duration_sec": duration_sec,
        "generated_at": db.now_iso(),
        "model": model,
        "usage": {
            "tokens_in": fresh.get("tokens_in", 0),
            "tokens_out": fresh.get("tokens_out", 0),
            "cost_cny": round(float(fresh.get("cost_cny", 0) or 0), 4),
            "currency": "CNY",
            "note": "按高峰价保守估算，实际以账单为准" if not settings.is_mock else "mock 模式无真实消耗",
        },
        "settlement": settlement,
    }
    db.save_report(session_id, payload)
    return payload