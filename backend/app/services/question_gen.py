"""出题阶段：检索 → 知识提纲 → 结构化题目 → 校验入库。"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, Iterable, List, Optional

from .. import db
from ..config import get_settings
from ..llm import LLMError, get_llm
from ..prompts import LEVEL_GUIDE, TYPE_RULES
from ..rag.retriever import (
    RagError,
    build_source_items,
    format_kb_evidence,
    format_web_evidence,
    retrieve,
)
from ..schemas import TYPE_LABELS, QuestionFull
from ..search import get_search
from ..utils import letters as _letters
from . import kb as kb_service
from .quota import refund_failure

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

    allowed_list = [str(u).strip() for u in allowed_urls if str(u).strip()]
    allowed = set(allowed_list)
    refs = []
    for raw_ref in raw.get("source_refs") or []:
        ref = str(raw_ref).strip()
        # 模型有时会输出 [K1]/K1；按证据顺序映射回真实 ref，避免引用被白名单丢弃
        match = re.fullmatch(r"\[?K(\d+)\]?", ref, flags=re.IGNORECASE)
        if match:
            index = int(match.group(1)) - 1
            if 0 <= index < len(allowed_list):
                ref = allowed_list[index]
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


async def build_knowledge_brief(
    topic: str,
    level: str,
    sources: List[Any],
    *,
    kb_pack: Any = None,
    kb_titles: str = "",
) -> Dict[str, Any]:
    llm = get_llm()
    if kb_pack is not None and getattr(kb_pack, "chunks", None):
        variables = {
            "topic": topic,
            "level_guide": LEVEL_GUIDE.get(level, LEVEL_GUIDE["basic"]),
            "kb_titles": kb_titles or "（用户知识库）",
            "kb_evidence": format_kb_evidence(kb_pack.chunks),
            "web_evidence": format_web_evidence(getattr(kb_pack, "web_sources", []) or []),
        }
        context = {
            "topic": topic,
            "sources": [s.model_dump() for s in sources],
            "evidence_refs": list(getattr(kb_pack, "allowed_refs", []) or []),
        }
        result = await llm.run(
            "rag_digest",
            variables,
            context=context,
            temperature=0.2,
            max_tokens=2000,
        )
    else:
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
        sources: List[Any] = []
        kb_pack = None
        use_kb = False
        kb_titles = ""
        allowed_refs: List[str] = []
        kb_ids = list(session.get("kb_ids") or [])
        source_mode = session.get("source_mode") or "model"

        if kb_ids and source_mode in {"kb_only", "hybrid"}:
            kb_names = kb_service.names_for(kb_ids)
            kb_titles = "、".join(kb_names.values()) or "用户知识库"
            kb_pack = await retrieve(
                topic,
                kb_ids,
                source_mode,
                settings=settings,
                lexical_search=db.search_kb_chunks_lexical,
                kb_titles=list(kb_names.values()),
                doc_titles=kb_service.doc_titles_for(kb_ids),
            )
            sources = build_source_items(kb_pack, kb_names)
            db.update_session(
                session_id,
                sources=[s.model_dump() for s in sources],
                retrieval_trace=kb_pack.trace,
            )
            use_kb = bool(kb_pack.chunks)
            if not use_kb and source_mode == "kb_only":
                raise RagError(
                    "资料库里没有检索到与这个主题相关的内容。可以换一个更具体的说法，或先补充资料。"
                )

        if not use_kb and kb_pack is None:
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
        brief_result = await build_knowledge_brief(
            topic,
            level,
            sources,
            kb_pack=kb_pack if use_kb else None,
            kb_titles=kb_titles,
        )
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
        has_objective = any(t in OBJECTIVE_TYPES for t in allowed_types)
        has_subjective = "short_answer" in allowed_types
        if has_objective and has_subjective:
            type_mix_note = "至少包含一种客观题和一种主观题"
        elif has_objective:
            type_mix_note = "本组只生成客观题，不要生成简答题"
        else:
            type_mix_note = "本组只生成简答题，不要生成客观题"

        if use_kb and kb_pack is not None:
            allowed_refs = list(kb_pack.allowed_refs)
            allowed_refs.extend(
                source.url for source in sources if source.kind == "web" and source.url
            )
            ref_hint = (
                "、".join(allowed_refs[:10])
                if allowed_refs
                else "（无可用 ref，source_refs 留空数组）"
            )
            gen_task = "rag_generate"
        else:
            allowed_refs = [source.url for source in sources if source.url]
            ref_hint = ""
            gen_task = "generate"
        url_hint = (
            "、".join(allowed_refs[:5])
            if allowed_refs
            else "（无可用链接，source_refs 留空数组）"
        )

        # 真实网关单次输出约 4k tokens，15 题会被截断；按 5 题分批生成再合并去重。
        batch_size = max(1, int(settings.question_generate_batch_size))
        batch_total = (count + batch_size - 1) // batch_size
        raw_questions: List[Any] = []
        seen_stems: List[str] = []
        avoid_stems = "（无）"
        model_name: Optional[str] = None

        for batch_index in range(batch_total):
            offset = batch_index * batch_size
            chunk = min(batch_size, count - offset)
            batch_note = (
                f"整套共 {count} 题；当前是第 {batch_index + 1}/{batch_total} 批，"
                f"本批只输出 {chunk} 题。请围绕提纲中不同知识点出题，"
                "避免与前面批次重复；不要因为篇幅省略题目。"
            )
            variables = {
                "topic": topic,
                "count": chunk,
                "batch_note": batch_note,
                "type_mix_note": type_mix_note,
                "avoid_stems": avoid_stems,
                "level_guide": LEVEL_GUIDE.get(level, LEVEL_GUIDE["basic"]),
                "type_desc": type_desc,
                "type_rules": TYPE_RULES,
                "brief_json": json.dumps(brief, ensure_ascii=False, indent=2),
                "url_hint": url_hint,
            }
            if use_kb and kb_pack is not None:
                variables["kb_evidence"] = format_kb_evidence(kb_pack.chunks)
                variables["ref_hint"] = ref_hint
            context = {
                "topic": topic,
                "count": chunk,
                "seq_offset": offset,
                "batch_index": batch_index,
                "batch_total": batch_total,
                "types": allowed_types,
                "brief": brief,
                "allowed_refs": allowed_refs,
            }
            gen_result = await llm.run(
                gen_task,
                variables,
                context=context,
                temperature=0.7,
                max_tokens=max(4000, min(16000, chunk * 800)),
            )
            db.add_usage(
                session_id,
                gen_result.tokens_in,
                gen_result.tokens_out,
                gen_result.cost_cny,
            )
            model_name = model_name or gen_result.model
            batch_raw = gen_result.data.get("questions")
            if isinstance(batch_raw, list):
                raw_questions.extend(batch_raw)
                for item in batch_raw:
                    if isinstance(item, dict):
                        stem = str(item.get("stem") or "").strip()
                        if stem:
                            seen_stems.append(stem[:120])
                avoid_stems = "\n".join(f"- {s}" for s in seen_stems[-12:]) or "（无）"
            db.update_session(
                session_id,
                progress=68 + int(20 * (batch_index + 1) / batch_total),
            )

        questions = validate_questions(
            raw_questions,
            session_id=session_id,
            count=count,
            allowed_types=allowed_types,
            allowed_urls=allowed_refs,
        )
        db.insert_questions(session_id, questions)
        db.update_session(
            session_id,
            status="ready",
            stage="ready",
            progress=100,
            error=None,
            model=model_name or usage.model,
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
        refund_failure(session)


def _friendly_error(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, RagError):
        return message[:240]
    if isinstance(exc, LLMError):
        if "余额不足" in message or "API Key 无效" in message:
            return message
        return f"AI 生成失败，请重试：{message[:120]}"
    if "timeout" in message.lower():
        return "AI 生成超时，请稍后重试"
    return "服务开小差了，请稍后重试"