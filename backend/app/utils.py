"""通用小工具。"""

from __future__ import annotations

from typing import Any, List


def letters(value: Any) -> List[str]:
    """把 "A" / ["A","C"] / "A,C" / "AB" 统一成字母数组。"""
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.replace(",", " ").replace("，", " ").replace("、", " ").strip()
        if not raw:
            return []
        parts = [p for p in raw.split() if p]
        if len(parts) == 1 and len(parts[0]) > 1 and parts[0].isalpha():
            parts = list(parts[0])
        return [p.strip().upper()[:1] for p in parts if p.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(p).strip().upper()[:1] for p in value if str(p).strip()]
    return []


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def overlap_ratio(answer: str, points: List[str]) -> float:
    """中文场景下的要点覆盖率（无需分词）：按 3 字滑窗命中判断。"""
    answer = (answer or "").strip()
    if not answer or not points:
        return 0.0
    hit = 0
    for point in points:
        point = str(point).strip()
        if not point:
            continue
        window = max(2, min(4, len(point)))
        matched = any(point[i : i + window] in answer for i in range(max(1, len(point) - window + 1)))
        if matched:
            hit += 1
    return hit / len(points)