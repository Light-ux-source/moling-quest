"""文档解析器单元测试：PDF / DOCX / PPTX / XLSX / 文本 / Markdown / HTML。"""

from __future__ import annotations

import io

import pytest
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from app.rag.parsers import ParseError, detect_kind, parse_document


def make_pdf(text: str = "HTTP cache") -> bytes:
    """生成一个最小可解析的文本 PDF（Helvetica，仅 ASCII）。"""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def make_docx() -> bytes:
    doc = Document()
    doc.add_heading("HTTP 缓存", level=1)
    doc.add_paragraph("强缓存直接读取本地副本，不向服务器发请求。")
    doc.add_paragraph("协商缓存会向服务器确认资源是否变化。")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "状态码"
    table.cell(0, 1).text = "304"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_pptx() -> bytes:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "HTTP 缓存"
    body = slide.placeholders[1]
    body.text = "强缓存与协商缓存的区别"
    body.width = Inches(6)
    slide.notes_slide.notes_text_frame.text = "讲解备注：先讲强缓存。"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def make_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "缓存"
    ws.append(["类型", "状态码", "说明"])
    ws.append(["强缓存", "200", "直接读本地副本"])
    ws.append(["协商缓存", "304", "向服务器确认"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_detect_kind():
    assert detect_kind("a.PDF", "") == "pdf"
    assert detect_kind("a.docx", "") == "docx"
    assert detect_kind("a.pptx", "") == "pptx"
    assert detect_kind("a.xlsx", "") == "xlsx"
    assert detect_kind("a.md", "") == "markdown"
    assert detect_kind("a.txt", "") == "text"
    assert detect_kind("a.html", "text/html") == "html"
    assert detect_kind("a.bin", "application/pdf") == "pdf"
    with pytest.raises(ParseError):
        detect_kind("a.exe", "application/octet-stream")


def test_parse_pdf_page_locator():
    parsed = parse_document("pdf", make_pdf(), filename="cache.pdf")
    assert "HTTP cache" in parsed.text
    assert parsed.title
    assert parsed.blocks[0].locator == "第 1 页"
    assert parsed.meta.get("pages") == 1


def test_parse_pdf_rejects_empty_document():
    with pytest.raises(ParseError):
        parse_document("pdf", b"%PDF-1.4\n", filename="empty.pdf")


def test_parse_docx_keeps_heading_paragraph_and_table():
    parsed = parse_document("docx", make_docx(), filename="cache.docx")
    assert "HTTP 缓存" in parsed.text
    assert "强缓存" in parsed.text
    assert "304" in parsed.text
    assert parsed.title
    assert parsed.blocks
    assert all(block.locator for block in parsed.blocks)


def test_parse_pptx_keeps_slide_and_notes():
    parsed = parse_document("pptx", make_pptx(), filename="cache.pptx")
    assert "HTTP 缓存" in parsed.text
    assert "强缓存与协商缓存" in parsed.text
    assert "讲解备注" in parsed.text
    assert any(block.locator == "幻灯片 1" for block in parsed.blocks)


def test_parse_xlsx_keeps_sheet_name_and_cells():
    parsed = parse_document("xlsx", make_xlsx(), filename="cache.xlsx")
    assert "强缓存" in parsed.text
    assert "304" in parsed.text
    assert any("工作表 缓存" in block.locator for block in parsed.blocks)


def test_parse_text_utf8_and_gb18030():
    utf8 = parse_document("text", "中文编码测试".encode("utf-8"), filename="note.txt")
    assert "中文编码测试" in utf8.text
    assert utf8.title == "note"

    gb = parse_document("text", "中文编码测试".encode("gb18030"), filename="note.txt")
    assert "中文编码测试" in gb.text


def test_parse_markdown_keeps_heading_text():
    parsed = parse_document(
        "markdown",
        "# 缓存\n\n强缓存命中时返回 200。\n\n## 协商缓存\n\n返回 304。".encode("utf-8"),
        filename="cache.md",
    )
    assert "缓存" in parsed.text
    assert "304" in parsed.text
    assert parsed.title == "缓存"


def test_parse_html_removes_navigation_and_script():
    html = """
    <html><head><title>HTTP 缓存</title></head>
    <body><nav>首页 目录</nav>
      <article><h1>强缓存</h1><p>强缓存直接读取本地副本。</p>
      <p>协商缓存返回 304。</p></article>
      <script>alert('x')</script><footer>版权</footer>
    </body></html>
    """
    parsed = parse_document("html", html.encode("utf-8"), filename="cache.html")
    assert parsed.title == "HTTP 缓存"
    assert "强缓存" in parsed.text
    assert "304" in parsed.text
    assert "首页" not in parsed.text
    assert "alert" not in parsed.text


def test_parse_empty_text_raises():
    with pytest.raises(ParseError):
        parse_document("text", b"   \n\t ", filename="empty.txt")
    with pytest.raises(ParseError):
        parse_document("html", b"<html><body></body></html>", filename="empty.html")