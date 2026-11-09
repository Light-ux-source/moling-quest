import json

from app.llm import extract_json
from app.services.question_gen import normalize_question, validate_questions
from app.utils import letters, overlap_ratio


def test_letters_variants():
    assert letters("A") == ["A"]
    assert letters(["a", "c"]) == ["A", "C"]
    assert letters("A,C") == ["A", "C"]
    assert letters("AB") == ["A", "B"]
    assert letters(None) == []


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('好的，结果如下：{"a": [1, 2]} 以上。') == {"a": [1, 2]}


def test_normalize_question_drops_bad_items():
    base = {
        "type": "single_choice",
        "stem": "关于 useEffect 依赖数组，下列说法正确的是？",
        "options": [{"key": "A", "text": "空数组只执行一次"}, {"key": "B", "text": "每次渲染都执行"}],
        "correct_answer": "A",
        "explanation": "空数组表示无依赖，只在挂载后执行一次。",
        "difficulty": "easy",
    }
    ok = normalize_question(base, seq=1, session_id="s_abcdef", allowed_urls=[])
    assert ok and ok["correct_answer"] == "A" and ok["seq"] == 1

    bad = dict(base, correct_answer="Z")
    assert normalize_question(bad, seq=1, session_id="s_abcdef", allowed_urls=[]) is None

    bad2 = dict(base, stem="短")
    assert normalize_question(bad2, seq=1, session_id="s_abcdef", allowed_urls=[]) is None


def test_validate_questions_filters_types_and_duplicates():
    raw = [
        {
            "type": "single_choice",
            "stem": "重复题干示例题目一",
            "options": [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
            "correct_answer": "A",
        },
        {
            "type": "single_choice",
            "stem": "重复题干示例题目一",
            "options": [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
            "correct_answer": "B",
        },
        {"type": "not_a_type", "stem": "非法题型示例题目", "options": [], "correct_answer": "A"},
    ]
    valid = validate_questions(
        raw,
        session_id="s_abcdef",
        count=5,
        allowed_types=["single_choice", "short_answer"],
        allowed_urls=[],
    )
    assert len(valid) == 1
    assert valid[0]["seq"] == 1


def test_overlap_ratio():
    assert overlap_ratio("先定义再讲机制最后给场景", ["定义", "机制"]) == 1.0
    assert overlap_ratio("", ["定义"]) == 0.0