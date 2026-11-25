"""XLSX 解析：逐工作表读取，按行分组，保留工作表名与行号区间。"""

from __future__ import annotations

import io
from pathlib import Path

from openpyxl import load_workbook

from ..types import ParsedDocument, TextBlock
from .base import ParseError

MAX_ROWS_PER_SHEET = 2000
MAX_COLS = 50
ROWS_PER_BLOCK = 40


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip().replace("\n", " ")


def parse_xlsx(data: bytes, filename: str = "") -> ParsedDocument:
    if not data.startswith(b"PK"):
        raise ParseError("文件内容不是有效的 XLSX")
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"XLSX 无法打开：{str(exc)[:120]}") from exc

    blocks = []
    sheet_names = []
    try:
        for sheet in workbook.worksheets:
            sheet_names.append(sheet.title)
            rows = []
            for row_index, row in enumerate(
                sheet.iter_rows(min_row=1, max_row=MAX_ROWS_PER_SHEET, max_col=MAX_COLS, values_only=True),
                1,
            ):
                cells = [_cell(value) for value in row]
                if any(cells):
                    rows.append((row_index, " | ".join(cells).strip(" |")))
            for start in range(0, len(rows), ROWS_PER_BLOCK):
                group = rows[start : start + ROWS_PER_BLOCK]
                if not group:
                    continue
                first = group[0][0]
                last = group[-1][0]
                text = "\n".join(line for _, line in group)
                blocks.append(
                    TextBlock(
                        text,
                        locator=f"工作表 {sheet.title} 第 {first}-{last} 行",
                        meta={"sheet": sheet.title, "rows": [first, last]},
                    )
                )
    finally:
        workbook.close()

    if not blocks:
        raise ParseError("XLSX 没有提取到文字")
    return ParsedDocument(
        title=Path(filename or "未命名资料").stem[:120] or "未命名资料",
        blocks=blocks,
        meta={"kind": "xlsx", "sheets": sheet_names},
    )