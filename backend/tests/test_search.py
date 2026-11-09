"""联网检索结果过滤测试（官方文档：rerank_score >= 1.5 为优质结果）。"""

from __future__ import annotations

import pytest

from app.search import build_queries, filter_results


def test_build_queries_covers_topic_and_misconceptions():
    queries = build_queries("HTTP 缓存")
    assert queries[0] == "HTTP 缓存"
    assert any("误区" in q for q in queries)


def test_filter_results_keeps_only_high_quality():
    raw = [
        {"title": "低质", "url": "https://a", "summary": "x", "rerank_score": 0.6},
        {"title": "边界", "url": "https://b", "summary": "y", "rerank_score": 1.49},
        {"title": "优质", "url": "https://c", "summary": "z", "rerank_score": 1.5},
        {"title": "更优质", "url": "https://d", "summary": "w", "rerank_score": 2.4},
        {"title": "无分数", "url": "https://e", "summary": "v"},
    ]
    items = filter_results(raw)
    assert [i.url for i in items] == ["https://c", "https://d"]


def test_filter_results_deduplicates_urls():
    raw = [
        {"title": "A", "url": "https://a", "summary": "x", "rerank_score": 2.0},
        {"title": "A2", "url": "https://a", "summary": "y", "rerank_score": 1.9},
    ]
    items = filter_results(raw)
    assert len(items) == 1
    assert items[0].title == "A"

@pytest.mark.asyncio
async def test_real_mode_without_web_search_returns_noop(monkeypatch):
    from app import search
    from app.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-only")
    monkeypatch.setenv("ENABLE_WEB_SEARCH", "false")
    get_settings.cache_clear()
    search._search = None

    client = search.get_search()
    assert isinstance(client, search.NoopSearchClient)
    assert await client.search_many("HTTP 缓存") == []


@pytest.mark.asyncio
async def test_mock_mode_still_returns_mock_sources(monkeypatch):
    from app import search
    from app.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("ENABLE_WEB_SEARCH", "false")
    get_settings.cache_clear()
    search._search = None

    client = search.get_search()
    assert isinstance(client, search.MockSearchClient)
    items = await client.search_many("HTTP 缓存")
    assert items and items[0].site_name == "本地模拟"
