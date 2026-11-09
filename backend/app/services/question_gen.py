"""出题阶段：检索 → 知识提纲 → 结构化题目 → 校验入库。"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Iterable, List, Optional

from .. import db
from ..config import get_settings
from ..llm import LLMError, get_llm
from ..prompts import LEVEL_GUIDE, TYPE_RULES
from ..schemas import TYPE_LABELS, QuestionFull
from ..search import get_search
from ..utils import letters as _letters

logger = logging.getLogger(__name__)

OBJECTIVE_TYPES = {"single_choice", "multiple_choice", "true_false"}


def normalize_question(
    raw: Dict[str, Any],
    *,
    seq: int,
    session_id: str,
    allowed_urls: Iterable[str],
) -> Optional[Dict[str, Any]]:
    """把模型输出规范成可信的题目结构；不合法直接丢弃（宁缺毋滥）。"""
    qtype = str(raw.get("type") or "").strip()
    stem = str(raw.get("stem") or "").strip()
    if qtype not in TYPE_LABELS or len(stem) < 6:
        return None

    options: List[Dict[str, str]] = []
    if qtype in OBJECTIVE_TYPES:
        raw_options = raw.get("options") or []
        seen_keys = set()
        for opt in raw_options:
            key = str((opt or {}).get("key") or "").strip().upper()[:1]
            text = str((opt or {}).get("text") or "").strip()
            if not key or not text or key in seen_keys:
                continue
            seen_keys.add(key)
            options.append({"key": key, "text": text[:200]})
        if qtype == "true_false":
            options = [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
        if len(options) < 2:
            return None
        option_keys = {o["key"] for o in options}
    else:
        option_keys = set()

    correct = raw.get("correct_answer")
    if qtype == "single_choice":
        letters = _letters(correct)
        if len(letters) != 1 or letters[0] not in option_keys:
            return None
        correct = letters[0]
    elif qtype == "true_false":
        letters = _letters(correct)
        if not letters or letters[0] not in {"A", "B"}:
            return None
        correct = letters[0]
    elif qtype == "multiple_choice":
        letters = _letters(correct)
        if len(letters) < 2 or not set(letters).issubset(option_keys):
            return None
        correct = sorted(set(letters))
    else:  # short_answer
        if isinstance(correct, str):
            points = [p.strip() for p in correct.replace("；", "\n").split("\n") if p.strip()]
        elif isinstance(correct, (list, tuple)):
            points = [str(p).strip() for p in correct if str(p).strip()]
        else:
            points = []
        if len(points) < 2:
            return None
        correct = points[:6]

    rubric = raw.get("rubric") or []
    rubric_list = [str(r).strip() for r in rubric if str(r).strip()][:6] if isinstance(rubric, (list, tuple)) else []

    allowed = {u for u in allowed_urls if u}
    refs = []
    for ref in raw.get("source_refs") or []:
        ref = str(ref).strip()
        if ref and ref in allowed and ref not in refs:
            refs.append(ref)

    difficulty = str(raw.get("difficulty") or "medium").strip().lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"

    title = str(raw.get("title") or "").strip()[:24]
    if not title:
        title = stem[:12]
    knowledge_point = str(raw.get("knowledge_point") or "").strip()[:40] or title

    return {
        "id": f"q_{session_id[-6:]}_{seq}_{uuid.uuid4().hex[:4]}",
        "seq": seq,
        "type": qtype,
        "title": title,
        "knowledge_point": knowledge_point,
        "stem": stem[:600],
        "options": options,
        "correct_answer": correct,
        "explanation": str(raw.get("explanation") or "").strip()[:800],
        "difficulty": difficulty,
        "rubric": rubric_list,
        "source_refs": refs,
    }


def validate_questions(
    raw_questions: Any,
    *,
    session_id: str,
    count: int,
    allowed_types: List[str],
    allowed_urls: Iterable[str],
) -> List[Dict[str, Any]]:
    if not isinstance(raw_questions, list):
        raise LLMError("模型未返回 questions 数组")

    out: List[Dict[str, Any]] = []
    seen_stems: set = set()
    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("type") or "").strip() not in allowed_types:
            continue
        question = normalize_question(
            raw, seq=len(out) + 1, session_id=session_id, allowed_urls=allowed_urls
        )
        if question is None:
            continue
        fingerprint = "".join(question["stem"].split()).lower()
        if fingerprint in seen_stems:
            continue
        seen_stems.add(fingerprint)
        out.append(question)
        if len(out) >= count:
            break

    out = _validate_with_schema(out)
    if not out:
        raise LLMError("生成的题目全部未通过校验")
    return out


def _validate_with_schema(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """用 Pydantic 再校验一次，确保入库结构稳定。"""
    valid: List[Dict[str, Any]] = []
    for item in items:
        try:
            model = QuestionFull(**item)
        except Exception as exc:  # noqa: BLE001 - 校验失败即丢弃
            logger.info("题目校验失败, 丢弃: %s", exc)
            continue
        valid.append(model.model_dump())
    return valid


def _format_source_text(sources: List[Any]) -> str:
    return "\n".join(
        f"[{i + 1}] {s.title or ''}（{s.site_name or '未知站点'}）\n{s.summary or ''}"
        for i, s in enumerate(sources[:8])
    ) or "（本次没有检索到外部资料，请基于你已有的可靠知识作答，并在 evidence 中标注「模型知识」。）"


async def build_knowledge_brief(topic: str, level: str, sources: List[Any]) -> Dict[str, Any]:
    llm = get_llm()
    result = await llm.run(
        "digest",
        {
            "topic": topic,
            "level_guide": LEVEL_GUIDE.get(level, LEVEL_GUIDE["basic"]),
            "source_text": _format_source_text(sources),
        },
        context={"topic": topic, "sources": [s.model_dump() for s in sources]},
        temperature=0.2,
        max_tokens=1600,
    )
    return {"data": result.data, "usage": result}


async def generate_for_session(session_id: str) -> None:
    """后台任务：生成题目并落库。任何异常都要把 session 置为 failed。"""
    session = db.get_session(session_id)
    if not session:
        return
    settings = get_settings()
    topic = session["topic"]
    level = session["level"]
    count = int(session["question_count"])
    requested = session["requested_types"] or ["single_choice", "multiple_choice", "true_false", "short_answer"]
    allowed_types = [t for t in requested if t in TYPE_LABELS] or list(TYPE_LABELS)

    try:
        db.update_session(session_id, status="searching", stage="searching", progress=12)
        sources = []
        if settings.enable_web_search:
            try:
                sources = await get_search().search_many(topic, per_query=4)
            except Exception as exc:  # noqa: BLE001
                logger.warning("检索失败，降级为纯模型知识: %s", exc)
        db.update_session(
            session_id,
            status="digesting",
            stage="digesting",
            progress=40,
            sources=[s.model_dump() for s in sources],
        )

        llm = get_llm()
        brief_result = await build_knowledge_brief(topic, level, sources)
        brief = brief_result["data"]
        usage = brief_result["usage"]
        db.add_usage(session_id, usage.tokens_in, usage.tokens_out, usage.cost_cny)
        db.update_session(
            session_id,
            knowledge_brief=brief,
            status="generating",
            stage="generating",
            progress=68,
        )

        type_desc = "、".join(TYPE_LABELS.get(t, t) for t in allowed_types)
        source_urls = [s.url for s in sources if s.url]
        url_hint = "、".join(source_urls[:5]) if source_urls else "（无可用链接，source_refs 留空数组）"
        gen_result = await llm.run(
            "generate",
            {
                "topic": topic,
                "count": count,
                "level_guide": LEVEL_GUIDE.get(level, LEVEL_GUIDE["basic"]),
                "type_desc": type_desc,
                "type_rules": TYPE_RULES,
                "brief_json": json.dumps(brief, ensure_ascii=False, indent=2),
                "url_hint": url_hint,
            },
            context={
                "topic": topic,
                "count": count,
                "types": allowed_types,
                "brief": brief,
            },
            temperature=0.7,
            max_tokens=4000,
        )
        db.add_usage(session_id, gen_result.tokens_in, gen_result.tokens_out, gen_result.cost_cny)

        raw = gen_result.data.get("questions")
        questions = validate_questions(
            raw,
            session_id=session_id,
            count=count,
            allowed_types=allowed_types,
            allowed_urls=[s.url for s in sources],
        )
        db.insert_questions(session_id, questions)
        db.update_session(
            session_id,
            status="ready",
            stage="ready",
            progress=100,
            error=None,
            model=gen_result.model or usage.model,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("生成题目失败 session=%s", session_id)
        db.update_session(
            session_id,
            status="failed",
            stage="failed",
            progress=100,
            error=_friendly_error(exc),
        )


def _friendly_error(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, LLMError):
        if "余额不足" in message or "API Key 无效" in message:
            return message
        return f"AI 生成失败，请重试：{message[:120]}"
    if "timeout" in message.lower():
        return "AI 生成超时，请稍后重试"
    return "服务开小差了，请稍后重试"