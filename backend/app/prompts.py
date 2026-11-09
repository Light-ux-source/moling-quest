"""Prompt 资产：集中管理、可版本化、可评测。

v1.1 起使用 LangChain `ChatPromptTemplate` 编排（mustache 模板）。
- 变量用 ``{{name}}``，JSON 示例中的单花括号保持原样，避免转义地狱；
- 每条链都必须出现 "JSON" 字样，满足 DeepSeek JSON Output 的硬性要求；
- Prompt 与业务规则分离，后续可单独评测/替换。
"""

from __future__ import annotations

from typing import Dict

from langchain_core.prompts import ChatPromptTemplate

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
- 每道题额外给出 title（不超过 12 字的知识点短名，用于章节地图节点）与 knowledge_point（不超过 20 字的知识点全名）。
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

DIGEST_HUMAN = """请把下面的资料整理成用于出题的知识提纲。

学习主题：{{topic}}
学习难度：{{level_guide}}

检索资料：
{{source_text}}

输出 JSON，结构严格如下：
{
  "title": "本次学习的知识标题（不超过 20 字）",
  "summary": "80 字以内的整体概述",
  "key_points": [
    {"point": "一个可被出题的核心知识点（不超过 40 字）", "evidence": "资料中的依据，40 字以内", "source_url": "对应资料链接，没有则为空字符串"}
  ],
  "misconceptions": ["初学者最常见的 2～3 个误区"],
  "prerequisites": ["理解本主题需要的前置概念，最多 3 个"]
}

要求：
1. key_points 给 4～6 条，覆盖定义、机制、应用、边界四类；
2. 只使用资料中可靠的信息；资料冲突时以官方/一手来源为准；
3. 纯 JSON，不要代码块。"""

GENERATE_HUMAN = """请为「{{topic}}」生成 {{count}} 道练习题。

难度要求：{{level_guide}}
题型范围：{{type_desc}}（数量按此顺序轮转分配，至少包含一种客观题和一种主观题）
{{type_rules}}

知识提纲（出题范围以此为准）：
{{brief_json}}

可引用的来源链接（source_refs 只能从这里选，不得编造）：{{url_hint}}

输出 JSON，结构严格如下：
{
  "questions": [
    {
      "type": "single_choice | multiple_choice | true_false | short_answer",
      "title": "知识点短名（不超过 12 字）",
      "knowledge_point": "知识点全名（不超过 20 字）",
      "stem": "题干",
      "options": [{"key": "A", "text": "选项内容"}],
      "correct_answer": "B",
      "explanation": "解析",
      "difficulty": "easy | medium | hard",
      "rubric": ["简答题判分要点；客观题给空数组"],
      "source_refs": ["https://..."]
    }
  ]
}

硬性要求：
1. 恰好 {{count}} 题，seq 由程序生成，你不需要输出；
2. 题干不得直接照抄提纲原句，要改写为具体问题；
3. 干扰项必须是「看起来合理但确实错误」的表述，禁止使用明显荒谬项凑数；
4. 简答题的 correct_answer 必须是字符串数组（3～5 条得分要点），客观题为字符串或字符串数组；
5. 纯 JSON，不要代码块。"""

GRADE_HUMAN = """请批改下面这道简答题。

题目：{{stem}}
判分要点（rubric）：{{rubric_json}}
参考答案要点：{{correct_json}}
学生答案：{{answer_json}}
学习难度：{{level}}

评分标准：
- 覆盖全部要点且表述准确：0.9～1.0
- 覆盖大部分要点，个别不精确：0.6～0.9
- 只覆盖少部分要点：0.3～0.6
- 答非所问/空白/明显错误：0～0.3
- 学生用同义表达也应给分，不要求逐字一致。

输出 JSON：
{
  "score": 0.0,
  "correct": false,
  "feedback": "60 字以内，先肯定答对的部分，再指出缺什么、怎么补",
  "missing_points": ["未覆盖的要点"]
}
纯 JSON，不要代码块。"""

REPORT_HUMAN = """请基于以下答题记录，生成一份学习分析报告。

学习主题：{{topic}}
学习难度：{{level}}
统计：共 {{total}} 题，答对 {{correct}} 题，正确率 {{accuracy_pct}}，用时 {{duration}} 秒
逐题记录：{{items_json}}

输出 JSON：
{
  "summary": "100～150 字，客观描述本次表现：掌握了什么、卡在哪里、整体处在什么水平。不要空泛鼓励。",
  "level_tag": "4～8 字，如「基础扎实」「概念混淆」「需要重学」",
  "knowledge_gaps": ["2～4 条具体知识缺口，每条不超过 30 字，必须来自错题或低分题"],
  "next_steps": ["2～4 条具体可执行的学习动作，每条不超过 40 字，要能今天就开始做"],
  "suggested_topics": ["2～3 个下一步可练习的关联主题"]
}
要求：全部用中文、面向学习者本人说话、避免套话；纯 JSON，不要代码块。"""


def _prompt(system: str, human: str) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [("system", system), ("human", human)],
        template_format="mustache",
    )


PROMPTS: Dict[str, ChatPromptTemplate] = {
    "digest": _prompt(SYSTEM_GENERATOR, DIGEST_HUMAN),
    "generate": _prompt(SYSTEM_GENERATOR, GENERATE_HUMAN),
    "grade": _prompt(SYSTEM_GRADER, GRADE_HUMAN),
    "report": _prompt(SYSTEM_REPORTER, REPORT_HUMAN),
}