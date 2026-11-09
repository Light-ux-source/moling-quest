"""真实 LangChain/DeepSeek 请求形状测试（不联网，用 httpx MockTransport）。"""

from __future__ import annotations

import json

import httpx
import pytest
from langchain_deepseek import ChatDeepSeek

from app.chains.pipeline import run_chain
from app.config import get_settings


@pytest.mark.asyncio
async def test_chatdeepseek_request_shape_and_usage():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"ok": true, "key_points": []}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
            },
        )

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(transport=transport)
    model = ChatDeepSeek(
        model="deepseek-flash",
        api_key="sk-test-only",
        api_base="https://api.deepseek.com",
        http_async_client=async_client,
        temperature=0.3,
        max_tokens=4000,
        max_retries=0,
        model_kwargs={"response_format": {"type": "json_object"}},
        extra_body={"thinking": {"type": "disabled"}},
    )

    try:
        result = await run_chain(
            "digest",
            {"topic": "HTTP 缓存", "level_guide": "入门", "source_text": "资料"},
            model=model,
            settings=get_settings(),
            temperature=0.2,
            max_tokens=1600,
        )
    finally:
        await async_client.aclose()

    assert result.data["ok"] is True
    assert result.tokens_in == 12
    assert result.tokens_out == 4
    assert result.cost_cny > 0

    body = captured["body"]
    assert captured["url"].endswith("/chat/completions")
    assert body["model"] == "deepseek-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert body["temperature"] == 0.2
    assert body["max_tokens"] == 1600
    assert body["messages"][0]["role"] == "system"
    assert "JSON" in body["messages"][1]["content"]