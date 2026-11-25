"""RAG Prompt 与 Mock 数据测试。"""

from __future__ import annotations

import pytest

from app.chains import PROMPTS, run_chain
from app.chains.models import MockChatModel


def test_rag_prompts_are_templates_with_json():
    cases = {
        "rag_plan": {
            "topic": "HTTP 缓存",
            "kb_titles": "前端资料库",
            "doc_titles": "HTTP 缓存.pdf",
        },
        "rag_evaluate": {"topic": "HTTP 缓存", "evidence_json": "[]"},
        "rag_digest": {
            "topic": "HTTP 缓存",
            "level_guide": "入门",
            "kb_titles": "前端资料库",
            "kb_evidence": "[K1] ref=kb://d/1",
            "web_evidence": "（空）",
        },
        "rag_generate": {
            "topic": "HTTP 缓存",
            "count": 3,
            "batch_note": "单批",
            "type_mix_note": "混合",
            "avoid_stems": "（无）",
            "level_guide": "入门",
            "type_desc": "单选题",
            "type_rules": "规范",
            "brief_json": "{}",
            "kb_evidence": "[K1] ref=kb://d/1",
            "ref_hint": "kb://d/1",
        },
    }
    for task, variables in cases.items():
        assert task in PROMPTS
        messages = PROMPTS[task].format_messages(**variables)
        text = "\n".join(str(message.content) for message in messages)
        assert "JSON" in text
        assert variables["topic"] in text


@pytest.mark.asyncio
async def test_mock_rag_plan_and_evaluate():
    plan_context = {"topic": "HTTP 缓存"}
    plan = await run_chain(
        "rag_plan",
        {
            "topic": "HTTP 缓存",
            "kb_titles": "前端资料库",
            "doc_titles": "缓存.pdf",
        },
        context=plan_context,
        model=MockChatModel(task="rag_plan", context=plan_context),
    )
    assert plan.data["queries"]
    assert any("HTTP 缓存" in query for query in plan.data["queries"])

    evaluate_context = {"topic": "HTTP 缓存", "evidence": []}
    verdict = await run_chain(
        "rag_evaluate",
        {"topic": "HTTP 缓存", "evidence_json": "[]"},
        context=evaluate_context,
        model=MockChatModel(task="rag_evaluate", context=evaluate_context),
    )
    assert verdict.data["sufficient"] is True


@pytest.mark.asyncio
async def test_mock_rag_digest_and_generate_keep_refs():
    digest_context = {
        "topic": "HTTP 缓存",
        "evidence_refs": ["kb://doc1/chunk/1", "kb://doc1/chunk/2"],
    }
    digest = await run_chain(
        "rag_digest",
        {
            "topic": "HTTP 缓存",
            "level_guide": "入门",
            "kb_titles": "前端资料库",
            "kb_evidence": "[K1] ref=kb://doc1/chunk/1",
            "web_evidence": "（空）",
        },
        context=digest_context,
        model=MockChatModel(task="rag_digest", context=digest_context),
    )
    assert any(point.get("source_ref") for point in digest.data["key_points"])

    generate_context = {
        "topic": "HTTP 缓存",
        "count": 2,
        "types": ["single_choice"],
        "allowed_refs": ["kb://doc1/chunk/1", "kb://doc1/chunk/2"],
    }
    generated = await run_chain(
        "rag_generate",
        {
            "topic": "HTTP 缓存",
            "count": 2,
            "batch_note": "单批",
            "type_mix_note": "客观题",
            "avoid_stems": "（无）",
            "level_guide": "入门",
            "type_desc": "单选题",
            "type_rules": "规范",
            "brief_json": "{}",
            "kb_evidence": "[K1] ref=kb://doc1/chunk/1",
            "ref_hint": "kb://doc1/chunk/1",
        },
        context=generate_context,
        model=MockChatModel(task="rag_generate", context=generate_context),
    )
    questions = generated.data["questions"]
    assert questions
    assert all(question["source_refs"] for question in questions)