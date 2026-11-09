"""结算/段位/连续学习纯函数测试。"""

from __future__ import annotations

from datetime import date, timedelta

from app.services.settlement import (
    combo_for,
    exp_for,
    rank_for_exp,
    stars_for_accuracy,
    streak_days,
)


def test_stars_thresholds():
    assert stars_for_accuracy(0.0) == 0
    assert stars_for_accuracy(0.599) == 0
    assert stars_for_accuracy(0.6) == 1
    assert stars_for_accuracy(0.799) == 1
    assert stars_for_accuracy(0.8) == 2
    assert stars_for_accuracy(0.999) == 2
    assert stars_for_accuracy(1.0) == 3


def test_exp_formula_matches_prototype():
    assert exp_for(correct=4, stars=2) == 120
    assert exp_for(correct=5, stars=3) == 160
    assert exp_for(correct=0, stars=0) == 0
    assert exp_for(correct=5, stars=3, daily_bonus=30) == 190


def test_combo_counts_longest_streak():
    assert combo_for([True, True, False, True, True, True]) == 3
    assert combo_for([]) == 0
    assert combo_for([False, False]) == 0


def test_rank_for_exp_boundaries():
    first = rank_for_exp(0)
    assert first["key"] == "S1"
    assert first["next_key"] == "S2"
    assert first["exp_to_next"] == 100

    second = rank_for_exp(100)
    assert second["key"] == "S2"
    assert second["next_key"] == "S3"

    near = rank_for_exp(99)
    assert near["key"] == "S1"
    assert near["exp_to_next"] == 1

    top = rank_for_exp(5000)
    assert top["key"] == "S6"
    assert top["next_key"] is None
    assert top["exp_to_next"] == 0


def test_streak_days():
    today = date(2026, 11, 9)
    assert streak_days([today, today - timedelta(days=1), today - timedelta(days=2)], today) == 3
    assert streak_days([today - timedelta(days=1), today - timedelta(days=2)], today) == 2
    assert streak_days([], today) == 0
    assert streak_days([today - timedelta(days=3)], today) == 0