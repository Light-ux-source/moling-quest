#!/usr/bin/env python3
"""校验文档中的相对链接是否存在。

范围：README.md、方案设计文档.md、docs/*.md、prototype/README.md。
忽略 http(s)、mailto、data、纯锚点；跳过 fenced code block 与行内 code。
用法：python3 scripts/check_docs_links.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FILES = [
    ROOT / "README.md",
    ROOT / "方案设计文档.md",
    ROOT / "prototype" / "README.md",
    *sorted((ROOT / "docs").glob("*.md")),
]

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FENCE_RE = re.compile(r"```.*?```", re.S)
CODE_RE = re.compile(r"`[^`]*`")


def strip_code(text: str) -> str:
    text = FENCE_RE.sub("", text)
    return CODE_RE.sub("", text)


def main() -> int:
    broken = []
    checked = 0
    for file in FILES:
        if not file.exists():
            broken.append((file, "<file missing>"))
            continue
        text = strip_code(file.read_text(encoding="utf-8"))
        for raw in LINK_RE.findall(text):
            target = raw.strip().split(" ")[0].strip()
            if not target:
                continue
            if target.startswith(("http://", "https://", "mailto:", "data:", "#")):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            checked += 1
            resolved = (file.parent / path_part).resolve()
            if not resolved.exists():
                broken.append((file.relative_to(ROOT), target))

    print(f"checked {checked} relative links in {len(FILES)} files")
    if broken:
        print(f"broken: {len(broken)}")
        for file, target in broken:
            print(f"  {file} -> {target}")
        return 1
    print("0 broken")
    return 0


if __name__ == "__main__":
    sys.exit(main())