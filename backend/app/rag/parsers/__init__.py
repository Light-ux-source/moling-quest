"""解析器注册与文件类型识别。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..types import ParsedDocument
from .base import ParseError
from .docx import parse_docx
from .html import parse_html, parse_html_text
from .pdf import parse_pdf
from .pptx import parse_pptx
from .text import decode_bytes, parse_markdown, parse_text
from .xlsx import parse_xlsx

SUPPORTED_KINDS = {"pdf", "docx", "pptx", "xlsx", "text", "markdown", "html"}

_EXT_MAP = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".txt": "text",
    ".text": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
}

_MIME_MAP = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/plain": "text",
    "text/markdown": "markdown",
    "text/html": "html",
    "application/xhtml+xml": "html",
}


def detect_kind(filename: str = "", mime: str = "") -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in _EXT_MAP:
        return _EXT_MAP[suffix]
    if suffix in {".doc", ".ppt", ".xls"}:
        raise ParseError("暂不支持旧版 Office 格式，请另存为 DOCX / PPTX / XLSX")
    normalized = (mime or "").split(";")[0].strip().lower()
    if normalized in _MIME_MAP:
        return _MIME_MAP[normalized]
    raise ParseError("暂不支持这种文件类型；支持 PDF、DOCX、PPTX、XLSX、TXT、MD、HTML")


def parse_document(
    kind: str,
    data: bytes,
    *,
    filename: str = "",
    mime: str = "",
    url: str = "",
    max_pages: int = 300,
) -> ParsedDocument:
    kind = (kind or detect_kind(filename, mime)).strip().lower()
    if kind not in SUPPORTED_KINDS:
        raise ParseError("暂不支持这种文件类型")
    if kind == "pdf":
        return parse_pdf(data, filename, max_pages=max_pages)
    if kind == "docx":
        return parse_docx(data, filename)
    if kind == "pptx":
        return parse_pptx(data, filename)
    if kind == "xlsx":
        return parse_xlsx(data, filename)
    if kind == "html":
        return parse_html(data, filename, url=url)
    if kind == "markdown":
        return parse_markdown(data, filename)
    return parse_text(data, filename)


__all__ = [
    "ParseError",
    "SUPPORTED_KINDS",
    "decode_bytes",
    "detect_kind",
    "parse_document",
    "parse_html_text",
]