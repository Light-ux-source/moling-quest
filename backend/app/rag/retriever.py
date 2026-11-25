"""Agentic RAG 检索编排。

流程：规划查询 → 多查询向量检索 → RRF 融合 → 充分性判断 → 改写重检（有界）
→ 证据预算/去重 → 证据包 + 可追溯 trace。

设计约束：
- 只检索选中的知识库（kb_ids 过滤），绝不跨库；
- 最多 `RAG_MAX_ROUNDS` 轮，避免成本失控；
- Embedding/向量库失败时可用 MySQL 词法检索降级；
- 证据包只保留可引用片段，ref 格式稳定为 `kb://{doc_id}/chunk/{seq}`。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from ..config import get_settings
from ..schemas import SourceItem
from .embeddings import EmbeddingError, get_embedding_client
from .types import (
    EvidenceChunk,
    EvidencePack,
    SearchHit,
    evidence_ref,
)
from .vector_store import VectorStoreError, get_vector_store

logger = logging.getLogger(__name__)

LexicalSearch = Callable[[List[str], str, int], Awaitable[List[Dict[str, Any]]]]


class RagError(Exception):
    """知识库检索失败；消息可直接展示给用户。"""


def _as_list(value: Any, limit: int = 8) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    output = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in output:
            output.append(text[:160])
        if len(output) >= limit:
            break
    return output


def _fallback_queries(topic: str) -> List[str]:
    topic = str(topic or "").strip()[:120]
    if not topic:
        return []
    return [topic, f"{topic} 核心概念 原理", f"{topic} 常见误区 适用边界"][:3]


async def plan_queries(
    topic: str,
    kb_titles: Iterable[str],
    doc_titles: Iterable[str],
    *,
    llm: Any = None,
) -> List[str]:
    """让模型规划 2–4 个检索查询；失败/空结果时使用确定性回退。"""
    titles = "、".join([str(item) for item in kb_titles if str(item).strip()]) or "（未命名知识库）"
    docs = "、".join([str(item)[:40] for item in doc_titles if str(item).strip()][:12]) or "（暂无资料标题）"
    try:
        client = llm
        if client is None:
            from ..llm import get_llm

            client = get_llm()
        result = await client.run(
            "rag_plan",
            {"topic": topic, "kb_titles": titles, "doc_titles": docs},
            context={"topic": topic, "kb_titles": titles, "doc_titles": docs},
            temperature=0.2,
            max_tokens=600,
        )
        queries = _as_list((result.data or {}).get("queries"), limit=4)
        if queries:
            return queries
    except Exception as exc:  # noqa: BLE001 - 规划失败不应阻断检索
        logger.warning("RAG 查询规划失败，使用回退查询: %s", exc)
    return _fallback_queries(topic)


async def evaluate_evidence(topic: str, chunks: List[EvidenceChunk], *, llm: Any = None) -> Dict[str, Any]:
    """判断证据是否足够；失败时默认足够，避免无意义地多轮检索。"""
    if not chunks:
        return {"sufficient": False, "missing": [], "refined_query": ""}
    compact = [
        {
            "ref": chunk.ref,
            "doc": chunk.doc_title,
            "locator": chunk.locator,
            "content": chunk.content[:200],
        }
        for chunk in chunks[:6]
    ]
    try:
        client = llm
        if client is None:
            from ..llm import get_llm

            client = get_llm()
        result = await client.run(
            "rag_evaluate",
            {
                "topic": topic,
                "evidence_json": json.dumps(compact, ensure_ascii=False),
            },
            context={"topic": topic, "evidence": compact},
            temperature=0.1,
            max_tokens=600,
        )
        data = result.data or {}
        sufficient = data.get("sufficient")
        if isinstance(sufficient, str):
            sufficient = sufficient.strip().lower() in {"true", "1", "yes"}
        refined = str(data.get("refined_query") or "").strip()[:160]
        missing = _as_list(data.get("missing"), limit=3)
        return {
            "sufficient": bool(sufficient),
            "missing": missing,
            "refined_query": refined,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG 充分性判断失败，默认采用当前证据: %s", exc)
        return {"sufficient": True, "missing": [], "refined_query": ""}


def _trigrams(text: str) -> set:
    compact = "".join(str(text or "").split())
    if len(compact) <= 3:
        return {compact} if compact else set()
    return {compact[index : index + 3] for index in range(len(compact) - 2)}


def _jaccard(left: str, right: str) -> float:
    a, b = _trigrams(left), _trigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _hit_from_row(row: Dict[str, Any], score: float = 0.0) -> SearchHit:
    payload = dict(row or {})
    chunk_id = str(payload.get("chunk_id") or payload.get("id") or "")
    return SearchHit(chunk_id=chunk_id, score=float(score), payload=payload)


def _add_hit(fused: Dict[str, Dict[str, Any]], hit: SearchHit, rank: int) -> None:
    if not hit.chunk_id:
        return
    payload = dict(hit.payload or {})
    payload.setdefault("chunk_id", hit.chunk_id)
    entry = fused.get(hit.chunk_id)
    rrf = 1.0 / (60 + rank + 1)
    if entry is None:
        fused[hit.chunk_id] = {"score": rrf, "payload": payload}
    else:
        entry["score"] += rrf
        # 保留信息更完整的 payload
        if len(payload.get("text") or "") > len(entry["payload"].get("text") or ""):
            entry["payload"] = payload


def _entry_score(entry: Any) -> float:
    if isinstance(entry, SearchHit):
        return float(entry.score or 0.0)
    if isinstance(entry, dict):
        return float(entry.get("score") or 0.0)
    return 0.0


def _entry_payload(entry: Any) -> Dict[str, Any]:
    if isinstance(entry, SearchHit):
        return dict(entry.payload or {})
    if isinstance(entry, dict):
        return dict(entry.get("payload") or {})
    return {}


def select_evidence(
    hits: Dict[str, Any], *, top_k: int = 8, max_chars: int = 6000
) -> List[EvidenceChunk]:
    """按融合分数排序、去重、按字符预算截取，生成可引用证据。

    兼容两种输入：`{chunk_id: {"score", "payload"}}`（检索内部）与
    `{chunk_id: SearchHit}`（测试/外部适配）。
    """
    ordered = sorted(hits.items(), key=lambda pair: _entry_score(pair[1]), reverse=True)
    selected: List[EvidenceChunk] = []
    total = 0
    for chunk_id, entry in ordered:
        payload = _entry_payload(entry)
        content = str(payload.get("text") or "").strip()
        if not content:
            continue
        if any(_jaccard(content, existing.content) > 0.85 for existing in selected):
            continue
        remaining = max_chars - total
        if remaining <= 0:
            break
        if len(content) > remaining:
            if selected:
                break
            content = content[:remaining]
        doc_id = str(payload.get("doc_id") or "")
        seq = payload.get("seq")
        try:
            seq_int = int(seq)
        except (TypeError, ValueError):
            seq_int = len(selected) + 1
        if not doc_id:
            continue
        ref = str(payload.get("ref") or evidence_ref(doc_id, seq_int))
        selected.append(
            EvidenceChunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                kb_id=str(payload.get("kb_id") or ""),
                doc_title=str(payload.get("doc_title") or payload.get("title") or "未命名资料")[:160],
                locator=str(payload.get("locator") or ""),
                content=content,
                score=_entry_score(entry),
                ref=ref,
            )
        )
        total += len(content)
        if len(selected) >= max(1, int(top_k)):
            break
    return selected


async def retrieve(
    topic: str,
    kb_ids: List[str],
    mode: str,
    *,
    llm: Any = None,
    embedder: Any = None,
    store: Any = None,
    search_client: Any = None,
    lexical_search: Optional[LexicalSearch] = None,
    settings: Any = None,
    kb_titles: Optional[Iterable[str]] = None,
    doc_titles: Optional[Iterable[str]] = None,
) -> EvidencePack:
    """执行有界 Agentic 检索；kb_only 空结果抛 RagError，hybrid 允许空 KB。"""
    if not kb_ids:
        raise RagError("没有选择知识库，无法执行知识库检索")
    active = settings or get_settings()
    max_rounds = max(1, int(getattr(active, "rag_max_rounds", 2)))
    top_k = max(1, int(getattr(active, "kb_retrieve_top_k", 8)))
    candidates = max(top_k, int(getattr(active, "kb_retrieve_candidates", 16)))
    max_chars = max(500, int(getattr(active, "kb_evidence_max_chars", 6000)))

    queries = await plan_queries(topic, kb_titles or [], doc_titles or [], llm=llm)
    if not queries:
        raise RagError("无法为这个主题规划检索查询，请换一个更具体的说法")

    active_embedder = embedder or get_embedding_client()
    active_store = store or get_vector_store(active)
    fused: Dict[str, Dict[str, Any]] = {}
    all_queries: List[str] = []
    rounds = 0
    fallback = False
    selected: List[EvidenceChunk] = []

    for round_index in range(max_rounds):
        rounds = round_index + 1
        all_queries.extend(queries)
        try:
            vectors = await active_embedder.embed(queries)
            for query, vector in zip(queries, vectors):
                hits = await active_store.search(kb_ids, vector, limit=candidates)
                for rank, hit in enumerate(hits):
                    _add_hit(fused, hit, rank)
        except (EmbeddingError, VectorStoreError, Exception) as exc:  # noqa: BLE001
            logger.warning("向量检索失败，尝试词法降级: %s", exc)
            if lexical_search is None:
                raise RagError("知识库检索暂时不可用，请稍后重试") from exc
            fallback = True
            for query in queries:
                try:
                    rows = await lexical_search(kb_ids, query, candidates)
                except Exception as lexical_exc:  # noqa: BLE001
                    logger.warning("词法检索也失败: %s", lexical_exc)
                    rows = []
                for rank, row in enumerate(rows):
                    _add_hit(fused, _hit_from_row(row), rank)

        selected = select_evidence(fused, top_k=top_k, max_chars=max_chars)
        if not selected:
            break
        verdict = await evaluate_evidence(topic, selected, llm=llm)
        if verdict.get("sufficient") or round_index >= max_rounds - 1:
            break
        refined = str(verdict.get("refined_query") or "").strip()
        missing = _as_list(verdict.get("missing"), limit=2)
        next_queries = [query for query in [refined] + missing if query]
        queries = next_queries[:3] or [f"{topic} 补充说明"]

    if not selected:
        if mode == "hybrid":
            web_sources = await _web_sources(topic, search_client)
            return EvidencePack(
                chunks=[],
                web_sources=web_sources,
                queries=all_queries,
                rounds=rounds,
                mode=mode,
                fallback=fallback,
                trace={"rounds": rounds, "queries": all_queries[:8], "chunks": 0, "fallback": fallback},
            )
        raise RagError(
            "资料库里没有检索到与这个主题相关的内容。可以换一个更具体的说法，或先在资料库补充资料。"
        )

    web_sources = await _web_sources(topic, search_client) if mode == "hybrid" else []
    trace = {
        "mode": mode,
        "rounds": rounds,
        "queries": all_queries[:8],
        "candidates": len(fused),
        "selected": [chunk.chunk_id for chunk in selected],
        "fallback": fallback,
        "web_sources": len(web_sources),
    }
    return EvidencePack(
        chunks=selected,
        web_sources=web_sources,
        queries=all_queries,
        rounds=rounds,
        mode=mode,
        fallback=fallback,
        trace=trace,
    )


async def _web_sources(topic: str, search_client: Any) -> List[Any]:
    client = search_client
    if client is None:
        try:
            from ..search import get_search

            client = get_search()
        except Exception:  # noqa: BLE001
            return []
    try:
        return list(await client.search_many(topic, per_query=4) or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG 联网补充失败，继续使用知识库: %s", exc)
        return []


def format_kb_evidence(chunks: List[EvidenceChunk]) -> str:
    if not chunks:
        return "（本次没有检索到知识库片段）"
    blocks = []
    for index, chunk in enumerate(chunks, 1):
        title = chunk.doc_title or "未命名资料"
        locator = f" | {chunk.locator}" if chunk.locator else ""
        blocks.append(
            f"[K{index}] ref={chunk.ref} | 《{title}》{locator}\n{chunk.content}"
        )
    return "\n\n".join(blocks)


def format_web_evidence(sources: List[Any]) -> str:
    if not sources:
        return "（本次没有联网补充资料）"
    lines = []
    for index, source in enumerate(sources[:8], 1):
        title = getattr(source, "title", "") or ""
        site = getattr(source, "site_name", "") or "未知站点"
        summary = getattr(source, "summary", "") or ""
        url = getattr(source, "url", "") or ""
        lines.append(f"[W{index}] {title}（{site}）\n{url}\n{summary}")
    return "\n\n".join(lines)


def build_source_items(pack: EvidencePack, kb_names: Dict[str, str]) -> List[SourceItem]:
    items: List[SourceItem] = []
    seen = set()
    for chunk in pack.chunks:
        if chunk.ref in seen:
            continue
        seen.add(chunk.ref)
        kb_name = kb_names.get(chunk.kb_id) or "知识库"
        title = f"《{chunk.doc_title}》{chunk.locator}".strip()
        items.append(
            SourceItem(
                title=title[:160],
                url=chunk.ref,
                site_name=f"知识库 · {kb_name}"[:80],
                summary=chunk.content[:300],
                kind="kb",
                ref=chunk.ref,
                kb_id=chunk.kb_id,
                doc_id=chunk.doc_id,
                locator=chunk.locator,
            )
        )
    for source in pack.web_sources:
        if hasattr(source, "model_dump"):
            data = source.model_dump()
        elif isinstance(source, dict):
            data = dict(source)
        else:
            data = {
                key: getattr(source, key, None)
                for key in ("title", "url", "site_name", "summary")
            }
        url = str(data.get("url") or "")
        key = url or str(data.get("title") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(
            SourceItem(
                title=str(data.get("title") or "未命名来源")[:160],
                url=url[:500],
                site_name=data.get("site_name"),
                summary=str(data.get("summary") or "")[:800],
                kind="web",
            )
        )
    return items