"""Agentic 检索编排测试：规划、融合、充分性判断、改写、降级与引用。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.rag.embeddings import HashEmbeddingClient
from app.rag.retriever import (
    RagError,
    build_source_items,
    format_kb_evidence,
    retrieve,
    select_evidence,
)
from app.rag.types import SearchHit
from app.rag.vector_store import MemoryVectorStore, VectorPoint


class FakeLLM:
    def __init__(self, plan=None, verdicts=None):
        self.plan = plan or {"queries": ["q1", "q2"], "focus": []}
        self.verdicts = list(verdicts or [{"sufficient": True, "missing": [], "refined_query": ""}])
        self.calls = []

    async def run(self, task, variables, context=None, **kwargs):
        self.calls.append((task, dict(variables), dict(context or {})))
        if task == "rag_plan":
            return SimpleNamespace(data=self.plan, tokens_in=0, tokens_out=0, cost_cny=0.0, model="fake")
        if task == "rag_evaluate":
            verdict = self.verdicts.pop(0) if self.verdicts else {"sufficient": True}
            return SimpleNamespace(data=verdict, tokens_in=0, tokens_out=0, cost_cny=0.0, model="fake")
        raise AssertionError(f"unexpected task {task}")


class FakeEmbedder:
    def __init__(self, mapping=None, fail=False):
        self.mapping = mapping or {}
        self.fail = fail
        self.calls = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("embedding down")
        return [self.mapping.get(text, [0.0, 0.0, 0.0]) for text in texts]


class FakeSearch:
    def __init__(self, items=None):
        self.items = items or []

    async def search_many(self, topic, per_query=4):
        return list(self.items)


def _store():
    store = MemoryVectorStore(dim=3)
    return store


async def _seed(store):
    await store.ensure()
    await store.upsert(
        [
            VectorPoint(
                id="chk1",
                vector=[1.0, 0.0, 0.0],
                payload={
                    "kb_id": "kb1",
                    "doc_id": "doc1",
                    "chunk_id": "chk1",
                    "seq": 1,
                    "text": "强缓存直接读取本地副本，状态码 200。",
                    "locator": "第 1 页",
                    "title": "HTTP 缓存",
                },
            ),
            VectorPoint(
                id="chk2",
                vector=[0.0, 1.0, 0.0],
                payload={
                    "kb_id": "kb1",
                    "doc_id": "doc1",
                    "chunk_id": "chk2",
                    "seq": 2,
                    "text": "协商缓存会向服务器确认，未变化返回 304。",
                    "locator": "第 2 页",
                    "title": "HTTP 缓存",
                },
            ),
            VectorPoint(
                id="chk3",
                vector=[0.0, 0.0, 1.0],
                payload={
                    "kb_id": "kb2",
                    "doc_id": "doc2",
                    "chunk_id": "chk3",
                    "seq": 1,
                    "text": "细胞呼吸分为三个阶段。",
                    "locator": "第 1 页",
                    "title": "细胞呼吸",
                },
            ),
        ]
    )


@pytest.mark.asyncio
async def test_retrieve_returns_kb_evidence_and_trace():
    store = _store()
    await _seed(store)
    embedder = FakeEmbedder({"q1": [1.0, 0.0, 0.0], "q2": [0.0, 1.0, 0.0]})
    llm = FakeLLM()
    pack = await retrieve(
        "HTTP 缓存",
        ["kb1"],
        "kb_only",
        llm=llm,
        embedder=embedder,
        store=store,
        settings=SimpleNamespace(
            rag_max_rounds=2,
            kb_retrieve_top_k=4,
            kb_retrieve_candidates=4,
            kb_evidence_max_chars=2000,
        ),
    )
    assert len(pack.chunks) == 2
    assert {chunk.doc_id for chunk in pack.chunks} == {"doc1"}
    assert all(chunk.ref.startswith("kb://doc1/chunk/") for chunk in pack.chunks)
    assert pack.rounds == 1
    assert pack.queries == ["q1", "q2"]
    assert pack.trace["selected"]
    assert pack.summary()["chunks"] == 2


@pytest.mark.asyncio
async def test_agentic_second_round_after_insufficient_verdict():
    store = _store()
    await _seed(store)
    embedder = FakeEmbedder(
        {"q1": [1.0, 0.0, 0.0], "q2": [0.0, 1.0, 0.0], "补充查询": [0.0, 0.0, 1.0]}
    )
    llm = FakeLLM(
        verdicts=[
            {"sufficient": False, "missing": ["细胞呼吸"], "refined_query": "补充查询"},
            {"sufficient": True, "missing": [], "refined_query": ""},
        ]
    )
    pack = await retrieve(
        "HTTP 缓存",
        ["kb1", "kb2"],
        "kb_only",
        llm=llm,
        embedder=embedder,
        store=store,
        settings=SimpleNamespace(
            rag_max_rounds=2,
            kb_retrieve_top_k=4,
            kb_retrieve_candidates=4,
            kb_evidence_max_chars=2000,
        ),
    )
    assert pack.rounds == 2
    assert "补充查询" in pack.queries
    assert any("细胞呼吸" in chunk.content for chunk in pack.chunks)


@pytest.mark.asyncio
async def test_kb_only_empty_raises_actionable_error():
    store = _store()
    await store.ensure()
    with pytest.raises(RagError) as exc:
        await retrieve(
            "不存在的主题",
            ["kb1"],
            "kb_only",
            llm=FakeLLM(plan={"queries": ["x"]}),
            embedder=FakeEmbedder({"x": [1.0, 0.0, 0.0]}),
            store=store,
            settings=SimpleNamespace(
                rag_max_rounds=1,
                kb_retrieve_top_k=4,
                kb_retrieve_candidates=4,
                kb_evidence_max_chars=2000,
            ),
        )
    assert "资料库" in str(exc.value)


@pytest.mark.asyncio
async def test_hybrid_merges_web_sources():
    store = _store()
    await _seed(store)
    web_item = SimpleNamespace(
        title="缓存最佳实践",
        url="https://example.com/cache",
        site_name="example.com",
        summary="强缓存与协商缓存的组合策略。",
    )
    pack = await retrieve(
        "HTTP 缓存",
        ["kb1"],
        "hybrid",
        llm=FakeLLM(plan={"queries": ["q1"]}),
        embedder=FakeEmbedder({"q1": [1.0, 0.0, 0.0]}),
        store=store,
        search_client=FakeSearch([web_item]),
        settings=SimpleNamespace(
            rag_max_rounds=1,
            kb_retrieve_top_k=4,
            kb_retrieve_candidates=4,
            kb_evidence_max_chars=2000,
        ),
    )
    assert len(pack.web_sources) == 1
    sources = build_source_items(pack, {"kb1": "前端资料库"})
    kinds = {source.kind for source in sources}
    assert "kb" in kinds and "web" in kinds
    assert any(source.site_name and "前端资料库" in source.site_name for source in sources)


@pytest.mark.asyncio
async def test_lexical_fallback_when_embedding_fails():
    async def lexical(kb_ids, query, limit):
        return [
            {
                "kb_id": "kb1",
                "doc_id": "doc1",
                "chunk_id": "chk1",
                "seq": 1,
                "text": "强缓存直接读取本地副本。",
                "locator": "第 1 页",
                "title": "HTTP 缓存",
                "score": 0.5,
            }
        ]

    pack = await retrieve(
        "HTTP 缓存",
        ["kb1"],
        "kb_only",
        llm=FakeLLM(plan={"queries": ["q1"]}),
        embedder=FakeEmbedder(fail=True),
        store=MemoryVectorStore(dim=3),
        lexical_search=lexical,
        settings=SimpleNamespace(
            rag_max_rounds=1,
            kb_retrieve_top_k=4,
            kb_retrieve_candidates=4,
            kb_evidence_max_chars=2000,
        ),
    )
    assert pack.fallback is True
    assert len(pack.chunks) == 1
    assert "强缓存" in pack.chunks[0].content


def test_format_kb_evidence_includes_ref_and_locator():
    from app.rag.types import EvidenceChunk

    text = format_kb_evidence(
        [
            EvidenceChunk(
                chunk_id="chk1",
                doc_id="doc1",
                kb_id="kb1",
                doc_title="HTTP 缓存",
                locator="第 1 页",
                content="强缓存直接读取本地副本。",
                score=0.9,
                ref="kb://doc1/chunk/1",
            )
        ]
    )
    assert "ref=kb://doc1/chunk/1" in text
    assert "第 1 页" in text
    assert "强缓存" in text


def test_select_evidence_dedupes_and_caps_chars():
    from app.rag.types import SearchHit

    hits = {
        "a": SearchHit(
            chunk_id="a",
            score=0.9,
            payload={
                "kb_id": "kb1",
                "doc_id": "doc1",
                "chunk_id": "a",
                "seq": 1,
                "text": "强缓存直接读取本地副本，不会向服务器发请求。" * 20,
                "locator": "第 1 页",
                "title": "HTTP 缓存",
            },
        ),
        "b": SearchHit(
            chunk_id="b",
            score=0.8,
            payload={
                "kb_id": "kb1",
                "doc_id": "doc1",
                "chunk_id": "b",
                "seq": 2,
                "text": "强缓存直接读取本地副本，不会向服务器发请求。" * 20,
                "locator": "第 1 页",
                "title": "HTTP 缓存",
            },
        ),
        "c": SearchHit(
            chunk_id="c",
            score=0.7,
            payload={
                "kb_id": "kb1",
                "doc_id": "doc1",
                "chunk_id": "c",
                "seq": 3,
                "text": "协商缓存返回 304。",
                "locator": "第 2 页",
                "title": "HTTP 缓存",
            },
        ),
    }
    selected = select_evidence(hits, top_k=5, max_chars=80)
    assert [chunk.chunk_id for chunk in selected] == ["a"]
    assert sum(len(chunk.content) for chunk in selected) <= 80


@pytest.mark.asyncio
async def test_plan_falls_back_when_llm_fails():
    class BrokenLLM:
        async def run(self, *args, **kwargs):
            raise RuntimeError("llm down")

    store = _store()
    await _seed(store)
    pack = await retrieve(
        "HTTP 缓存",
        ["kb1"],
        "kb_only",
        llm=BrokenLLM(),
        embedder=HashEmbeddingClient(dim=3),
        store=store,
        settings=SimpleNamespace(
            rag_max_rounds=1,
            kb_retrieve_top_k=4,
            kb_retrieve_candidates=4,
            kb_evidence_max_chars=2000,
        ),
    )
    assert pack.queries
    assert any("HTTP 缓存" in query for query in pack.queries)


@pytest.mark.asyncio
async def test_retrieve_without_kb_ids_raises():
    with pytest.raises(RagError):
        await retrieve(
            "x",
            [],
            "kb_only",
            llm=FakeLLM(),
            embedder=FakeEmbedder(),
            store=MemoryVectorStore(dim=3),
            settings=SimpleNamespace(
                rag_max_rounds=1,
                kb_retrieve_top_k=4,
                kb_retrieve_candidates=4,
                kb_evidence_max_chars=2000,
            ),
        )

def test_normalize_question_maps_k_index_to_real_ref():
    from app.services.question_gen import normalize_question

    question = normalize_question(
        {
            "type": "single_choice",
            "stem": "关于强缓存，下列说法正确的是？",
            "options": [
                {"key": "A", "text": "强缓存直接读取本地副本"},
                {"key": "B", "text": "强缓存必须向服务器确认"},
                {"key": "C", "text": "强缓存总是返回 304"},
                {"key": "D", "text": "强缓存与 Cache-Control 无关"},
            ],
            "correct_answer": "A",
            "explanation": "强缓存命中时直接读取本地副本。",
            "source_refs": ["[K1]", "https://example.com/unknown"],
        },
        seq=1,
        session_id="s_test",
        allowed_urls=["kb://doc1/chunk/1", "kb://doc1/chunk/2"],
    )
    assert question is not None
    assert question["source_refs"] == ["kb://doc1/chunk/1"]


def test_normalize_question_keeps_regular_url():
    from app.services.question_gen import normalize_question

    question = normalize_question(
        {
            "type": "true_false",
            "stem": "强缓存命中时不会向服务器发请求。",
            "options": [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
            "correct_answer": "A",
            "explanation": "强缓存直接读取本地副本。",
            "source_refs": ["https://example.com/cache"],
        },
        seq=1,
        session_id="s_test",
        allowed_urls=["https://example.com/cache"],
    )
    assert question is not None
    assert question["source_refs"] == ["https://example.com/cache"]
