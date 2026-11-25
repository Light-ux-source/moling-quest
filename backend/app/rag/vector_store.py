"""向量存储适配：Qdrant 本地/服务端 + 内存实现。

上层只依赖异步接口；Qdrant 的同步调用放到线程池，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .types import SearchHit

logger = logging.getLogger(__name__)

_POINT_NAMESPACE = uuid.UUID("6f1c2b1e-6d7a-4f3d-9b0f-5c1a2d3e4f50")


class VectorStoreError(Exception):
    """向量库不可用/维度不一致等；消息可直接展示。"""


@dataclass
class VectorPoint:
    id: str
    vector: List[float]
    payload: Dict[str, Any] = field(default_factory=dict)


def _cosine(left: List[float], right: List[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return numerator / (left_norm * right_norm)


class MemoryVectorStore:
    """进程内实现：仅用于测试/降级；不持久化。"""

    def __init__(self, dim: int = 1024) -> None:
        self.dim = int(dim)
        self._items: Dict[str, VectorPoint] = {}
        self._lock = threading.Lock()

    async def ensure(self) -> None:
        return None

    async def upsert(self, points: Iterable[VectorPoint]) -> None:
        with self._lock:
            for point in points:
                if len(point.vector) != self.dim:
                    raise VectorStoreError(
                        f"向量维度不一致：期望 {self.dim}，实际 {len(point.vector)}"
                    )
                self._items[point.id] = VectorPoint(
                    id=point.id, vector=list(point.vector), payload=dict(point.payload or {})
                )

    async def search(self, kb_ids: List[str], vector: List[float], limit: int = 8) -> List[SearchHit]:
        if not kb_ids:
            return []
        allowed = set(kb_ids)
        with self._lock:
            items = [
                item
                for item in self._items.values()
                if item.payload.get("kb_id") in allowed
            ]
        hits = [
            SearchHit(
                chunk_id=str(item.payload.get("chunk_id") or item.id),
                score=_cosine(vector, item.vector),
                payload=dict(item.payload),
            )
            for item in items
        ]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[: max(1, int(limit))]

    async def delete_doc(self, doc_id: str) -> None:
        with self._lock:
            self._items = {
                key: value
                for key, value in self._items.items()
                if value.payload.get("doc_id") != doc_id
            }

    async def delete_kb(self, kb_id: str) -> None:
        with self._lock:
            self._items = {
                key: value
                for key, value in self._items.items()
                if value.payload.get("kb_id") != kb_id
            }

    async def count(self, kb_id: Optional[str] = None) -> int:
        with self._lock:
            if kb_id is None:
                return len(self._items)
            return sum(1 for item in self._items.values() if item.payload.get("kb_id") == kb_id)

    async def reset(self) -> None:
        with self._lock:
            self._items.clear()

    async def aclose(self) -> None:
        return None


class QdrantVectorStore:
    """Qdrant 适配：默认本地嵌入式，也可通过 URL 连服务端。"""

    def __init__(
        self,
        *,
        path: Optional[Path] = None,
        url: str = "",
        api_key: str = "",
        collection: str = "kb_chunks_v1",
        dim: int = 1024,
        timeout: float = 30.0,
    ) -> None:
        self.dim = int(dim)
        self.collection = collection
        self.path = Path(path) if path else None
        self.url = (url or "").strip()
        self.api_key = (api_key or "").strip()
        self.timeout = float(timeout)
        self._lock = threading.Lock()
        self._client: Any = None
        self._ensured = False

    def _build_client(self) -> Any:
        try:
            from qdrant_client import QdrantClient
        except Exception as exc:  # noqa: BLE001 - 依赖缺失时给出可操作错误
            raise VectorStoreError("qdrant-client 未安装，无法启用向量检索") from exc
        if self.url:
            return QdrantClient(url=self.url, api_key=self.api_key or None, timeout=self.timeout)
        if self.path is None:
            raise VectorStoreError("Qdrant 本地路径未配置")
        self.path.mkdir(parents=True, exist_ok=True)
        return QdrantClient(path=str(self.path))

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _ensure_sync(self) -> None:
        if self._ensured:
            return
        from qdrant_client import models

        client = self._get_client()
        with self._lock:
            exists = False
            try:
                exists = bool(client.collection_exists(self.collection))
            except Exception:  # noqa: BLE001 - 旧版本没有该接口
                exists = False
            if exists:
                info = client.get_collection(self.collection)
                try:
                    size = info.config.params.vectors.size
                except Exception:  # noqa: BLE001
                    size = None
                if size is not None and int(size) != self.dim:
                    raise VectorStoreError(
                        f"向量集合维度 {size} 与当前 embedding 维度 {self.dim} 不一致；"
                        "请删除 Qdrant 数据目录或配置新的 QDRANT_COLLECTION 后重新入库"
                    )
            else:
                client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=self.dim, distance=models.Distance.COSINE
                    ),
                )
            self._ensured = True

    async def ensure(self) -> None:
        await asyncio.to_thread(self._ensure_sync)

    async def upsert(self, points: Iterable[VectorPoint]) -> None:
        await self.ensure()
        from qdrant_client import models

        payloads = []
        for point in points:
            if len(point.vector) != self.dim:
                raise VectorStoreError(
                    f"向量维度不一致：期望 {self.dim}，实际 {len(point.vector)}"
                )
            payloads.append(
                models.PointStruct(
                    id=str(uuid.uuid5(_POINT_NAMESPACE, point.id)),
                    vector=list(point.vector),
                    payload={**dict(point.payload or {}), "chunk_id": point.payload.get("chunk_id", point.id)},
                )
            )
        if not payloads:
            return

        def _run() -> None:
            with self._lock:
                self._get_client().upsert(collection_name=self.collection, points=payloads)

        await asyncio.to_thread(_run)

    async def search(self, kb_ids: List[str], vector: List[float], limit: int = 8) -> List[SearchHit]:
        if not kb_ids:
            return []
        await self.ensure()
        from qdrant_client import models

        query_filter = models.Filter(
            must=[models.FieldCondition(key="kb_id", match=models.MatchAny(any=list(kb_ids)))]
        )

        def _run() -> List[SearchHit]:
            with self._lock:
                result = self._get_client().query_points(
                    collection_name=self.collection,
                    query=list(vector),
                    query_filter=query_filter,
                    limit=max(1, int(limit)),
                    with_payload=True,
                )
            hits = []
            for item in getattr(result, "points", []) or []:
                payload = dict(item.payload or {})
                hits.append(
                    SearchHit(
                        chunk_id=str(payload.get("chunk_id") or item.id),
                        score=float(item.score or 0.0),
                        payload=payload,
                    )
                )
            return hits

        return await asyncio.to_thread(_run)

    async def delete_doc(self, doc_id: str) -> None:
        await self.ensure()
        from qdrant_client import models

        selector = models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
            )
        )

        def _run() -> None:
            with self._lock:
                self._get_client().delete(
                    collection_name=self.collection, points_selector=selector
                )

        await asyncio.to_thread(_run)

    async def delete_kb(self, kb_id: str) -> None:
        await self.ensure()
        from qdrant_client import models

        selector = models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id))]
            )
        )

        def _run() -> None:
            with self._lock:
                self._get_client().delete(
                    collection_name=self.collection, points_selector=selector
                )

        await asyncio.to_thread(_run)

    async def count(self, kb_id: Optional[str] = None) -> int:
        await self.ensure()
        from qdrant_client import models

        count_filter = None
        if kb_id is not None:
            count_filter = models.Filter(
                must=[models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id))]
            )

        def _run() -> int:
            with self._lock:
                result = self._get_client().count(
                    collection_name=self.collection,
                    count_filter=count_filter,
                    exact=True,
                )
            return int(getattr(result, "count", 0) or 0)

        return await asyncio.to_thread(_run)

    async def reset(self) -> None:
        def _run() -> None:
            with self._lock:
                client = self._get_client()
                try:
                    if client.collection_exists(self.collection):
                        client.delete_collection(self.collection)
                except Exception:  # noqa: BLE001
                    try:
                        client.delete_collection(self.collection)
                    except Exception:  # noqa: BLE001
                        pass
                self._ensured = False
            self._ensure_sync()

        await asyncio.to_thread(_run)

    async def aclose(self) -> None:
        def _run() -> None:
            with self._lock:
                if self._client is not None:
                    try:
                        self._client.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self._client = None
                    self._ensured = False

        await asyncio.to_thread(_run)

# --------------------------------------------------------------------------- #
# 单例工厂
# --------------------------------------------------------------------------- #
_store: Optional[Any] = None
_store_mode: str = "none"


def get_vector_store(settings: Any = None) -> Any:
    """按配置返回 Qdrant/内存实现；Qdrant 不可用时降级为内存并记录。"""
    global _store, _store_mode
    if _store is not None:
        return _store
    if settings is None:
        from ..config import get_settings

        settings = get_settings()
    if not settings.rag_available:
        _store = MemoryVectorStore(dim=settings.embedding_dim)
        _store_mode = "none"
        return _store
    if settings.qdrant_url.strip():
        _store = QdrantVectorStore(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            collection=settings.qdrant_collection,
            dim=settings.embedding_dim,
            timeout=settings.qdrant_timeout,
        )
        _store_mode = "qdrant-server"
        return _store
    _store = QdrantVectorStore(
        path=Path(settings.qdrant_local_path),
        collection=settings.qdrant_collection,
        dim=settings.embedding_dim,
        timeout=settings.qdrant_timeout,
    )
    _store_mode = "qdrant-local"
    return _store


def current_vector_store_mode() -> str:
    return _store_mode


async def close_vector_store() -> None:
    global _store
    if _store is not None:
        try:
            await _store.aclose()
        except Exception:  # noqa: BLE001
            pass
        _store = None


async def reset_vector_store() -> None:
    """测试夹具：清空当前向量库。"""
    if _store is not None:
        await _store.reset()
