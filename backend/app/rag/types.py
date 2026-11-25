"""RAG 领域类型：解析块、分块结果、检索命中与证据包。

这些类型不依赖 FastAPI / 数据库，便于单测和后续替换实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TextBlock:
    """解析后的一段文本；locator 用于回溯（页码/幻灯片/工作表/段落）。"""

    text: str
    locator: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    title: str
    blocks: List[TextBlock] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks if block.text.strip())

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class Chunk:
    seq: int
    content: str
    locator: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.content)


@dataclass
class SearchHit:
    chunk_id: str
    score: float
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceChunk:
    chunk_id: str
    doc_id: str
    kb_id: str
    doc_title: str
    locator: str
    content: str
    score: float
    ref: str

    def public_dict(self, snippet: int = 240) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "locator": self.locator,
            "content": self.content[:snippet],
            "score": round(float(self.score), 4),
        }


@dataclass
class EvidencePack:
    chunks: List[EvidenceChunk] = field(default_factory=list)
    web_sources: List[Any] = field(default_factory=list)
    queries: List[str] = field(default_factory=list)
    rounds: int = 0
    mode: str = "kb_only"
    fallback: bool = False
    trace: Dict[str, Any] = field(default_factory=dict)

    @property
    def allowed_refs(self) -> List[str]:
        return [chunk.ref for chunk in self.chunks if chunk.ref]

    @property
    def total_chars(self) -> int:
        return sum(len(chunk.content) for chunk in self.chunks)

    def summary(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "rounds": self.rounds,
            "queries": self.queries[:6],
            "chunks": len(self.chunks),
            "web_sources": len(self.web_sources),
            "fallback": self.fallback,
        }


def evidence_ref(doc_id: str, seq: int) -> str:
    """知识库片段的稳定引用格式；不暴露内部文件路径。"""
    return f"kb://{doc_id}/chunk/{seq}"


def parse_evidence_ref(ref: str) -> Optional[tuple]:
    if not ref or not ref.startswith("kb://"):
        return None
    rest = ref[len("kb://") :]
    if "/chunk/" not in rest:
        return None
    doc_id, _, seq = rest.partition("/chunk/")
    try:
        return doc_id, int(seq)
    except (TypeError, ValueError):
        return None