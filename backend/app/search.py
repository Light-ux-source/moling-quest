"""联网检索：Tavily Search API / DeepSeek 官方 Search API。

需求里的「AI 自动从全网获取知识」由这一层兜底：
1. 先用 Search 拿到带摘要的真实网页（默认 Tavily，与 Chat 网关解耦）；
2. 摘要交给模型做知识提炼（digest）；
3. 出题时要求引用来源，报告里可回溯。

检索失败不阻塞主流程 —— 自动降级为「纯模型知识出题」，并在 session 上标记。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from .config import Settings, get_settings
from .schemas import SourceItem

logger = logging.getLogger(__name__)

# 官方文档：rerank_score 0～3，>=1.5 为优质结果（2026-11 核实）
MIN_RERANK_SCORE = 1.5


def build_queries(topic: str) -> List[str]:
    topic = topic[:80]
    return [topic, f"{topic} 核心概念 原理 常见误区"]


def filter_results(results: List[Dict[str, Any]]) -> List[SourceItem]:
    """过滤低质来源、按 URL 去重，并裁剪到 UI 可展示的长度。"""
    items: List[SourceItem] = []
    seen_urls = set()
    for raw in results:
        score = raw.get("rerank_score")
        if not isinstance(score, (int, float)) or score < MIN_RERANK_SCORE:
            continue
        url = (raw.get("url") or "")[:500]
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        items.append(
            SourceItem(
                title=(raw.get("title") or "")[:120],
                url=url,
                site_name=raw.get("site_name"),
                summary=(raw.get("summary") or raw.get("snippet") or "")[:800],
            )
        )
    return items


class SearchClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.deepseek_search_base_url.rstrip("/"),
            timeout=httpx.Timeout(20.0, connect=8.0),
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key.strip()}",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, count: int = 6) -> List[SourceItem]:
        try:
            resp = await self._client.post(
                "/v1/tools/search",
                json={"query": query[:128], "count": max(1, min(count, 50)), "need_content": False},
            )
        except httpx.HTTPError as exc:
            logger.warning("Search 网络错误 query=%s err=%s", query, exc)
            return []
        if resp.status_code != 200:
            logger.warning("Search 失败 status=%s body=%s", resp.status_code, resp.text[:200])
            return []

        results = (resp.json() or {}).get("results") or []
        return filter_results(results)

    async def search_many(self, topic: str, per_query: int = 5) -> List[SourceItem]:
        seen: Dict[str, SourceItem] = {}
        for q in build_queries(topic):
            for item in await self.search(q, per_query):
                key = item.url or item.title
                if key and key not in seen:
                    seen[key] = item
        return list(seen.values())[: self.settings.search_count * 2]


def _site_name(url: str) -> str:
    """从 URL 提取可展示的站点名；失败时返回空串。"""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001 - 展示字段失败不抛错
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host[:80]


class TavilySearchClient:
    """Tavily 联网检索（官方 Search API，2026-11 核实）。

    官方文档：POST /search，Bearer 鉴权；无 Key 时可用
    ``X-Tavily-Access-Mode: keyless``（免费、限流）。返回
    ``results[].content`` 可直接作为摘要注入 digest Prompt。
    """

    def __init__(self, settings: Settings, client: Optional[httpx.AsyncClient] = None) -> None:
        self.settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.tavily_base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.tavily_timeout, connect=8.0),
        )

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self.settings.tavily_api_key.strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        else:
            # keyless 只在显式 provider=tavily 时才会走到这里（见 effective_search_provider）
            headers["X-Tavily-Access-Mode"] = "keyless"
        return headers

    def _payload(self, query: str, count: int) -> Dict[str, Any]:
        depth = (self.settings.tavily_search_depth or "basic").strip().lower()
        if depth not in {"advanced", "basic", "fast", "ultra-fast"}:
            depth = "basic"
        topic = (self.settings.tavily_topic or "general").strip().lower()
        if topic not in {"general", "news", "finance"}:
            topic = "general"
        return {
            "query": query[:400],
            "search_depth": depth,
            "max_results": max(1, min(count, 20)),
            # 只需要干净摘要；正文留给需要时再取，避免撑爆 Prompt
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            # 让来源带发布日期，Prompt 可优先采用较新资料
            "include_published_date": True,
            "chunks_per_source": 3,
            "include_usage": True,
            "topic": topic,
        }

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, count: int = 6) -> List[SourceItem]:
        try:
            resp = await self._client.post(
                "/search",
                json=self._payload(query, count),
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            logger.warning("Tavily 搜索网络错误 query=%s err=%s", query, exc)
            return []
        if resp.status_code != 200:
            logger.warning("Tavily 搜索失败 status=%s body=%s", resp.status_code, resp.text[:200])
            return []
        try:
            data = resp.json() or {}
        except ValueError:
            logger.warning("Tavily 返回非 JSON query=%s", query)
            return []

        results = data.get("results") or []
        if not isinstance(results, list):
            return []
        items: List[SourceItem] = []
        seen_urls = set()
        for raw in results:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = str(raw.get("title") or "").strip()[:120]
            summary = str(raw.get("content") or raw.get("snippet") or "").strip()
            published = str(raw.get("published_date") or "").strip()
            if published:
                summary = f"（发布/更新：{published}）{summary}"
            items.append(
                SourceItem(
                    title=title or _site_name(url) or url[:120],
                    url=url[:500],
                    site_name=_site_name(url) or None,
                    summary=summary[:800],
                )
            )
        usage = data.get("usage") or {}
        if isinstance(usage, dict) and usage.get("credits") is not None:
            logger.info("Tavily 检索完成 query=%s results=%s credits=%s", query, len(items), usage.get("credits"))
        return items

    async def search_many(self, topic: str, per_query: int = 5) -> List[SourceItem]:
        # 一次多拿几条比多次少量更划算；官方建议查询保持简短
        return await self.search(topic, count=max(per_query, self.settings.search_count))


class NoopSearchClient:
    """真实模式但关闭联网检索：不返回任何来源（也不伪造模拟来源）。"""

    async def search_many(self, topic: str, per_query: int = 5) -> List[SourceItem]:
        return []

    async def aclose(self) -> None:
        return None


class MockSearchClient:
    """离线模式：返回明确标注为模拟的来源，避免伪造真实链接。"""

    async def search_many(self, topic: str, per_query: int = 5) -> List[SourceItem]:
        return [
            SourceItem(
                title=f"{topic} · 概念综述（模拟来源）",
                url="",
                site_name="本地模拟",
                summary=f"围绕 {topic} 的定义、发展脉络与典型应用展开，用于离线演示检索环节。",
            ),
            SourceItem(
                title=f"{topic} 常见误区盘点（模拟来源）",
                url="",
                site_name="本地模拟",
                summary=f"列举学习 {topic} 时最容易混淆的 3 组概念及判断方法。",
            ),
        ]

    async def aclose(self) -> None:
        return None


_search: Any = None


def get_search() -> Any:
    global _search
    if _search is None:
        settings = get_settings()
        if settings.is_mock:
            # Mock 模式始终返回模拟来源，保证无 Key 也能完整演示检索环节
            _search = MockSearchClient()
        else:
            provider = settings.effective_search_provider
            if provider == "tavily":
                _search = TavilySearchClient(settings)
            elif provider == "deepseek":
                _search = SearchClient(settings)
            else:
                _search = NoopSearchClient()
    return _search


async def close_search() -> None:
    global _search
    if _search is not None:
        await _search.aclose()
        _search = None