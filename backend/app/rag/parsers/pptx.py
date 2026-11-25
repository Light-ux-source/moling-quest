"""PPTX 解析：逐页提取文本框 + 演讲者备注，保留幻灯片序号。"""

from __future__ import annotations

import io
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from ..types import ParsedDocument, TextBlock
from .base import ParseError


def _shape_texts(shape) -> list:
    texts = []
    try:
        if shape.has_text_frame:
            value = str(shape.text_frame.text or "").strip()
            if value:
                texts.append(value)
    except Exception:  # noqa: BLE001
        pass
    try:
        if shape.has_table:
            for row in shape.table.rows:
                cells = [str(cell.text or "").strip() for cell in row.cells]
                if any(cells):
                    texts.append(" | ".join(cells))
    except Exception:  # noqa: BLE001
        pass
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        try:
            for child in shape.shapes:
                texts.extend(_shape_texts(child))
        except Exception:  # noqa: BLE001
            pass
    return texts


def parse_pptx(data: bytes, filename: str = "") -> ParsedDocument:
    if not data.startswith(b"PK"):
        raise ParseError("文件内容不是有效的 PPTX")
    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"PPTX 无法打开：{str(exc)[:120]}") from exc

    blocks = []
    title = ""
    try:
        title = str(prs.core_properties.title or "").strip()[:120]
    except Exception:  # noqa: BLE001
        title = ""

    for index, slide in enumerate(prs.slides, 1):
        parts = []
        for shape in slide.shapes:
            parts.extend(_shape_texts(shape))
        if not title and slide.shapes.title is not None:
            value = str(slide.shapes.title.text or "").strip()
            if value:
                title = value[:120]
        try:
            notes = slide.notes_slide.notes_text_frame.text or ""
        except Exception:  # noqa: BLE001
            notes = ""
        notes = str(notes).strip()
        if notes:
            parts.append(f"【备注】{notes}")
        content = "\n".join(part for part in parts if part).strip()
        if content:
            blocks.append(
                TextBlock(content, locator=f"幻灯片 {index}", meta={"slide": index})
            )

    if not blocks:
        raise ParseError("PPTX 没有提取到文字")
    return ParsedDocument(
        title=title or Path(filename or "未命名资料").stem[:120] or "未命名资料",
        blocks=blocks,
        meta={"kind": "pptx", "slides": len(prs.slides)},
    )