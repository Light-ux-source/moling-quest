"""联网检索：DeepSeek 官方 Search API（/v1/tools/search）。

需求里的「AI 自动从全网获取知识」由这一层兜底：
1. 先用 Search 拿到带摘要的真实网页；
2. 摘要交给模型做知识提炼（digest）；
3. 出题时要求引用来源，报告里可回溯。

检索失败不阻塞主流程 —— 自动降级为「纯模型知识出题」，并在 session 上标记。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from .config import Settings, get_settings
from .schemas import SourceItem

logger = logging.getLogger(__name__)


def build_queries(topic: str) -> List[str]:
    topic = topic[:80]
    return [topic, f"{topic} 核心概念 原理 常见误区"]


class SearchClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.deepseek_base_url.rstrip("/"),
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
        items: List[SourceItem] = []
        for r in results:
            score = r.get("rerank_score")
            if isinstance(score, (int, float)) and score < 0.6:
                continue
            items.append(
                SourceItem(
                    title=(r.get("title") or "")[:120],
                    url=(r.get("url") or "")[:500],
                    site_name=r.get("site_name"),
                    summary=(r.get("summary") or r.get("snippet") or "")[:800],
                )
            )
        return items

    async def search_many(self, topic: str, per_query: int = 5) -> List[SourceItem]:
        seen: Dict[str, SourceItem] = {}
        for q in build_queries(topic):
            for item in await self.search(q, per_query):
                key = item.url or item.title
                if key and key not in seen:
                    seen[key] = item
        return list(seen.values())[: self.settings.search_count * 2]


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
        if settings.enable_web_search and not settings.is_mock:
            _search = SearchClient(settings)
        else:
            _search = MockSearchClient()
    return _search


async def close_search() -> None:
    global _search
    if _search is not None:
        await _search.aclose()
        _search = None