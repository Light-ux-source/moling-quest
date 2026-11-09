"""Prompt 资产：集中管理、可版本化、可评测。

设计原则
1. 输出必须是严格 JSON（DeepSeek JSON mode），字段与 schemas 对齐；
2. 出题质量靠「认知层级 + 干扰项规则 + 禁止事项」约束，而不是靠模型自由发挥；
3. 所有事实性陈述要求可回溯到检索来源，降低幻觉。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .schemas import TYPE_LABELS

LEVEL_GUIDE: Dict[str, str] = {
    "basic": (
        "入门级：70% 概念识记与理解，20% 简单应用，10% 辨析。"
        "题干直白，不设陷阱；干扰项应来自常见误解而非文字游戏。"
    ),
    "advanced": (
        "进阶级：30% 概念理解，50% 场景应用与因果推理，20% 边界辨析。"
        "题干可包含简短场景，要求判断「为什么」而不是只记「是什么」。"
    ),
    "challenge": (
        "挑战级：20% 综合理解，50% 多步推理/方案取舍，30% 反例与边界条件。"
        "允许对比两个相近方案，要求指出前提差异；避免偏题冷知识。"
    ),
}

TYPE_RULES = """
题型规范（必须严格遵守）：
- single_choice：4 个选项，key 依次为 A/B/C/D，correct_answer 为单个字母字符串，如 "B"。
- multiple_choice：4 个选项，key 依次为 A/B/C/D，correct_answer 为字母数组（2～3 个），如 ["A","C"]。
- true_false：固定 2 个选项 [{"key":"A","text":"正确"},{"key":"B","text":"错误"}]，correct_answer 为 "A" 或 "B"。
- short_answer：options 为空数组；correct_answer 为 3～5 条「得分要点」字符串数组；rubric 为对应的判分细则（与要点一一对应）。
- 除 short_answer 外，每题的 explanation 写 60～160 字：先点明正确项为什么对，再点明最容易误选的干扰项为什么错。
- 所有题目必须围绕给定知识点，不得出现「以上都对」「以上都不对」之外的万能选项，也不得两题考查同一事实。
"""

SYSTEM_GENERATOR = (
    "你是一位资深的教学设计师与命题专家，擅长把复杂知识拆成有梯度的题目。"
    "你只输出 JSON，不输出任何解释性文字或 Markdown 代码块。"
)

SYSTEM_GRADER = (
    "你是一位严格但公正的阅卷老师，按得分要点给分，不因表达差异扣分，也不因措辞华丽给分。"
    "你只输出 JSON。"
)

SYSTEM_REPORTER = (
    "你是一位学习教练，擅长基于答题数据给出具体、可执行、不空泛的改进建议。"
    "你只输出 JSON。"
)


def build_digest_prompt(topic: str, level: str, sources: List[Dict[str, Any]]) -> Dict[str, str]:
    source_text = "\n".join(
        f"[{i + 1}] {s.get('title', '')}（{s.get('site_name') or '未知站点'}）\n{s.get('summary', '')}"
        for i, s in enumerate(sources[:8])
    ) or "（本次没有检索到外部资料，请基于你已有的可靠知识作答，并在 evidence 中标注「模型知识」。）"

    user = f"""请把下面的资料整理成用于出题的知识提纲。

学习主题：{topic}
学习难度：{LEVEL_GUIDE[level]}

检索资料：
{source_text}

输出 JSON，结构严格如下：
{{
  "title": "本次学习的知识标题（不超过 20 字）",
  "summary": "80 字以内的整体概述",
  "key_points": [
    {{"point": "一个可被出题的核心知识点（不超过 40 字）", "evidence": "资料中的依据，40 字以内", "source_url": "对应资料链接，没有则为空字符串"}}
  ],
  "misconceptions": ["初学者最常见的 2～3 个误区"],
  "prerequisites": ["理解本主题需要的前置概念，最多 3 个"]
}}

要求：
1. key_points 给 4～6 条，覆盖定义、机制、应用、边界四类；
2. 只使用资料中可靠的信息；资料冲突时以官方/一手来源为准；
3. 纯 JSON，不要代码块。"""
    return {"system": SYSTEM_GENERATOR, "user": user}


def build_generate_prompt(
    topic: str,
    level: str,
    count: int,
    types: List[str],
    brief: Dict[str, Any],
    sources: List[Dict[str, Any]],
) -> Dict[str, str]:
    type_desc = "、".join(TYPE_LABELS.get(t, t) for t in types)
    source_urls = [s.get("url") for s in sources if s.get("url")]
    url_hint = "、".join(source_urls[:5]) if source_urls else "（无可用链接，source_refs 留空数组）"

    user = f"""请为「{topic}」生成 {count} 道练习题。

