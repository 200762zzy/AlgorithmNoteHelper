"""SM-2 算法单元测试（对应项目文档 5.2 的用例 18–24）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from models import EASE_INITIAL, EASE_MIN, MASTERED_INTERVAL_DAYS, SrsState, today
from srs import (
    QUALITY_EASY,
    QUALITY_FORGOT,
    QUALITY_HARD,
    apply_review,
    is_due,
    is_mastered,
    new_state,
)

DAY = date(2026, 10, 13)


def state_at(next_review: date, interval: int = 1, repetitions: int = 1) -> SrsState:
    return SrsState(
        ease=EASE_INITIAL,
        interval=interval,
        repetitions=repetitions,
        next_review=next_review,
    )


# --- 初值与首次评分（用例 18） ---------------------------------------------


def test_new_state_defaults():
    state = new_state(DAY)
    assert state.ease == pytest.approx(EASE_INITIAL)
    assert state.interval == 0
    assert state.repetitions == 0
    assert state.next_review == DAY


def test_first_review_sets_interval_one_and_next_review_tomorrow():
    state = apply_review(new_state(DAY), QUALITY_EASY, DAY)
    assert state.interval == 1
    assert state.repetitions == 1
    assert state.next_review == DAY + timedelta(days=1)


# --- 间隔增长节奏（用例 20） -------------------------------------------------


def test_interval_only_multiplies_from_the_third_review():
    """前两次评分不进入乘法环节：1 → 6 → round(6 × ease)。

    这是文档里专门标注的易错点，也是原测试用例 14 写错的地方。
    """
    first = apply_review(new_state(DAY), QUALITY_HARD, DAY)
    second = apply_review(first, QUALITY_HARD, DAY)
    third = apply_review(second, QUALITY_HARD, DAY)

    assert first.interval == 1
    assert second.interval == 6
    # 乘法用的是**更新前**的 ease（标准 SM-2 的顺序）
    assert third.interval == round(second.interval * second.ease)
    assert third.interval == 13


def test_easy_path_intervals():
    state = new_state(DAY)
    intervals = []
    for _ in range(4):
        state = apply_review(state, QUALITY_EASY, DAY)
        intervals.append(state.interval)
    assert intervals == [1, 6, 16, 45]


def test_hard_path_intervals():
    state = new_state(DAY)
    intervals = []
    for _ in range(5):
        state = apply_review(state, QUALITY_HARD, DAY)
        intervals.append(state.interval)
    assert intervals == [1, 6, 13, 27, 52]


# --- ease 调整（用例 21） ---------------------------------------------------


def test_easy_review_raises_ease():
    state = apply_review(new_state(DAY), QUALITY_EASY, DAY)
    assert state.ease == pytest.approx(2.6)


def test_hard_review_lowers_ease_by_0_14():
    state = apply_review(new_state(DAY), QUALITY_HARD, DAY)
    assert state.ease == pytest.approx(2.36)


def test_ease_never_drops_below_floor():
    state = new_state(DAY)
    for _ in range(20):
        state = apply_review(state, QUALITY_HARD, DAY)
    assert state.ease == pytest.approx(EASE_MIN)


# --- 忘记（用例 19） --------------------------------------------------------


def test_forgot_resets_interval_but_keeps_ease():
    """必须在 interval 已放大之后再测，否则验证不到「重置」行为。

    这是原测试用例 13 的问题：在初始态（interval 本为 0）测，值从 0 变成 1，
    看起来通过了，其实什么都没验证。
    """
    grown = apply_review(apply_review(new_state(DAY), QUALITY_HARD, DAY), QUALITY_HARD, DAY)
    assert grown.interval == 6

    reset = apply_review(grown, QUALITY_FORGOT, DAY)
    assert reset.interval == 1
    assert reset.repetitions == 0
    assert reset.ease == pytest.approx(grown.ease)


# --- 掌握判定（用例 22） ----------------------------------------------------


def test_is_mastered_threshold():
    assert is_mastered(state_at(DAY, interval=MASTERED_INTERVAL_DAYS, repetitions=5))
    assert not is_mastered(
        state_at(DAY, interval=MASTERED_INTERVAL_DAYS - 1, repetitions=5)
    )


def test_easy_path_reaches_mastery_after_four_reviews():
    state = new_state(DAY)
    for _ in range(4):
        state = apply_review(state, QUALITY_EASY, DAY)
    assert is_mastered(state)


def test_hard_path_needs_five_reviews():
    state = new_state(DAY)
    for _ in range(4):
        state = apply_review(state, QUALITY_HARD, DAY)
    assert state.interval == 27
    assert not is_mastered(state)

    state = apply_review(state, QUALITY_HARD, DAY)
    assert state.interval == 52
    assert is_mastered(state)


# --- 到期判定（用例 23、24） -------------------------------------------------


def test_is_due_boundaries():
    base = state_at(DAY)
    assert is_due(base, DAY)  # 等于今天也算到期
    assert is_due(replace(base, next_review=DAY - timedelta(days=1)), DAY)
    assert not is_due(replace(base, next_review=DAY + timedelta(days=1)), DAY)


def test_schedule_follows_injected_day_not_real_today():
    """文档用例 24：结果不随运行时的真实日期变化。"""
    long_ago = date(2001, 1, 1)
    state = apply_review(new_state(long_ago), QUALITY_EASY, long_ago)
    assert state.next_review == date(2001, 1, 2)
    assert is_due(state, date(2001, 1, 2))
    assert not is_due(state, long_ago)


def test_today_returns_local_date():
    """时间基准必须是本地日期，不能用 UTC。"""
    assert today() == date.today()


# --- 纯函数性质 -------------------------------------------------------------


def test_apply_review_does_not_mutate_its_input():
    state = new_state(DAY)
    apply_review(state, QUALITY_EASY, DAY)
    assert state.interval == 0
    assert state.repetitions == 0


def test_quality_is_clamped_into_range():
    assert apply_review(new_state(DAY), 99, DAY).interval == 1
    assert apply_review(new_state(DAY), -5, DAY).interval == 1


def test_quality_must_be_an_integer():
    with pytest.raises(ValueError):
        apply_review(new_state(DAY), "轻松", DAY)
