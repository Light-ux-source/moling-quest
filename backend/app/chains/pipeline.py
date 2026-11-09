"""LCEL 链执行器：Prompt → ChatModel → JSON/usage 解析。"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableLambda

from ..config import Settings, get_settings
from ..llm_types import LLMError, LLMResult, map_llm_error
from ..prompts import PROMPTS
from .models import MockChatModel, get_default_model
from .parsing import parse_ai_message


async def run_chain(
    task: str,
    variables: Mapping[str, Any],
    *,
    context: Optional[Dict[str, Any]] = None,
    model: Optional[BaseChatModel] = None,
    settings: Optional[Settings] = None,
    temperature: float = 0.3,
    max_tokens: int = 3000,
) -> LLMResult:
    """执行指定任务的 LangChain 链。

    - 真实模式：调用 ChatDeepSeek（JSON Output + 思考模式开关）；
    - Mock 模式：MockChatModel 返回确定性 JSON，链结构完全一致；
    - 空 content 自动重试一次，其余错误翻译为中文 LLMError。
    """
    if task not in PROMPTS:
        raise LLMError(f"未知的 AI 任务：{task}")

    active_settings = settings or get_settings()
    if model is None:
        if active_settings.is_mock:
            model = MockChatModel(task=task, context=context or {})
        else:
            model = get_default_model(active_settings)

    prompt = PROMPTS[task]
    chain = (
        prompt
        | model.bind(temperature=temperature, max_tokens=max_tokens)
        | RunnableLambda(lambda message: parse_ai_message(message, active_settings))
    )

    last_error: Optional[LLMError] = None
    for attempt in range(2):
        try:
            return await chain.ainvoke(dict(variables))
        except LLMError as exc:
            last_error = exc
            # JSON Output 偶尔会返回空 content（DeepSeek 文档明确说明），重试一次
            if "空内容" in str(exc) and attempt == 0:
                continue
            raise
        except Exception as exc:  # noqa: BLE001 - 统一翻译为业务错误
            raise map_llm_error(exc) from exc

    raise last_error or LLMError("AI 调用失败")