难度要求：{LEVEL_GUIDE[level]}
题型范围：{type_desc}（数量按此顺序轮转分配，至少包含一种客观题和一种主观题）
{TYPE_RULES}

知识提纲（出题范围以此为准）：
{json.dumps(brief, ensure_ascii=False, indent=2)}

可引用的来源链接（source_refs 只能从这里选，不得编造）：{url_hint}

输出 JSON，结构严格如下：
{{
  "questions": [
    {{
      "type": "single_choice | multiple_choice | true_false | short_answer",
      "stem": "题干",
      "options": [{{"key": "A", "text": "选项内容"}}],
      "correct_answer": "B",
      "explanation": "解析",
      "difficulty": "easy | medium | hard",
      "rubric": ["简答题判分要点；客观题给空数组"],
      "source_refs": ["https://..."]
    }}
  ]
}}

硬性要求：
1. 恰好 {count} 题，seq 由程序生成，你不需要输出；
2. 题干不得直接照抄提纲原句，要改写为具体问题；
3. 干扰项必须是「看起来合理但确实错误」的表述，禁止使用明显荒谬项凑数；
4. 简答题的 correct_answer 必须是字符串数组（3～5 条得分要点），客观题为字符串或字符串数组；
5. 纯 JSON，不要代码块。"""
    return {"system": SYSTEM_GENERATOR, "user": user}


def build_grade_prompt(question: Dict[str, Any], user_answer: Any, level: str) -> Dict[str, str]:
    user = f"""请批改下面这道简答题。

题目：{question.get('stem', '')}
判分要点（rubric）：{json.dumps(question.get('rubric') or [], ensure_ascii=False)}
参考答案要点：{json.dumps(question.get('correct_answer'), ensure_ascii=False)}
学生答案：{json.dumps(user_answer, ensure_ascii=False)}
学习难度：{level}

评分标准：
- 覆盖全部要点且表述准确：0.9～1.0
- 覆盖大部分要点，个别不精确：0.6～0.9
- 只覆盖少部分要点：0.3～0.6
- 答非所问/空白/明显错误：0～0.3
- 学生用同义表达也应给分，不要求逐字一致。

输出 JSON：
{{
  "score": 0.0,
  "correct": false,
  "feedback": "60 字以内，先肯定答对的部分，再指出缺什么、怎么补",
  "missing_points": ["未覆盖的要点"]
}}
纯 JSON，不要代码块。"""
    return {"system": SYSTEM_GRADER, "user": user}


def build_report_prompt(
    topic: str,
    level: str,
    stats: Dict[str, Any],
    items: List[Dict[str, Any]],
) -> Dict[str, str]:
    compact_items = [
        {
            "seq": it["seq"],
            "type_label": it["type_label"],
            "stem": it["stem"][:120],
            "is_correct": it["is_correct"],
            "score": it["score"],
            "feedback": it.get("feedback", "")[:80],
        }
        for it in items
    ]
    user = f"""请基于以下答题记录，生成一份学习分析报告。

学习主题：{topic}
学习难度：{level}
统计：共 {stats['total']} 题，答对 {stats['correct']} 题，正确率 {stats['accuracy']:.0%}，用时 {stats.get('duration_sec', 0)} 秒
逐题记录：{json.dumps(compact_items, ensure_ascii=False)}

输出 JSON：
{{
  "summary": "100～150 字，客观描述本次表现：掌握了什么、卡在哪里、整体处在什么水平。不要空泛鼓励。",
  "level_tag": "4～8 字，如「基础扎实」「概念混淆」「需要重学」",
  "knowledge_gaps": ["2～4 条具体知识缺口，每条不超过 30 字，必须来自错题或低分题"],
  "next_steps": ["2～4 条具体可执行的学习动作，每条不超过 40 字，要能今天就开始做"],
  "suggested_topics": ["2～3 个下一步可练习的关联主题"]
}}
要求：全部用中文、面向学习者本人说话、避免套话；纯 JSON，不要代码块。"""
    return {"system": SYSTEM_REPORTER, "user": user}