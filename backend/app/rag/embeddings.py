"""Embedding 适配：OpenAI 兼容网关 + 确定性哈希降级。

真实模式复用现有 MaaS 网关的 `qwen3.7-text-embedding-flash`（1024 维）；
无 Key / Mock / CI 时使用哈希向量，保证离线可跑、结果确定。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """向量化失败；消息可直接展示给用户。"""


class BaseEmbeddingClient:
    model: str = "hash"
    dim: int = 1024

    async def embed(self, texts: List[str]) -> List[List[float]]:  # pragma: no cover - 接口
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class HashEmbeddingClient(BaseEmbeddingClient):
    """字符 n-gram 哈希向量：不调用网络，适合测试/离线演示。

    质量明显低于真实 embedding，但能保证：
    - 相同文本得到相同向量；
    - 中文按字符/二元组参与，短查询与长文档有基本重叠；
    - 向量 L2 归一化，可直接余弦检索。
    """

    def __init__(self, dim: int = 1024) -> None:
        self.dim = max(8, int(dim))
        self.model = "hash-char-ngram"

    def _vector(self, text: str) -> List[float]:
        value = " ".join(str(text or "").lower().split())
        vector = [0.0] * self.dim
        if not value:
            vector[0] = 1.0
            return vector
        tokens: List[tuple] = []
        for char in value:
            if not char.isspace():
                tokens.append((char, 0.5))
        compact = "".join(value.split())
        for index in range(len(compact) - 1):
            tokens.append((compact[index : index + 2], 1.0))
        for token, weight in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            number = int.from_bytes(digest, "big")
            slot = number % self.dim
            sign = 1.0 if (number >> 63) & 1 else -1.0
            vector[slot] += sign * weight
        norm = math.sqrt(sum(item * item for item in vector))
        if norm <= 1e-9:
            vector[0] = 1.0
            return vector
        return [round(item / norm, 8) for item in vector]

    async def embed(self, texts: List[str]) -> List[List[float]]:
        return [self._vector(text) for text in texts]


class OpenAIEmbeddingClient(BaseEmbeddingClient):
    """OpenAI 兼容 `/embeddings`；支持批量、重试、维度校验。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dim: int = 1024,
        batch_size: int = 16,
        timeout: float = 30.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = model or "text-embedding"
        self.dim = int(dim or 1024)
        self.batch_size = max(1, int(batch_size))
        self.timeout = float(timeout)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=8.0),
        )
        self.last_usage: Dict[str, Any] = {}

    @property
    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise EmbeddingError("Embedding API Key 未配置")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def embed(self, texts: List[str]) -> List[List[float]]:
        cleaned = [str(text or "") for text in texts]
        if not cleaned:
            return []
        vectors: List[List[float]] = []
        for start in range(0, len(cleaned), self.batch_size):
            batch = cleaned[start : start + self.batch_size]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        payload = {"model": self.model, "input": batch}
        last_error: Optional[EmbeddingError] = None
        for attempt in range(3):
            try:
                response = await self._client.post(
                    "/embeddings", json=payload, headers=self._headers
                )
            except httpx.HTTPError as exc:
                last_error = EmbeddingError(f"Embedding 网络错误：{str(exc)[:100]}")
                if attempt < 2:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                raise last_error from exc

            status = response.status_code
            if status == 401 or status == 403:
                raise EmbeddingError("Embedding API Key 无效或无权限，请检查后端配置")
            if status == 402:
                raise EmbeddingError("Embedding 账户余额不足，请检查网关配额")
            if status == 429 or status >= 500:
                last_error = EmbeddingError(f"Embedding 服务繁忙（{status}），请稍后重试")
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise last_error
            if status != 200:
                raise EmbeddingError(f"Embedding 请求失败（{status}）：{response.text[:120]}")

            try:
                data = response.json() or {}
            except ValueError as exc:
                raise EmbeddingError("Embedding 返回非 JSON") from exc
            items = data.get("data")
            if not isinstance(items, list) or len(items) != len(batch):
                raise EmbeddingError("Embedding 返回数量与输入不一致")
            ordered = sorted(
                enumerate(items),
                key=lambda pair: int((pair[1] or {}).get("index", pair[0])),
            )
            output: List[List[float]] = []
            for _, item in ordered:
                vector = (item or {}).get("embedding")
                if not isinstance(vector, list) or not vector:
                    raise EmbeddingError("Embedding 返回空向量")
                if len(vector) != self.dim:
                    raise EmbeddingError(
                        f"Embedding 维度不一致：期望 {self.dim}，实际 {len(vector)}"
                    )
                output.append([float(value) for value in vector])
            usage = data.get("usage")
            if isinstance(usage, dict):
                self.last_usage = usage
            return output
        raise last_error or EmbeddingError("Embedding 调用失败")


class UnavailableEmbeddingClient(BaseEmbeddingClient):
    """显式关闭 RAG 时的空实现（保留接口，便于上层统一处理）。"""

    model = "disabled"
    dim = 1

    async def embed(self, texts: List[str]) -> List[List[float]]:
        if texts:
            raise EmbeddingError("知识库向量化未启用")
        return []

# --------------------------------------------------------------------------- #
# 单例工厂
# --------------------------------------------------------------------------- #
_embedding: Optional[BaseEmbeddingClient] = None


def create_embedding_client(settings: Any) -> BaseEmbeddingClient:
    provider = settings.effective_embedding_provider
    if provider == "none":
        return UnavailableEmbeddingClient()
    if provider == "mock":
        return HashEmbeddingClient(dim=settings.embedding_dim)
    return OpenAIEmbeddingClient(
        base_url=settings.embedding_base_url_effective,
        api_key=settings.embedding_api_key_effective,
        model=settings.embedding_model,
        dim=settings.embedding_dim,
        batch_size=settings.embedding_batch_size,
        timeout=settings.embedding_timeout,
    )


def get_embedding_client() -> BaseEmbeddingClient:
    global _embedding
    if _embedding is None:
        from ..config import get_settings

        _embedding = create_embedding_client(get_settings())
        logger.info(
            "Embedding 初始化: provider=%s model=%s dim=%s",
            get_settings().effective_embedding_provider,
            _embedding.model,
            _embedding.dim,
        )
    return _embedding


async def close_embeddings() -> None:
    global _embedding
    if _embedding is not None:
        await _embedding.aclose()
        _embedding = None
