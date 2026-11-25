"""向量库测试：内存实现与 Qdrant 本地实现同契约。"""

from __future__ import annotations

import pytest

from app.rag.vector_store import (
    MemoryVectorStore,
    QdrantVectorStore,
    VectorPoint,
    VectorStoreError,
)


def _points():
    return [
        VectorPoint(
            id="c1",
            vector=[1.0, 0.0, 0.0, 0.0],
            payload={"kb_id": "kb1", "doc_id": "doc1", "chunk_id": "c1", "text": "强缓存"},
        ),
        VectorPoint(
            id="c2",
            vector=[0.0, 1.0, 0.0, 0.0],
            payload={"kb_id": "kb1", "doc_id": "doc1", "chunk_id": "c2", "text": "协商缓存"},
        ),
        VectorPoint(
            id="c3",
            vector=[0.0, 0.0, 1.0, 0.0],
            payload={"kb_id": "kb2", "doc_id": "doc2", "chunk_id": "c3", "text": "细胞呼吸"},
        ),
    ]


async def _exercise(store):
    await store.ensure()
    await store.upsert(_points())
    assert await store.count() == 3
    assert await store.count(kb_id="kb1") == 2

    hits = await store.search(["kb1"], [1.0, 0.0, 0.0, 0.0], limit=5)
    assert len(hits) == 2
    assert hits[0].payload["chunk_id"] == "c1"
    assert hits[0].score > hits[1].score

    # 空 kb 列表不得搜索全部数据
    assert await store.search([], [1.0, 0.0, 0.0, 0.0], limit=5) == []

    await store.delete_doc("doc1")
    assert await store.count(kb_id="kb1") == 0
    assert await store.count(kb_id="kb2") == 1

    await store.delete_kb("kb2")
    assert await store.count() == 0


@pytest.mark.asyncio
async def test_memory_vector_store_contract():
    store = MemoryVectorStore(dim=4)
    await _exercise(store)


@pytest.mark.asyncio
async def test_qdrant_local_vector_store_contract(tmp_path):
    store = QdrantVectorStore(
        path=tmp_path / "qdrant",
        collection="test_chunks",
        dim=4,
    )
    try:
        await _exercise(store)
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_qdrant_local_persists_across_reopen(tmp_path):
    path = tmp_path / "qdrant_persist"
    first = QdrantVectorStore(path=path, collection="persist", dim=4)
    await first.ensure()
    await first.upsert(_points())
    await first.aclose()

    second = QdrantVectorStore(path=path, collection="persist", dim=4)
    try:
        hits = await second.search(["kb2"], [0.0, 0.0, 1.0, 0.0], limit=2)
        assert len(hits) == 1
        assert hits[0].payload["text"] == "细胞呼吸"
    finally:
        await second.aclose()


@pytest.mark.asyncio
async def test_qdrant_dimension_mismatch_raises(tmp_path):
    path = tmp_path / "qdrant_dim"
    first = QdrantVectorStore(path=path, collection="dim", dim=4)
    await first.ensure()
    await first.upsert(_points())
    await first.aclose()

    second = QdrantVectorStore(path=path, collection="dim", dim=8)
    with pytest.raises(VectorStoreError):
        await second.ensure()
    await second.aclose()


@pytest.mark.asyncio
async def test_memory_dimension_mismatch_raises():
    store = MemoryVectorStore(dim=4)
    with pytest.raises(VectorStoreError):
        await store.upsert([VectorPoint(id="x", vector=[1.0, 0.0], payload={"kb_id": "k"})])


@pytest.mark.asyncio
async def test_qdrant_reset_clears_collection(tmp_path):
    store = QdrantVectorStore(path=tmp_path / "qdrant_reset", collection="reset", dim=4)
    try:
        await store.ensure()
        await store.upsert(_points())
        assert await store.count() == 3
        await store.reset()
        assert await store.count() == 0
    finally:
        await store.aclose()