"""中文友好的分块器。

设计目标：
1. 不跨 locator（页码/幻灯片/工作表）混块，保证引用可回溯；
2. 优先在句末切分，避免把一句话拦腰截断；
3. 相邻块保留轻量重叠，缓解检索时的边界丢失；
4. 对重复块去重，防止同一段资料反复入库。
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

from .types import Chunk, TextBlock

_SENTENCE_BREAK = re.compile(r"(?<=[。！？!?；;])|\n+")
_WHITESPACE = re.compile(r"[ \t\u3000]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = _WHITESPACE.sub(" ", value)
    value = _BLANK_LINES.sub("\n\n", value)
    return value.strip()


def split_sentences(text: str) -> List[str]:
    """按中英文句末标点/换行切句；保留标点，过滤空串。"""
    parts = [part.strip() for part in _SENTENCE_BREAK.split(text) if part and part.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _hard_split(text: str, size: int) -> List[str]:
    if size <= 0:
        return [text]
    return [text[i : i + size] for i in range(0, len(text), size)]


def _pack_sentences(sentences: List[str], size: int) -> List[str]:
    """把句子装进不超过 size 的片段；超长句子硬切。"""
    pieces: List[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > size:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_hard_split(sentence, size))
            continue
        if not current:
            current = sentence
            continue
        if len(current) + len(sentence) <= size:
            current += sentence
        else:
            pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)
    return pieces


def _merge_tiny_tail(pieces: List[str], size: int, overlap: int, min_chars: int) -> List[str]:
    if len(pieces) < 2:
        return pieces
    tail = pieces[-1]
    if len(tail) >= min_chars:
        return pieces
    merged = pieces[-2] + tail
    if len(merged) <= size + overlap + 12:
        return pieces[:-2] + [merged]
    return pieces


def _chunk_block(block: TextBlock, size: int, overlap: int, min_chars: int) -> List[str]:
    text = normalize_text(block.text)
    if not text:
        return []
    sentences = split_sentences(text)
    pieces = _pack_sentences(sentences, size)
    pieces = _merge_tiny_tail(pieces, size, overlap, min_chars)
    if len(pieces) > 1:
        # 单块内重叠：把前一块尾部拼到后一块开头；不再二次扩块，避免超长。
        with_overlap: List[str] = []
        for index, piece in enumerate(pieces):
            if index == 0 or overlap <= 0:
                with_overlap.append(piece)
                continue
            prefix = pieces[index - 1][-overlap:]
            if prefix and not piece.startswith(prefix):
                with_overlap.append(prefix + piece)
            else:
                with_overlap.append(piece)
        return with_overlap
    return pieces


def chunk_blocks(
    blocks: Iterable[TextBlock],
    *,
    size: int = 600,
    overlap: int = 80,
    min_chars: int = 40,
) -> List[Chunk]:
    """把解析块切成可入库的分块；返回 seq 连续、内容去重后的 Chunk 列表。"""
    size = max(80, int(size))
    overlap = max(0, min(int(overlap), size // 2))
    min_chars = max(1, int(min_chars))

    chunks: List[Chunk] = []
    seen: set = set()
    seq = 0
    for block in blocks:
        for content in _chunk_block(block, size, overlap, min_chars):
            normalized = normalize_text(content)
            if not normalized or len(normalized) < min_chars:
                # 极短块只在它是整篇唯一内容时保留
                if not chunks and normalized:
                    pass
                else:
                    continue
            fingerprint = "".join(normalized.split())
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            seq += 1
            chunks.append(
                Chunk(
                    seq=seq,
                    content=normalized,
                    locator=block.locator,
                    meta=dict(block.meta or {}),
                )
            )
    return chunks


def chunks_to_payload(chunks: List[Chunk], *, title: str) -> List[dict]:
    """转成向量库 payload 的纯数据形式，避免上层重复拼装。"""
    return [
        {
            "chunk_id": f"chunk_{chunk.seq}",
            "seq": chunk.seq,
            "text": chunk.content,
            "locator": chunk.locator,
            "title": title,
            "meta": chunk.meta,
        }
        for chunk in chunks
    ]


def truncate_text(text: str, limit: int) -> str:
    value = str(text or "")
    if limit <= 0 or len(value) <= limit:
        return value
    return value[:limit]


def find_locator(text: str, locator: Optional[str]) -> str:
    return locator or ""