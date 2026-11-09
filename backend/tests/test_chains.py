"""LangChain Prompt 编排与解析层测试（先写测试，再实现）。"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_PROVIDER", "mock")

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.chains import PROMPTS, run_chain
from app.chains.models import MockChatModel
from app.chains.parsing import parse_ai_message
from app.config import get_settings
from app.llm import LLMError, extract_json, map_llm_error


def _text(messages) -> str:
    return "\n".join(str(m.content) for m in messages)


def test_digest_prompt_is_langchain_template_with_json():
    messages = PROMPTS["digest"].format_messages(
        topic="HTTP 缓存", level_guide="入门", source_text="资料 A"
    )
    text = _text(messages)
    assert "JSON" in text
    assert "HTTP 缓存" in text
    assert "资料 A" in text


def test_generate_prompt_contains_count_types_and_brief():
    messages = PROMPTS["generate"].format_messages(
        topic="HTTP 缓存",
        count=5,
        level_guide="进阶级",
        type_desc="单选题、多选题",
        type_rules="题型规范",
        brief_json='{"key_points": []}',
        url_hint="https://example.com",
    )
    text = _text(messages)
    assert "JSON" in text
    assert "5" in text
    assert "HTTP 缓存" in text
    assert "单选题、多选题" in text
    assert "https://example.com" in text


def test_grade_prompt_contains_rubric_and_answer():
    messages = PROMPTS["grade"].format_messages(
        stem="请解释强缓存",
        rubric_json='["定义", "机制"]',
        correct_json='["定义", "机制"]',
        answer_json='"强缓存是……"',
        level="basic",
    )
    text = _text(messages)
    assert "JSON" in text
    assert "强缓存" in text
    assert "定义" in text


def test_report_prompt_contains_stats():
    messages = PROMPTS["report"].format_messages(
        topic="HTTP 缓存",
        level="basic",
        total=5,
        correct=4,
        accuracy_pct="80%",
        duration=120,
        items_json='[{"seq": 1}]',
    )
    text = _text(messages)
    assert "JSON" in text
    assert "80%" in text
    assert "HTTP 缓存" in text


@pytest.mark.asyncio
async def test_mock_digest_chain_returns_structured_data():
    context = {"topic": "HTTP 缓存", "sources": []}
    result = await run_chain(
        "digest",
        {
            "topic": "HTTP 缓存",
            "level_guide": "入门",
            "source_text": "资料",
        },
        context=context,
        model=MockChatModel(task="digest", context=context),
    )
    assert result.data["key_points"]
    assert result.model == "mock-deepseek-flash"


@pytest.mark.asyncio
async def test_mock_generate_chain_returns_questions():
    context = {"topic": "HTTP 缓存", "count": 5, "types": ["single_choice", "short_answer"]}
    result = await run_chain(
        "generate",
        {
            "topic": "HTTP 缓存",
            "count": 5,
            "level_guide": "入门",
            "type_desc": "单选题、简答题",
            "type_rules": "题型规范",
            "brief_json": "{}",
            "url_hint": "",
        },
        context=context,
        model=MockChatModel(task="generate", context=context),
    )
    questions = result.data["questions"]
    assert len(questions) == 5
    assert [q["type"] for q in questions][:2] == ["single_choice", "short_answer"]


@pytest.mark.asyncio
async def test_mock_grade_and_report_chains():
    grade_ctx = {"user_answer": "先定义再讲机制", "rubric": ["定义", "机制"]}
    grade = await run_chain(
        "grade",
        {
            "stem": "请解释",
            "rubric_json": '["定义", "机制"]',
            "correct_json": '["定义", "机制"]',
            "answer_json": '"先定义再讲机制"',
            "level": "basic",
        },
        context=grade_ctx,
        model=MockChatModel(task="grade", context=grade_ctx),
    )
    assert 0.0 <= grade.data["score"] <= 1.0

    report_ctx = {"topic": "HTTP 缓存", "accuracy": 0.8, "wrong_seqs": [{"seq": 2, "type_label": "多选题"}]}
    report = await run_chain(
        "report",
        {
            "topic": "HTTP 缓存",
            "level": "basic",
            "total": 5,
            "correct": 4,
            "accuracy_pct": "80%",
            "duration": 120,
            "items_json": "[]",
        },
        context=report_ctx,
        model=MockChatModel(task="report", context=report_ctx),
    )
    assert report.data["summary"]
    assert report.data["knowledge_gaps"]


def test_parse_ai_message_extracts_data_and_usage():
    ai = AIMessage(
        content='```json\n{"a": 1}\n```',
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        response_metadata={"model_name": "deepseek-flash"},
    )
    result = parse_ai_message(ai, get_settings())
    assert result.data == {"a": 1}
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    assert result.cost_cny > 0
    assert result.model == "deepseek-flash"


def test_parse_ai_message_rejects_empty_content():
    with pytest.raises(LLMError) as exc:
        parse_ai_message(AIMessage(content=""), get_settings())
    assert "空内容" in str(exc.value)


class _FlakyChatModel(BaseChatModel):
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "flaky"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        content = "" if self.calls == 1 else '{"ok": true}'
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.mark.asyncio
async def test_run_chain_retries_once_on_empty_content():
    model = _FlakyChatModel()
    result = await run_chain(
        "digest",
        {"topic": "x", "level_guide": "y", "source_text": "z"},
        context={},
        model=model,
    )
    assert result.data == {"ok": True}
    assert model.calls == 2


def test_map_llm_error_maps_status_codes():
    class _StatusError(Exception):
        status_code = 402

    assert "余额不足" in str(map_llm_error(_StatusError()))

    class _AuthError(Exception):
        status_code = 401

    assert "API Key" in str(map_llm_error(_AuthError()))


def test_extract_json_still_exported_from_llm():
    assert extract_json('{"a": 1}') == {"a": 1}