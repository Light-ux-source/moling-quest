"""PDF 解析：逐页提取文字，保留页码。扫描件（无文本层）会明确报错。"""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader

from ..types import ParsedDocument, TextBlock
from .base import ParseError


def _clean(text: str) -> str:
    lines = [line.strip() for line in str(text or "").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def parse_pdf(data: bytes, filename: str = "", max_pages: int = 300) -> ParsedDocument:
    if not data.lstrip().startswith(b"%PDF"):
        raise ParseError("文件内容不是有效的 PDF")
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - pypdf 的异常类型较多
        raise ParseError(f"PDF 无法打开：{str(exc)[:120]}") from exc

    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ParseError("PDF 已加密，暂不支持解析")
        except ParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ParseError("PDF 已加密，暂不支持解析") from exc

    pages = len(reader.pages)
    if pages > max_pages:
        raise ParseError(f"PDF 共 {pages} 页，超过单份 {max_pages} 页限制")

    blocks = []
    for index, page in enumerate(reader.pages, 1):
        try:
            text = _clean(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - 单页失败不拖垮整份文档
            text = ""
        if text:
            blocks.append(TextBlock(text, locator=f"第 {index} 页", meta={"page": index}))

    if not blocks:
        raise ParseError("PDF 没有提取到文字，可能是扫描件；请上传文字版 PDF 或粘贴文本")

    title = ""
    try:
        meta_title = (reader.metadata or {}).get("/Title") if reader.metadata else None
        if meta_title:
            title = str(meta_title).strip()[:120]
    except Exception:  # noqa: BLE001
        title = ""
    title = title or Path(filename or "未命名资料").stem[:120] or "未命名资料"
    return ParsedDocument(title=title, blocks=blocks, meta={"kind": "pdf", "pages": pages})