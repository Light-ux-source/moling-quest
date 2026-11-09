"""LangChain 模型适配：真实 ChatDeepSeek + 离线 MockChatModel。"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from ..config import Settings
from .mock_data import build_mock_data

_default_model: Optional[BaseChatModel] = None


def create_deepseek_model(settings: Settings) -> BaseChatModel:
    """按官方 langchain-deepseek 集成创建 ChatDeepSeek。

    - JSON Output：response_format=json_object，Prompt 中必须出现 JSON；
    - 思考模式：DeepSeek 默认开启，必须显式 disabled 才关闭；
    - extra_body / model_kwargs 由 BaseChatOpenAI 透传。
    """
    from langchain_deepseek import ChatDeepSeek

    extra_body: Dict[str, Any] = {
        "thinking": {"type": "enabled" if settings.deepseek_thinking else "disabled"}
    }
    if settings.deepseek_thinking:
        extra_body["reasoning_effort"] = "high"

    return ChatDeepSeek(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key.strip(),
        api_base=settings.deepseek_base_url.rstrip("/"),
        temperature=0.3,
        max_tokens=4000,
        timeout=settings.deepseek_timeout,
        max_retries=settings.deepseek_max_retries,
        model_kwargs={"response_format": {"type": "json_object"}},
        extra_body=extra_body,
    )


def get_default_model(settings: Settings) -> BaseChatModel:
    global _default_model
    if _default_model is None:
        _default_model = create_deepseek_model(settings)
    return _default_model


async def close_default_model() -> None:
    global _default_model
    if _default_model is not None:
        client = getattr(_default_model, "async_client", None)
        if client is not None:
            try:
                await client.close()
            except Exception:  # noqa: BLE001 - 关闭失败不影响退出
                pass
        _default_model = None


class MockChatModel(BaseChatModel):
    """离线模型：按 task + context 返回确定性 JSON，走真实 LangChain 链。"""

    task: str
    context: Dict[str, Any] = Field(default_factory=dict)
    model_name: str = "mock-deepseek-flash"

    @property
    def _llm_type(self) -> str:
        return "mock-deepseek"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        data = build_mock_data(self.task, self.context)
        message = AIMessage(
            content=json.dumps(data, ensure_ascii=False),
            usage_metadata={
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
            response_metadata={"model_name": self.model_name},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)