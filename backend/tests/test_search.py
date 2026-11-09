"""联网检索结果过滤测试（官方文档：rerank_score >= 1.5 为优质结果）。"""

from __future__ import annotations

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