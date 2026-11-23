"""Tavily 联网检索适配层测试（先写测试，再实现）。

覆盖：
- 请求形状（Bearer / keyless、search_depth、max_results、不取正文）；
- 响应解析（标题/URL/摘要/站点名、URL 去重、空 URL 丢弃）；
- HTTP 失败时降级为空来源，不阻断出题；
- provider 选择与 /health 的 web_search 状态。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import search
from app.config import Settings, get_settings
from app.search import TavilySearchClient, get_search


def _settings(**overrides) -> Settings:
    values = {
        "llm_provider": "deepseek",
        "deepseek_api_key": "sk-test-only",
        "enable_web_search": True,
        "search_provider": "tavily",
        "tavily_api_key": "tvly-test-only",
        "tavily_base_url": "https://api.tavily.com",
        "tavily_allow_keyless": True,
        "search_count": 6,
    }
    values.update(overrides)
    return Settings(**values)


def _tavily_response() -> dict:
    return {
        "query": "HTTP 缓存",
        "answer": "强缓存不发请求，协商缓存发请求验证。",
        "results": [
            {
                "title": "HTTP 缓存 - MDN",
                "url": "https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Caching",
                "content": "强缓存由 max-age 控制，命中时不发请求。",
                "score": 0.92,
                "published_date": "2026-01-02T00:00:00+00:00",
            },
            {
                "title": "重复来源",
                "url": "https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Caching",
                "content": "重复 URL 应被去重。",
                "score": 0.80,
            },
            {
                "title": "RFC 9111",
                "url": "https://www.rfc-editor.org/rfc/rfc9111.html",
                "content": "HTTP Caching 的权威规范。",
                "score": 0.71,
            },
            {
                "title": "没有链接的结果",
                "url": "",
                "content": "无 URL 不应进入来源列表。",
                "score": 0.50,
            },
        ],
        "response_time": 1.2,
        "usage": {"credits": 1},
    }


@pytest.mark.asyncio
async def test_tavily_search_sends_expected_payload_and_parses_results():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("authorization")
        captured["keyless"] = request.headers.get("x-tavily-access-mode")
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_tavily_response())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.tavily.com") as http_client:
        client = TavilySearchClient(_settings(), client=http_client)
        sources = await client.search_many("HTTP 缓存", per_query=4)

    payload = captured["json"]
    assert captured["path"] == "/search"
    assert captured["authorization"] == "Bearer tvly-test-only"
    assert captured["keyless"] is None
    assert payload["query"] == "HTTP 缓存"
    assert payload["search_depth"] == "basic"
    assert payload["max_results"] == 6
    assert payload["include_raw_content"] is False
    assert payload["include_images"] is False
    assert payload["include_usage"] is True
    assert payload["include_published_date"] is True
    assert payload["chunks_per_source"] == 3

    assert len(sources) == 2
    assert sources[0].url == "https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Caching"
    assert sources[0].title == "HTTP 缓存 - MDN"
    assert sources[0].site_name == "developer.mozilla.org"
    assert "max-age" in sources[0].summary
    assert "2026-01-02" in sources[0].summary
    assert sources[1].site_name == "rfc-editor.org"


@pytest.mark.asyncio
async def test_tavily_without_key_uses_keyless_header():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["keyless"] = request.headers.get("x-tavily-access-mode")
        return httpx.Response(200, json=_tavily_response())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.tavily.com") as http_client:
        client = TavilySearchClient(_settings(tavily_api_key=""), client=http_client)
        sources = await client.search_many("HTTP 缓存")

    assert captured["authorization"] is None
    assert captured["keyless"] == "keyless"
    assert sources


@pytest.mark.asyncio
async def test_tavily_http_error_returns_empty_and_does_not_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": {"error": "server error"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.tavily.com") as http_client:
        client = TavilySearchClient(_settings(), client=http_client)
        sources = await client.search_many("HTTP 缓存")

    assert sources == []


@pytest.mark.asyncio
async def test_tavily_invalid_json_returns_empty_and_does_not_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-a-json")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.tavily.com") as http_client:
        client = TavilySearchClient(_settings(), client=http_client)
        sources = await client.search_many("HTTP 缓存")

    assert sources == []


def test_tavily_provider_is_selected_when_configured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-only")
    monkeypatch.setenv("ENABLE_WEB_SEARCH", "true")
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-only")
    get_settings.cache_clear()
    search._search = None

    client = get_search()
    assert isinstance(client, TavilySearchClient)


def test_auto_provider_does_not_enable_keyless_without_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-only")
    monkeypatch.setenv("ENABLE_WEB_SEARCH", "true")
    monkeypatch.setenv("SEARCH_PROVIDER", "auto")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()
    search._search = None

    settings = get_settings()
    assert settings.effective_search_provider == "none"
    assert isinstance(get_search(), search.NoopSearchClient)


def test_explicit_tavily_allows_keyless_without_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-only")
    monkeypatch.setenv("ENABLE_WEB_SEARCH", "true")
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("TAVILY_ALLOW_KEYLESS", "true")
    get_settings.cache_clear()
    search._search = None

    settings = get_settings()
    assert settings.effective_search_provider == "tavily"
    assert isinstance(get_search(), TavilySearchClient)


@pytest.mark.asyncio
async def test_health_reports_tavily(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-only")
    monkeypatch.setenv("ENABLE_WEB_SEARCH", "true")
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-only")
    get_settings.cache_clear()

    res = await client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["web_search"] is True
    assert body["search_provider"] == "tavily"

@pytest.mark.asyncio
async def test_tavily_sources_are_injected_into_digest_and_whitelisted(monkeypatch):
    """检索摘要必须进入 digest Prompt，且题目 source_refs 只能引用真实来源。"""
    from app import db
    from app.llm_types import LLMResult
    from app.schemas import SourceItem
    from app.services import question_gen

    db.create_session(
        {
            "id": "s_tavily_fixture",
            "client_id": "test_tavily_client",
            "topic": "HTTP 强缓存与协商缓存",
            "level": "basic",
            "requested_types": ["single_choice"],
            "question_count": 3,
            "status": "queued",
        }
    )

    captured: dict = {}

    class FakeSearch:
        async def search_many(self, topic, per_query=5):
            return [
                SourceItem(
                    title="MDN HTTP 缓存",
                    url="https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Caching",
                    site_name="developer.mozilla.org",
                    summary="最新资料：强缓存由 max-age 控制，命中时不发请求。",
                )
            ]

    class FakeLLM:
        async def run(self, task, variables, **kwargs):
            captured[task] = dict(variables)
            if task == "digest":
                return LLMResult(
                    data={
                        "title": "HTTP 缓存",
                        "summary": "强缓存与协商缓存",
                        "key_points": [{"point": "强缓存", "evidence": "MDN", "source_url": ""}],
                        "misconceptions": [],
                        "prerequisites": [],
                    }
                )
            questions = []
            for i in range(1, 4):
                questions.append(
                    {
                        "type": "single_choice",
                        "title": f"知识点{i}",
                        "knowledge_point": f"知识点{i}",
                        "stem": f"关于 HTTP 缓存的说法，哪一项是正确的？第{i}题",
                        "options": [
                            {"key": "A", "text": "强缓存命中不发请求"},
                            {"key": "B", "text": "ETag 属于强缓存"},
                            {"key": "C", "text": "协商缓存永远返回 200"},
                            {"key": "D", "text": "max-age 控制协商缓存"},
                        ],
                        "correct_answer": "A",
                        "explanation": "强缓存命中时浏览器直接使用本地副本，不发起网络请求。",
                        "difficulty": "easy",
                        "rubric": [],
                        # 一个真实来源 + 一个编造来源，后者应被丢弃
                        "source_refs": [
                            "https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Caching",
                            "https://fake.example/made-up",
                        ],
                    }
                )
            return LLMResult(data={"questions": questions})

    monkeypatch.setattr(question_gen, "get_search", lambda: FakeSearch())
    monkeypatch.setattr(question_gen, "get_llm", lambda: FakeLLM())

    await question_gen.generate_for_session("s_tavily_fixture")

    assert "最新资料：强缓存由 max-age 控制" in captured["digest"]["source_text"]
    session = db.get_session("s_tavily_fixture")
    assert session and session["status"] == "ready"
    assert session["sources"][0]["url"] == "https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Caching"
    questions = db.list_questions("s_tavily_fixture")
    assert len(questions) == 3
    for question in questions:
        assert question["source_refs"] == [
            "https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Caching"
        ]
