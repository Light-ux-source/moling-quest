"""LLM 适配层（LangChain 版）。

- Prompt 编排、模型调用、JSON 解析全部走 `app/chains` 的 LCEL 链；
- 真实模式使用官方 `langchain-deepseek` 的 ChatDeepSeek；
- Mock 模式使用 MockChatModel，链结构与真实模式一致；
- 业务层只依赖 `run(task, variables, context)`，不感知 SDK。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

from .chains.models import close_default_model, get_default_model
from .chains.pipeline import run_chain
from .config import Settings, get_settings
from .llm_types import LLMError, LLMResult, estimate_cost, extract_json, map_llm_error

logger = logging.getLogger(__name__)

__all__ = [
    "LLMAdapter",
    "LLMError",
    "LLMResult",
    "estimate_cost",
    "extract_json",
    "get_llm",
    "close_llm",
    "map_llm_error",
]


class LLMAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = None if settings.is_mock else get_default_model(settings)
        logger.info(
            "LLM 初始化: %s (%s)",
            "mock" if settings.is_mock else "deepseek",
            "mock-deepseek-flash" if settings.is_mock else settings.deepseek_model,
        )

    async def run(
        self,
        task: str,
        variables: Mapping[str, Any],
        *,
        context: Optional[Dict[str, Any]] = None,
        temperature: float = 0.3,
        max_tokens: int = 3000,
    ) -> LLMResult:
        return await run_chain(
            task,
            variables,
            context=context,
            model=self.model,
            settings=self.settings,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def aclose(self) -> None:
        if self.model is not None:
            await close_default_model()
            self.model = None


_llm: Optional[LLMAdapter] = None


def get_llm() -> LLMAdapter:
    global _llm
    if _llm is None:
        _llm = LLMAdapter(get_settings())
    return _llm


async def close_llm() -> None:
    global _llm
    if _llm is not None:
        await _llm.aclose()
        _llm = None