"""把 LangChain AIMessage 解析成业务可用的 LLMResult。"""

from __future__ import annotations

from typing import Any, List

from langchain_core.messages import AIMessage

from ..config import Settings
from ..llm_types import LLMError, LLMResult, estimate_cost, extract_json


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(content or "")


def parse_ai_message(message: AIMessage, settings: Settings) -> LLMResult:
    text = _content_to_text(message.content).strip()
    if not text:
        raise LLMError("模型返回空内容")

    data = extract_json(text)

    usage = message.usage_metadata or {}
    tokens_in = int(usage.get("input_tokens") or 0)
    tokens_out = int(usage.get("output_tokens") or 0)
    if not usage:
        meta = message.response_metadata or {}
        fallback = meta.get("token_usage") or meta.get("usage") or {}
        tokens_in = int(fallback.get("prompt_tokens") or fallback.get("input_tokens") or 0)
        tokens_out = int(fallback.get("completion_tokens") or fallback.get("output_tokens") or 0)

    model = (message.response_metadata or {}).get("model_name") or settings.deepseek_model
    return LLMResult(
        data=data,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_cny=estimate_cost(tokens_in, tokens_out, settings),
        model=str(model),
    )