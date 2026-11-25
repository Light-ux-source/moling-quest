"""DOCX 解析：段落 + 表格，保留段落序号与标题标记。"""

from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..types import ParsedDocument, TextBlock
from .base import ParseError


def _is_heading(paragraph: Paragraph) -> bool:
    try:
        name = (paragraph.style.name or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return name.startswith("heading") or name.startswith("标题")


def _paragraph_text(paragraph: Paragraph) -> str:
    return str(paragraph.text or "").strip()


def _table_text(table: Table) -> str:
    lines = []
    for row in table.rows:
        cells = [str(cell.text or "").strip().replace("\n", " ") for cell in row.cells]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def parse_docx(data: bytes, filename: str = "") -> ParsedDocument:
    if not data.startswith(b"PK"):
        raise ParseError("文件内容不是有效的 DOCX")
    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"DOCX 无法打开：{str(exc)[:120]}") from exc

    blocks = []
    title = ""
    try:
        title = str(doc.core_properties.title or "").strip()[:120]
    except Exception:  # noqa: BLE001
        title = ""

    index = 0
    items = doc.iter_inner_content() if hasattr(doc, "iter_inner_content") else doc.paragraphs
    for item in items:
        index += 1
        if isinstance(item, Paragraph):
            text = _paragraph_text(item)
            if not text:
                continue
            heading = _is_heading(item)
            if heading and not title:
                title = text[:120]
            content = f"# {text}" if heading else text
            blocks.append(
                TextBlock(
                    content,
                    locator=f"第 {index} 段",
                    meta={"paragraph": index, "heading": heading},
                )
            )
        elif isinstance(item, Table):
            text = _table_text(item)
            if text:
                blocks.append(
                    TextBlock(text, locator=f"第 {index} 段（表格）", meta={"paragraph": index, "table": True})
                )

    if not blocks:
        raise ParseError("DOCX 没有提取到文字")
    return ParsedDocument(
        title=title or Path(filename or "未命名资料").stem[:120] or "未命名资料",
        blocks=blocks,
        meta={"kind": "docx", "paragraphs": index},
    )