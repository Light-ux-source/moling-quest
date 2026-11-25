"""纯文本 / Markdown 解析。"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import ParsedDocument, TextBlock
from .base import ParseError

_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


def decode_bytes(data: bytes) -> str:
    if not data:
        raise ParseError("文件内容为空")
    for encoding in _ENCODINGS:
        try:
            text = data.decode(encoding)
            if text.strip():
                return text
        except (UnicodeDecodeError, LookupError):
            continue
    raise ParseError("无法识别文本编码，请另存为 UTF-8 后重试")


def _stem(filename: str) -> str:
    return Path(filename or "未命名资料").stem[:120] or "未命名资料"


def _paragraphs(text: str) -> list:
    value = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = [part.strip() for part in re.split(r"\n{2,}", value) if part.strip()]
    return parts or ([value.strip()] if value.strip() else [])


def parse_text(data: bytes, filename: str = "") -> ParsedDocument:
    text = decode_bytes(data)
    blocks = [
        TextBlock(part, locator=f"第 {index} 段", meta={"paragraph": index})
        for index, part in enumerate(_paragraphs(text), 1)
    ]
    if not blocks:
        raise ParseError("没有提取到文字")
    return ParsedDocument(title=_stem(filename), blocks=blocks, meta={"kind": "text"})


def parse_markdown(data: bytes, filename: str = "") -> ParsedDocument:
    text = decode_bytes(data)
    blocks = []
    title = ""
    for index, part in enumerate(_paragraphs(text), 1):
        first_line = part.splitlines()[0].strip()
        match = _HEADING.match(first_line)
        if match and not title:
            title = match.group(1).strip()[:120]
        blocks.append(
            TextBlock(part, locator=f"第 {index} 段", meta={"paragraph": index, "heading": bool(match)})
        )
    if not blocks:
        raise ParseError("没有提取到文字")
    return ParsedDocument(title=title or _stem(filename), blocks=blocks, meta={"kind": "markdown"})