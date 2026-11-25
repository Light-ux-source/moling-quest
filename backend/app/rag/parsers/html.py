"""HTML 正文提取：去导航/脚本/页脚，优先 article/main，保留段落顺序。

不使用 lxml，避免额外系统依赖；html.parser 对小程序资料足够。
"""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from ..types import ParsedDocument, TextBlock
from .base import ParseError

_DROP_TAGS = [
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "aside",
    "noscript",
    "svg",
    "form",
    "iframe",
    "canvas",
]
_BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre", "td", "th"]
_WS = re.compile(r"[ \t\u3000]+")


def _clean(text: str) -> str:
    value = str(text or "").replace("\r", "\n")
    lines = [_WS.sub(" ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def parse_html(data: bytes, filename: str = "", url: str = "") -> ParsedDocument:
    try:
        html = data.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        raise ParseError("网页内容无法解码") from exc
    return parse_html_text(html, filename=filename, url=url)


def parse_html_text(html: str, filename: str = "", url: str = "") -> ParsedDocument:
    soup = BeautifulSoup(html or "", "html.parser")
    title = ""
    if soup.title and soup.title.get_text(strip=True):
        title = _clean(soup.title.get_text(" "))[:120]
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = _clean(og.get("content"))[:120]

    for tag in _DROP_TAGS:
        for node in soup.find_all(tag):
            node.decompose()

    root = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"})
    if root is None or len(_clean(root.get_text(" "))) < 40:
        root = soup.body or soup

    blocks = []
    seen = set()
    for node in root.find_all(_BLOCK_TAGS):
        text = _clean(node.get_text(" "))
        if not text or text in seen:
            continue
        # 跳过被父级 block 覆盖的嵌套单元格文本
        if node.name in {"td", "th"} and len(text) < 4:
            continue
        seen.add(text)
        heading = node.name.startswith("h")
        content = f"# {text}" if heading else text
        blocks.append(
            TextBlock(
                content,
                locator=f"第 {len(blocks) + 1} 段",
                meta={"tag": node.name, "heading": heading},
            )
        )

    if not blocks:
        fallback = _clean(root.get_text("\n"))
        for index, part in enumerate([p for p in fallback.split("\n") if p.strip()][:200], 1):
            blocks.append(TextBlock(part, locator=f"第 {index} 段", meta={"tag": "text"}))

    if not blocks:
        raise ParseError("网页没有提取到正文，可能需要登录或被反爬限制；可以改用粘贴文本")

    return ParsedDocument(
        title=title or Path(filename or "网页资料").stem[:120] or "网页资料",
        blocks=blocks,
        meta={"kind": "html", "url": url},
    )