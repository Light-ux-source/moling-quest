"""Mock 数据构建器：离线模式也走同一条 LangChain 链，保证契约一致。"""

from __future__ import annotations

import random
from typing import Any, Dict, List

DEFAULT_TYPES = ["single_choice", "multiple_choice", "true_false", "short_answer"]
TITLES = ["核心概念", "关键机制", "适用条件", "常见误区", "场景应用", "边界条件"]


def _topic(ctx: Dict[str, Any]) -> str:
    return str(ctx.get("topic") or "这个主题")


def build_digest(ctx: Dict[str, Any]) -> Dict[str, Any]:
    topic = _topic(ctx)
    return {
        "title": f"{topic} 核心知识梳理",
        "summary": f"围绕「{topic}」，本次学习聚焦概念定义、关键机制与常见误区三个层面。",
        "key_points": [
            {
                "point": f"{topic} 的基本定义与适用边界",
                "evidence": "来源于主题综述与官方文档。",
                "source_url": "",
            },
            {
                "point": f"{topic} 的核心机制与关键步骤",
                "evidence": "来源于原理讲解类资料。",
                "source_url": "",
            },
            {
                "point": f"{topic} 的典型应用场景与反例",
                "evidence": "来源于实践案例。",
                "source_url": "",
            },
            {
                "point": f"{topic} 的常见误区与辨析",
                "evidence": "来源于经验总结。",
                "source_url": "",
            },
        ],
        "misconceptions": [
            f"把 {topic} 的某个特例当成通用结论",
            f"混淆 {topic} 与相邻概念的前提条件",
        ],
        "prerequisites": ["基础术语", "常见场景"],
        "mock": True,
    }


def build_generate(ctx: Dict[str, Any]) -> Dict[str, Any]:
    topic = _topic(ctx)
    count = int(ctx.get("count") or 5)
    types: List[str] = list(ctx.get("types") or DEFAULT_TYPES)
    if not types:
        types = list(DEFAULT_TYPES)
    rng = random.Random(hash(topic) & 0xFFFF)
    questions: List[Dict[str, Any]] = []

    for i in range(count):
        qtype = types[i % len(types)]
        seq = i + 1
        title = TITLES[(i) % len(TITLES)]
        base = {
            "type": qtype,
            "title": title,
            "knowledge_point": f"{topic} · {title}",
            "difficulty": "easy" if seq <= 2 else ("medium" if seq <= 4 else "hard"),
            "source_refs": [],
        }
        if qtype in ("single_choice", "true_false"):
            options = (
                [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
                if qtype == "true_false"
                else [
                    {"key": "A", "text": f"{topic} 的核心定义"},
                    {"key": "B", "text": f"与 {topic} 无关的干扰项"},
                    {"key": "C", "text": f"{topic} 的常见误用"},
                    {"key": "D", "text": "以上都不对"},
                ]
            )
            correct = "A" if qtype == "true_false" else rng.choice(["A", "C"])
            questions.append(
                {
                    **base,
                    "stem": f"关于「{topic}」，下列说法正确的是？（第 {seq} 题 · 模拟）",
                    "options": options,
                    "correct_answer": correct,
                    "explanation": f"本题考查 {topic} 的基本概念。正确选项体现了核心定义，其余选项混淆了边界条件。",
                    "rubric": [],
                }
            )
        elif qtype == "multiple_choice":
            questions.append(
                {
                    **base,
                    "stem": f"以下哪些属于「{topic}」的关键要素？（多选 · 模拟）",
                    "options": [
                        {"key": "A", "text": "核心概念"},
                        {"key": "B", "text": "适用条件"},
                        {"key": "C", "text": "无关的营销话术"},
                        {"key": "D", "text": "典型反例"},
                    ],
                    "correct_answer": ["A", "B", "D"],
                    "explanation": "关键要素需要同时满足概念、条件与反例三个维度；营销话术不属于知识本身。",
                    "rubric": [],
                }
            )
        else:
            questions.append(
                {
                    **base,
                    "stem": f"请用 2～3 句话说明「{topic}」的核心机制，并举一个适用场景。（模拟）",
                    "options": [],
                    "correct_answer": [
                        f"说明 {topic} 的定义与作用",
                        "描述关键步骤或因果关系",
                        "给出一个具体适用场景",
                    ],
                    "explanation": "简答题按要点给分：定义、机制、场景各占一部分。",
                    "rubric": [
                        f"提到 {topic} 的定义或目标",
                        "描述了机制/流程",
                        "给出具体场景",
                    ],
                }
            )
    return {"questions": questions}


def build_grade(ctx: Dict[str, Any]) -> Dict[str, Any]:
    answer = str(ctx.get("user_answer") or "").strip()
    rubric: List[str] = list(ctx.get("rubric") or [])
    hits = 0
    for point in rubric:
        keyword = str(point).replace("提到", "").strip()[:6]
        if keyword and keyword in answer:
            hits += 1
    if not rubric:
        hits = 1 if len(answer) >= 20 else 0
    score = min(1.0, hits / max(1, len(rubric))) if rubric else (1.0 if hits else 0.0)
    if len(answer) >= 12 and score < 0.4:
        score = 0.4
    return {
        "score": round(score, 2),
        "correct": score >= 0.6,
        "feedback": (
            "要点覆盖较完整，表述清晰。"
            if score >= 0.8
            else "覆盖了部分要点，建议补充机制与场景细节。"
            if score >= 0.4
            else "答案与要点关联较弱，建议先回看解析中的关键概念。"
        ),
        "missing_points": [] if score >= 0.8 else rubric[: max(0, len(rubric) - hits)],
    }


def build_report(ctx: Dict[str, Any]) -> Dict[str, Any]:
    topic = _topic(ctx)
    accuracy = float(ctx.get("accuracy") or 0)
    wrong_seqs = ctx.get("wrong_seqs") or []
    gaps = (
        [
            f"第 {w.get('seq')} 题（{w.get('type_label')}）涉及的知识点仍需巩固"
            for w in wrong_seqs[:3]
        ]
        or [f"{topic} 的整体框架已基本掌握"]
    )
    return {
        "summary": (
            f"本次「{topic}」练习正确率 {int(accuracy * 100)}%，"
            + ("整体掌握良好，可以进入更难的题目。" if accuracy >= 0.8 else "基础概念已建立，但细节与应用还需加强。")
        ),
        "level_tag": "掌握良好" if accuracy >= 0.8 else "需要巩固" if accuracy >= 0.5 else "建议重学",
        "knowledge_gaps": gaps,
        "next_steps": [
            "回看错题的解析，用自己的话复述一遍关键概念",
            "针对薄弱点再练一组同主题题目",
            "尝试把概念应用到一个真实场景中",
        ],
        "suggested_topics": [f"{topic} 进阶", f"{topic} 的常见误区", f"{topic} 实战案例"],
    }


BUILDERS = {
    "digest": build_digest,
    "generate": build_generate,
    "grade": build_grade,
    "report": build_report,
}


def build_mock_data(task: str, context: Dict[str, Any] | None) -> Dict[str, Any]:
    builder = BUILDERS.get(task)
    if builder is None:
        return {"ok": True}
    return builder(context or {})