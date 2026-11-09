"""判分阶段：客观题规则判分（快、稳定、零成本），简答题 LLM 按 rubric 判分。"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from .. import db
from ..llm import LLMError, get_llm
from ..utils import clamp, is_blank, letters, overlap_ratio

logger = logging.getLogger(__name__)

PASS_SCORE = 0.6


def grade_objective(question: Dict[str, Any], user_answer: Any) -> Dict[str, Any]:
    if is_blank(user_answer):
        return {"is_correct": False, "score": 0.0, "feedback": "本题未作答，建议先看解析。"}

    qtype = question["type"]
    correct = letters(question.get("correct_answer"))
    picked = letters(user_answer)

    if qtype == "multiple_choice":
        picked_set, correct_set = set(picked), set(correct)
        if picked_set == correct_set:
            return {"is_correct": True, "score": 1.0, "feedback": "全对，选项判断准确。"}
        if picked_set.issubset(correct_set):
            return {
                "is_correct": False,
                "score": round(0.5 * len(picked_set) / max(1, len(correct_set)), 2),
                "feedback": "漏选了正确项，多选题需要把握住每一个成立的条件。",
            }
        return {
            "is_correct": False,
            "score": 0.0,
            "feedback": "包含错误选项，说明对边界条件的判断还需要加强。",
        }

    if not picked:
        return {"is_correct": False, "score": 0.0, "feedback": "答案格式无法识别。"}
    ok = picked[0] == (correct[0] if correct else "")
    return {
        "is_correct": ok,
        "score": 1.0 if ok else 0.0,
        "feedback": "回答正确。" if ok else "选项有误，注意题干中的限定条件。",
    }


async def grade_short_answer(
    question: Dict[str, Any], user_answer: Any, level: str, topic: str
) -> Dict[str, Any]:
    answer_text = str(user_answer or "").strip()
    if is_blank(answer_text):
        return {
            "is_correct": False,
            "score": 0.0,
            "feedback": "本题未作答。建议先写「定义 → 机制 → 场景」三句话，再逐步补细节。",
        }

    rubric = question.get("rubric") or question.get("correct_answer") or []
    try:
        result = await get_llm().run(
            "grade",
            {
                "stem": question.get("stem", ""),
                "rubric_json": json.dumps(rubric, ensure_ascii=False),
                "correct_json": json.dumps(question.get("correct_answer"), ensure_ascii=False),
                "answer_json": json.dumps(answer_text, ensure_ascii=False),
                "level": level,
            },
            context={"topic": topic, "user_answer": answer_text, "rubric": rubric},
            temperature=0.1,
            max_tokens=800,
        )
        data = result.data
        score = clamp(float(data.get("score", 0) or 0), 0.0, 1.0)
        missing = data.get("missing_points") or []
        feedback = str(data.get("feedback") or "").strip()[:200]
        return {
            "is_correct": bool(data.get("correct", score >= PASS_SCORE)) and score >= PASS_SCORE,
            "score": round(score, 2),
            "feedback": feedback or ("要点覆盖较好。" if score >= PASS_SCORE else "要点覆盖不足，建议回看解析。"),
            "missing_points": [str(m).strip()[:60] for m in missing if str(m).strip()][:5]
            if isinstance(missing, (list, tuple))
            else [],
            "usage": {
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "cost_cny": result.cost_cny,
            },
        }
    except LLMError as exc:
        logger.warning("简答题 LLM 判分失败，降级为要点覆盖率: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("简答题判分异常，降级: %s", exc)

    ratio = overlap_ratio(answer_text, [str(p) for p in rubric])
    score = clamp(0.2 + ratio * 0.8, 0.0, 1.0) if ratio else 0.2
    return {
        "is_correct": score >= PASS_SCORE,
        "score": round(score, 2),
        "feedback": (
            "要点覆盖较完整（自动降级判分）。" if score >= PASS_SCORE
            else "答案与要点关联较弱，建议对照解析补充关键概念（自动降级判分）。"
        ),
        "missing_points": [],
        "usage": {"tokens_in": 0, "tokens_out": 0, "cost_cny": 0.0},
    }


async def run_grading(session_id: str) -> None:
    session = db.get_session(session_id)
    if not session:
        return
    questions = db.list_questions(session_id)
    stored = {a["question_id"]: a for a in db.list_answers(session_id)}

    results: List[Dict[str, Any]] = []
    tokens_in = tokens_out = 0
    cost = 0.0
    for question in questions:
        raw = stored.get(question["id"], {})
        user_answer = raw.get("user_answer", "")
        if question["type"] == "short_answer":
            graded = await grade_short_answer(
                {**question, "session_id": session_id}, user_answer, session["level"], session["topic"]
            )
        else:
            graded = grade_objective(question, user_answer)
        usage = graded.get("usage") or {}
        tokens_in += int(usage.get("tokens_in") or 0)
        tokens_out += int(usage.get("tokens_out") or 0)
        cost += float(usage.get("cost_cny") or 0)
        results.append(
            {
                "id": f"ans_{question['id']}",
                "question_id": question["id"],
                "seq": question["seq"],
                "user_answer": user_answer,
                "is_correct": graded["is_correct"],
                "score": graded["score"],
                "feedback": graded["feedback"],
            }
        )

    if tokens_in or tokens_out:
        db.add_usage(session_id, tokens_in, tokens_out, cost)
    db.upsert_answers(session_id, results)
    db.update_session(session_id, status="reporting", stage="reporting", progress=82)

    from .reporting import build_and_save_report

    await build_and_save_report(session_id)
    db.update_session(session_id, status="completed", stage="completed", progress=100, error=None)