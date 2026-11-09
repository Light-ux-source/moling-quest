"""生成小程序静态资源：墨团 SVG、线性图标、地图路径、纸纹。

原型全部是内联 SVG；微信小程序不支持 JSX 里的 <svg>，但 <image> 支持 SVG 文件。
本脚本把原型中的图形固化为本地 SVG，避免运行时兼容问题。
"""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src" / "assets"
ICONS = ASSETS / "icons"
MASCOT = ASSETS / "mascot"
MAP = ASSETS / "map"
STYLES = ROOT / "src" / "styles"

for directory in (ICONS, MASCOT, MAP, STYLES):
    directory.mkdir(parents=True, exist_ok=True)


def write(path: Path, content: str) -> None:
    path.write_text(content.strip() + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# 图标
# --------------------------------------------------------------------------- #
ICON_PATHS = {
    "tab-home": '<path d="M4 18c3-6 5-9 8-9s5 3 8 9"/><path d="M4 20h16"/>',
    "tab-compass": '<circle cx="12" cy="12" r="8"/><path d="M15 9l-2 5-4 1 2-5z"/>',
    "tab-book": '<path d="M5 4h11a3 3 0 013 3v13H8a3 3 0 01-3-3z"/><path d="M8 8h8M8 12h6"/>',
    "tab-user": '<circle cx="12" cy="9" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>',
    "back": '<path d="M15 5l-7 7 7 7"/>',
    "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "check": '<path d="M5 12l4 4L19 6"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "lock": '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "list": '<path d="M5 7h14M5 12h14M5 17h9"/>',
    "leaf": '<path d="M5 19c8-1 13-6 14-14C11 5 4 10 5 19z"/><path d="M5 19c3-5 7-8 11-10"/>',
    "share": '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 10.7l6.8-4.4M8.6 13.3l6.8 4.4"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "refresh": '<path d="M20 12a8 8 0 11-2.3-5.7"/><path d="M20 4v5h-5"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 00-2-2H6a2 2 0 00-2 2v8a2 2 0 002 2h2"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "chapter-data": '<path d="M4 18c3-6 5-9 8-9s5 3 8 9"/><path d="M4 20h16"/><circle cx="12" cy="5" r="2"/>',
    "chapter-cache": '<path d="M4 7h16M4 12h10M4 17h7"/><circle cx="18" cy="16" r="3"/>',
    "sparkle": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
    "flame": '<path d="M12 2c1 4 5 5 5 10a5 5 0 11-10 0c0-3 2-4 2-7 1 2 2 2 3 3 0-2 0-4 0-6z"/>',
    "star": '<path d="M12 3l2.6 6.2 6.4.6-4.9 4.3 1.5 6.4L12 17.1 6.4 20.5l1.5-6.4L3 9.8l6.4-.6z"/>',
}

# 填充型图标不使用描边
FILLED = {"sparkle", "flame", "star"}
COLORS = {
    "ink": "#23281F",
    "ink2": "#4E564A",
    "ink3": "#626A5C",
    "moss": "#3E6650",
    "mossdeep": "#2B4A39",
    "amber": "#E0A23C",
    "amberdeep": "#A96F1F",
    "paper": "#FFFDF6",
    "vermilion": "#BF5B42",
    "celadon": "#9DBFB0",
}

VARIANTS = {
    "tab-home": ["ink3", "mossdeep"],
    "tab-compass": ["ink3", "mossdeep"],
    "tab-book": ["ink3", "mossdeep"],
    "tab-user": ["ink3", "mossdeep"],
    "back": ["ink"],
    "arrow-right": ["paper", "ink", "mossdeep"],
    "check": ["paper", "moss", "vermilion"],
    "close": ["ink3"],
    "lock": ["ink3"],
    "clock": ["paper", "ink3"],
    "list": ["paper"],
    "leaf": ["moss", "paper"],
    "share": ["ink", "paper"],
    "chevron-down": ["ink3"],
    "chevron-right": ["ink3"],
    "refresh": ["mossdeep", "paper"],
    "copy": ["ink3"],
    "info": ["ink3"],
    "chapter-data": ["mossdeep"],
    "chapter-cache": ["amberdeep"],
    "sparkle": ["amber"],
    "flame": ["amberdeep", "amber"],
    "star": ["amber", "paper", "empty"],
}


def icon_svg(name: str, paths: str, color: str) -> str:
    if name in FILLED:
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="{color}">{paths}</svg>"""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="' + color + '" stroke-width="1.7" stroke-linecap="round" '
        'stroke-linejoin="round">' + paths + "</svg>"
    )


for name, paths in ICON_PATHS.items():
    for variant in VARIANTS.get(name, ["ink"]):
        if variant == "empty":
            # 空心星：陈纸描边，不用灰色
            svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
                'fill="#EFE6D1" stroke="#D8CFB8" stroke-width="1.4" stroke-linejoin="round">'
                + paths
                + "</svg>"
            )
        else:
            svg = icon_svg(name, paths, COLORS[variant])
        write(ICONS / f"{name}-{variant}.svg", svg)

# 兼容别名：代码里常用 star-empty
write(ICONS / "star-empty.svg", icon_svg("star", ICON_PATHS["star"], "#EFE6D1").replace(
    'fill="#EFE6D1"', 'fill="#EFE6D1" stroke="#D8CFB8" stroke-width="1.4"'
))


# --------------------------------------------------------------------------- #
# 墨团
# --------------------------------------------------------------------------- #
MASCOT_IDLE = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 260">
  <ellipse cx="130" cy="238" rx="60" ry="9" fill="#23281f" opacity="0.1"/>
  <path d="M196 186c34-8 44-44 24-68" stroke="#23281f" stroke-width="20" fill="none" stroke-linecap="round"/>
  <ellipse cx="130" cy="176" rx="58" ry="50" fill="#23281f"/>
  <ellipse cx="130" cy="190" rx="26" ry="20" fill="#f7f2e4" opacity="0.95"/>
  <circle cx="130" cy="118" r="54" fill="#23281f"/>
  <path d="M86 84L80 44l34 24z" fill="#23281f"/><path d="M174 84l6-40-34 24z" fill="#23281f"/>
  <ellipse cx="108" cy="112" rx="14" ry="16" fill="#e0a23c"/><ellipse cx="152" cy="112" rx="14" ry="16" fill="#e0a23c"/>
  <ellipse cx="108" cy="112" rx="4.5" ry="9" fill="#23281f"/><ellipse cx="152" cy="112" rx="4.5" ry="9" fill="#23281f"/>
  <circle cx="103" cy="105" r="3" fill="#fffdf6"/><circle cx="147" cy="105" r="3" fill="#fffdf6"/>
  <ellipse cx="130" cy="134" rx="24" ry="15" fill="#f7f2e4" opacity="0.96"/>
  <path d="M125 132q5 5 10 0" stroke="#23281f" stroke-width="2.4" fill="none" stroke-linecap="round"/>
  <ellipse cx="130" cy="126" rx="4" ry="2.6" fill="#bf5b42"/>
</svg>
"""

MASCOT_HAPPY = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 260">
  <ellipse cx="130" cy="238" rx="60" ry="9" fill="#23281f" opacity="0.1"/>
  <path d="M196 186c34-8 44-44 24-68" stroke="#23281f" stroke-width="20" fill="none" stroke-linecap="round"/>
  <path d="M196 186c40-12 52-52 26-76" stroke="#e0a23c" stroke-width="6" fill="none" stroke-linecap="round" opacity="0.5"/>
  <ellipse cx="130" cy="176" rx="58" ry="50" fill="#23281f"/>
  <ellipse cx="130" cy="190" rx="26" ry="20" fill="#f7f2e4" opacity="0.95"/>
  <circle cx="130" cy="118" r="54" fill="#23281f"/>
  <path d="M86 84L80 44l34 24z" fill="#23281f"/><path d="M174 84l6-40-34 24z" fill="#23281f"/>
  <path d="M98 112q10-10 20 0" stroke="#e0a23c" stroke-width="5" fill="none" stroke-linecap="round"/>
  <path d="M142 112q10-10 20 0" stroke="#e0a23c" stroke-width="5" fill="none" stroke-linecap="round"/>
  <ellipse cx="130" cy="136" rx="24" ry="16" fill="#f7f2e4" opacity="0.96"/>
  <path d="M120 132q10 10 20 0" stroke="#23281f" stroke-width="2.4" fill="none" stroke-linecap="round"/>
  <ellipse cx="88" cy="130" rx="9" ry="5" fill="#bf5b42" opacity="0.32"/>
  <ellipse cx="172" cy="130" rx="9" ry="5" fill="#bf5b42" opacity="0.32"/>
  <path d="M40 70l4 10 10 4-10 4-4 10-4-10-10-4 10-4z" fill="#e0a23c" opacity="0.8"/>
</svg>
"""

MASCOT_THINKING = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 260">
  <ellipse cx="130" cy="238" rx="60" ry="9" fill="#23281f" opacity="0.1"/>
  <path d="M196 186c26-2 40-28 34-54" stroke="#23281f" stroke-width="20" fill="none" stroke-linecap="round"/>
  <ellipse cx="130" cy="176" rx="58" ry="50" fill="#23281f"/>
  <ellipse cx="130" cy="190" rx="26" ry="20" fill="#f7f2e4" opacity="0.95"/>
  <circle cx="130" cy="118" r="54" fill="#23281f"/>
  <path d="M86 84L80 44l34 24z" fill="#23281f"/><path d="M174 84l6-40-34 24z" fill="#23281f"/>
  <ellipse cx="108" cy="112" rx="14" ry="9" fill="#e0a23c"/>
  <ellipse cx="152" cy="112" rx="14" ry="16" fill="#e0a23c"/>
  <ellipse cx="108" cy="112" rx="4.5" ry="6" fill="#23281f"/><ellipse cx="152" cy="112" rx="4.5" ry="9" fill="#23281f"/>
  <circle cx="147" cy="105" r="3" fill="#fffdf6"/>
  <ellipse cx="130" cy="134" rx="24" ry="15" fill="#f7f2e4" opacity="0.96"/>
  <path d="M126 134h8" stroke="#23281f" stroke-width="2.4" stroke-linecap="round"/>
  <path d="M186 46c8-6 20-2 20 8 0 8-10 10-14 5s0-12 8-14" stroke="#3e6650" stroke-width="2.6" fill="none" stroke-linecap="round"/>
  <path d="M190 58c0-10 7-16 16-16s16 6 16 16c0 8-6 11-10 14-3 2-4 4-4 7" stroke="#3e6650" stroke-width="2.6" fill="none" stroke-linecap="round" opacity=".75"/>
  <circle cx="208" cy="86" r="1.8" fill="#3e6650" opacity=".75"/>
</svg>
"""

MASCOT_HEAD = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">
  <circle cx="100" cy="92" r="44" fill="#23281f"/>
  <path d="M64 60L60 28l28 18z" fill="#23281f"/><path d="M136 60l4-32-28 18z" fill="#23281f"/>
  <ellipse cx="83" cy="90" rx="10" ry="12" fill="#e0a23c"/><ellipse cx="117" cy="90" rx="10" ry="12" fill="#e0a23c"/>
  <ellipse cx="83" cy="90" rx="3.6" ry="7" fill="#23281f"/><ellipse cx="117" cy="90" rx="3.6" ry="7" fill="#23281f"/>
  <ellipse cx="100" cy="112" rx="17" ry="10" fill="#f7f2e4"/>
</svg>
"""

write(MASCOT / "idle.svg", MASCOT_IDLE)
write(MASCOT / "happy.svg", MASCOT_HAPPY)
write(MASCOT / "thinking.svg", MASCOT_THINKING)
write(MASCOT / "head.svg", MASCOT_HEAD)


# --------------------------------------------------------------------------- #
# 地图节点坐标 + 路径
# --------------------------------------------------------------------------- #
NODE_LAYOUTS = {
    3: [(24, 83), (55, 64), (38, 42)],
    5: [(24, 83), (63, 70), (38, 55), (71, 40), (32, 26)],
    8: [(24, 86), (58, 78), (70, 68), (40, 58), (26, 48), (62, 38), (72, 28), (36, 18)],
}
FINAL_POSITION = {3: (66, 14), 5: (66, 12), 8: (66, 8)}


def catmull_rom(points: list[tuple[float, float]]) -> str:
    if len(points) < 2:
        return ""
    pts = [points[0]] + points + [points[-1]]
    d = f"M{points[0][0]:.1f} {points[0][1]:.1f}"
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p2[0]:.1f} {p2[1]:.1f}"
    return d


def map_svg(count: int) -> str:
    if count == 5:
        main = (
            "M80 390C130 380 180 365 211 329C245 295 170 290 127 258C85 225 200 225 "
            "238 188C270 160 145 150 107 122C75 100 180 90 221 56"
        )
    else:
        positions = NODE_LAYOUTS[count] + [FINAL_POSITION[count]]
        points = [(x / 100 * 335, y / 100 * 470) for x, y in positions]
        main = catmull_rom(points)
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 335 470" preserveAspectRatio="none">
  <path d="{main}" stroke="#3e6650" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-dasharray="2 11" opacity="0.42"/>
  <path d="M20 430c26-22 40-56 64-72" stroke="#9dbfb0" stroke-width="18" fill="none" stroke-linecap="round" opacity="0.35"/>
  <circle cx="292" cy="118" r="26" fill="#e0a23c" opacity="0.12"/>
  <circle cx="48" cy="196" r="34" fill="#3e6650" opacity="0.08"/>
  <path d="M270 400c10-18 16-30 14-46" stroke="#3e6650" stroke-width="2" fill="none" opacity="0.25"/>
  <path d="M300 392c12-14 14-28 10-40" stroke="#3e6650" stroke-width="2" fill="none" opacity="0.2"/>
</svg>
"""


for count in (3, 5, 8):
    write(MAP / f"path-{count}.svg", map_svg(count))

# 布局坐标常量也生成一份，保证 TS 与 SVG 同源
layout_ts = "// 由 scripts/gen_assets.py 生成，请勿手改\nexport const NODE_LAYOUTS: Record<number, Array<[number, number]>> = {\n"
for count, positions in NODE_LAYOUTS.items():
    layout_ts += f"  {count}: {[[x, y] for x, y in positions]},\n"
layout_ts += "}\n\nexport const FINAL_POSITION: Record<number, [number, number]> = {\n"
for count, position in FINAL_POSITION.items():
    layout_ts += f"  {count}: [{position[0]}, {position[1]}],\n"
layout_ts += "}\n"
write(ROOT / "src" / "utils" / "mapLayout.ts", layout_ts)


# --------------------------------------------------------------------------- #
# 纸纹（96×96 PNG → CSS base64）
# --------------------------------------------------------------------------- #
try:
    from PIL import Image

    rng = __import__("random").Random(20261109)
    image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    pixels = image.load()
    for y in range(96):
        for x in range(96):
            alpha = rng.randint(0, 10)
            shade = rng.randint(40, 90)
            pixels[x, y] = (shade, shade, shade, alpha)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    write(
        STYLES / "noise.css",
        """
/* 由 scripts/gen_assets.py 生成：96×96 纸纹，低透明度，仅作质感 */
.paper-noise::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: 0.55;
  background-image: url("data:image/png;base64,%s");
  background-repeat: repeat;
  mix-blend-mode: multiply;
}
""" % encoded,
    )
    print("noise bytes", len(buffer.getvalue()), "base64", len(encoded))
except Exception as exc:  # pragma: no cover
    print("noise skipped:", exc)

print("assets generated at", ASSETS)