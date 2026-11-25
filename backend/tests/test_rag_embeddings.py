"""Embedding 客户端测试：请求形状、批量、维度、重试与哈希降级。"""

from __future__ import annotations

import httpx
import pytest

from app.rag.embeddings import (
    EmbeddingError,
    HashEmbeddingClient,
    OpenAIEmbeddingClient,
)


@pytest.mark.asyncio
async def test_hash_embedding_is_deterministic_and_normalized():
    client = HashEmbeddingClient(dim=64)
    first = await client.embed(["HTTP 强缓存", "细胞呼吸"])
    second = await client.embed(["HTTP 强缓存", "细胞呼吸"])
    assert first == second
    assert len(first) == 2
    assert all(len(vector) == 64 for vector in first)
    assert first[0] != first[1]
    norm = sum(value * value for value in first[0]) ** 0.5
    assert abs(norm - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_hash_embedding_empty_input():
    client = HashEmbeddingClient(dim=16)
    assert await client.embed([]) == []


@pytest.mark.asyncio
async def test_openai_embedding_request_shape_and_order():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["payload"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                    {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                ],
                "model": "test-embedding",
                "usage": {"prompt_tokens": 4},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://gateway.test/v1") as http:
        client = OpenAIEmbeddingClient(
            base_url="https://gateway.test/v1",
            api_key="sk-test",
            model="test-embedding",
            dim=3,
            client=http,
        )
        vectors = await client.embed(["第一段", "第二段"])

    assert seen["url"].endswith("/embeddings")
    assert seen["auth"] == "Bearer sk-test"
    import json

    assert json.loads(seen["payload"])["input"] == ["第一段", "第二段"]
    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


@pytest.mark.asyncio
async def test_openai_embedding_batches_requests():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.read().decode("utf-8"))
        calls.append(payload["input"])
        data = [
            {"index": index, "embedding": [float(index), 0.0]}
            for index, _ in enumerate(payload["input"])
        ]
        return httpx.Response(200, json={"data": data})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://gateway.test/v1") as http:
        client = OpenAIEmbeddingClient(
            base_url="https://gateway.test/v1",
            api_key="sk-test",
            model="test-embedding",
            dim=2,
            batch_size=2,
            client=http,
        )
        vectors = await client.embed(["a", "b", "c", "d", "e"])

    assert [len(batch) for batch in calls] == [2, 2, 1]
    assert len(vectors) == 5


@pytest.mark.asyncio
async def test_openai_embedding_dimension_mismatch():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]})
    )
    async with httpx.AsyncClient(transport=transport, base_url="https://gateway.test/v1") as http:
        client = OpenAIEmbeddingClient(
            base_url="https://gateway.test/v1",
            api_key="sk-test",
            model="test-embedding",
            dim=3,
            client=http,
        )
        with pytest.raises(EmbeddingError) as exc:
            await client.embed(["x"])
    assert "维度" in str(exc.value)


@pytest.mark.asyncio
async def test_openai_embedding_retries_429(monkeypatch):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    async def fast_sleep(_):
        return None

    monkeypatch.setattr("app.rag.embeddings.asyncio.sleep", fast_sleep)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://gateway.test/v1") as http:
        client = OpenAIEmbeddingClient(
            base_url="https://gateway.test/v1",
            api_key="sk-test",
            model="test-embedding",
            dim=2,
            client=http,
        )
        vectors = await client.embed(["x"])
    assert attempts["n"] == 2
    assert vectors == [[1.0, 0.0]]


@pytest.mark.asyncio
async def test_openai_embedding_auth_error_is_friendly():
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "unauthorized"}))
    async with httpx.AsyncClient(transport=transport, base_url="https://gateway.test/v1") as http:
        client = OpenAIEmbeddingClient(
            base_url="https://gateway.test/v1",
            api_key="sk-test",
            model="test-embedding",
            dim=2,
            client=http,
        )
        with pytest.raises(EmbeddingError) as exc:
            await client.embed(["x"])
    assert "Key" in str(exc.value) or "鉴权" in str(exc.value)


@pytest.mark.asyncio
async def test_openai_embedding_empty_input_no_request():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://gateway.test/v1") as http:
        client = OpenAIEmbeddingClient(
            base_url="https://gateway.test/v1",
            api_key="sk-test",
            model="test-embedding",
            dim=2,
            client=http,
        )
        assert await client.embed([]) == []
    assert calls["n"] == 0