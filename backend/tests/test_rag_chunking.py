"""分块器单元测试：中文长度、重叠、定位信息、边界与去重。"""

from __future__ import annotations

from app.rag.chunking import chunk_blocks
from app.rag.types import TextBlock


def _joined(chunks) -> str:
    return "".join(c.content for c in chunks)


def test_empty_blocks_returns_empty_list():
    assert chunk_blocks([]) == []


def test_short_text_returns_single_chunk():
    chunks = chunk_blocks([TextBlock("HTTP 缓存分为强缓存和协商缓存。", locator="第 1 段")])
    assert len(chunks) == 1
    assert chunks[0].seq == 1
    assert "强缓存" in chunks[0].content
    assert chunks[0].locator == "第 1 段"


def test_long_chinese_text_is_split_with_overlap():
    text = "。".join(f"第{i}个知识点说明" for i in range(1, 200)) + "。"
    chunks = chunk_blocks([TextBlock(text)], size=200, overlap=40, min_chars=20)
    assert len(chunks) > 1
    assert all(c.content for c in chunks)
    # 每个块不超过 size + overlap 的合理上界
    assert all(len(c.content) <= 240 for c in chunks)
    # 相邻块存在重叠（取前一块尾部 16 字）
    for prev, nxt in zip(chunks, chunks[1:]):
        assert prev.content[-16:] in nxt.content


def test_chunks_do_not_mix_locators():
    blocks = [
        TextBlock("第一页的内容。" * 40, locator="第 1 页"),
        TextBlock("第二页的内容。" * 40, locator="第 2 页"),
    ]
    chunks = chunk_blocks(blocks, size=300, overlap=50, min_chars=20)
    page1 = [c for c in chunks if c.locator == "第 1 页"]
    page2 = [c for c in chunks if c.locator == "第 2 页"]
    assert page1 and page2
    assert all("第二页" not in c.content for c in page1)
    assert all("第一页" not in c.content for c in page2)


def test_sentence_boundary_preferred():
    text = "。".join(["这是一个完整的句子，用来测试分块边界"] * 20) + "。"
    chunks = chunk_blocks([TextBlock(text)], size=120, overlap=20, min_chars=10)
    # 绝大多数块应以中文句号收尾（硬切时才例外）
    ended = [c.content.endswith("。") for c in chunks]
    assert sum(ended) >= len(chunks) - 1


def test_duplicate_blocks_are_removed():
    block = TextBlock("完全相同的一段资料。" * 10, locator="第 1 页")
    chunks = chunk_blocks([block, block], size=1000, overlap=50)
    assert len(chunks) == 1


def test_whitespace_only_returns_empty():
    assert chunk_blocks([TextBlock("   \n\t  "), TextBlock("")]) == []


def test_tiny_trailing_chunk_is_merged_forward():
    text = "甲" * 300 + "乙。"
    chunks = chunk_blocks([TextBlock(text)], size=300, overlap=20, min_chars=40)
    assert all(len(c.content) >= 40 for c in chunks)
    assert "乙。" in chunks[-1].content


def test_metadata_and_char_count():
    chunks = chunk_blocks(
        [TextBlock("元数据测试。" * 20, locator="幻灯片 3", meta={"slide": 3})],
        size=100,
        overlap=10,
    )
    assert chunks[0].meta.get("slide") == 3
    assert chunks[0].char_count == len(chunks[0].content)


def test_chunk_ids_are_stable_for_same_input():
    blocks = [TextBlock("稳定性测试。" * 30, locator="第 1 页")]
    first = chunk_blocks(blocks, size=100, overlap=10)
    second = chunk_blocks(blocks, size=100, overlap=10)
    assert [c.content for c in first] == [c.content for c in second]
    assert _joined(first) == _joined(second)