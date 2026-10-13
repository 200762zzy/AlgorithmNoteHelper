"""SM-2 间隔重复算法：纯函数、无 IO、无状态。

接口边界（见项目文档 3.1）：本模块**不认识 `review_status`**，只处理 `SrsState`
与日期。把「状态」和「排期」组合起来判断是否进待复习队列，属于 `services.py`
的职责。守住这条边界，本模块才能纯函数式地被单测，不需要任何文件系统或 GUI。
"""

from __future__ import annotations

from datetime import date, timedelta

from models import (
    EASE_INITIAL,
    EASE_MIN,
    MASTERED_INTERVAL_DAYS,
    SrsState,
    today as default_today,
)

# 三档评分（见项目文档 2.1.3）
QUALITY_FORGOT = 1
QUALITY_HARD = 3
QUALITY_EASY = 5

QUALITY_RANGE = (0, 5)


def new_state(day: date | None = None) -> SrsState:
    """新建错题的初值：ease 2.5 / interval 0 / repetitions 0 / next_review = 创建日。

    `next_review` 取创建日意味着**新建条目当天就进入待复习队列**，这正是修掉
    「新建后永不复习」漏洞的关键（见项目文档 2.1.3）。
    """
    return SrsState(
        ease=EASE_INITIAL,
        interval=0,
        repetitions=0,
        next_review=_day(day),
    )


def apply_review(state: SrsState, quality: int, day: date | None = None) -> SrsState:
    """按 SM-2 计算评分后的新状态。

    间隔增长节奏（易被误解，见项目文档 3.2）：
    - 第 1 次评分（困难或轻松）恒得 `interval = 1`
    - 第 2 次恒得 `interval = 6`
    - **从第 3 次起**才按 `round(interval × ease)` 放大

    其中乘法用的是**更新前**的 ease（标准 SM-2 的顺序）。
    """
    quality = _clamp_quality(quality)
    base = _day(day)

    if quality >= 3:
        if state.repetitions == 0:
            interval = 1
        elif state.repetitions == 1:
            interval = 6
        else:
            interval = round(state.interval * state.ease)

        ease = state.ease + (
            0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
        )
        ease = max(ease, EASE_MIN)
        repetitions = state.repetitions + 1
    else:
        # "忘记"：重复次数归零、间隔重置，但 ease 保持不变
        # （原始 SM-2 原文即如此规定）
        interval = 1
        ease = state.ease
        repetitions = 0

    return SrsState(
        ease=ease,
        interval=interval,
        repetitions=repetitions,
        next_review=base + timedelta(days=interval),
    )


def is_due(state: SrsState, day: date | None = None) -> bool:
    """**仅按排期**判断是否到期：`next_review <= 今天`。

    这是纯排期判断，不含状态语义。组合判断请看 `services.Library.in_review_queue`。
    """
    return state.next_review <= _day(day)


def is_mastered(
    state: SrsState, threshold: int = MASTERED_INTERVAL_DAYS
) -> bool:
    """间隔达到阈值即视为「已掌握」。

    注意 `mastered` **不是终态**：它表示"已进入长间隔"，仍继续参与调度，
    只是入队时多一个宽限期（见 `services`）。
    """
    return state.interval >= threshold


def _clamp_quality(quality: int) -> int:
    try:
        value = int(quality)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"评分必须是整数：{quality!r}") from exc
    low, high = QUALITY_RANGE
    return max(low, min(high, value))


def _day(day: date | None) -> date:
    return default_today() if day is None else day
