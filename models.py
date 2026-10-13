"""数据结构与枚举，以及全项目唯一的「今天」来源。

分层约束（见项目文档 3.1）：本模块不得 import 任何 Qt 模块，以便数据层与
业务层可以在没有 GUI 环境的机器上直接用 pytest 测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

# --------------------------------------------------------------------------
# 调度参数（属于持久化契约的一部分：改动它们会改变既有数据的语义）
# --------------------------------------------------------------------------

EASE_INITIAL = 2.5
EASE_MIN = 1.3
MASTERED_INTERVAL_DAYS = 30
MASTERED_GRACE_DAYS = 7


# --------------------------------------------------------------------------
# 时间基准：全项目唯一来源
# --------------------------------------------------------------------------


def today() -> date:
    """返回**本地日期**。

    约定（见项目文档 3.2）：全项目只允许这一处取「今天」，其余代码一律调用
    它或接收注入的日期参数。**禁止使用 `utcnow()` / UTC 日期** —— UTC+8 下会
    让每天 08:00 之前的到期判定偏差整整一天。
    """
    return date.today()


def now_iso() -> str:
    """本地时间戳，ISO 8601，秒精度，与文档示例格式一致。"""
    return datetime.now().replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------
# 枚举
# --------------------------------------------------------------------------


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

    @property
    def zh(self) -> str:
        return _DIFFICULTY_ZH[self]

    @classmethod
    def from_zh(cls, text: str) -> "Difficulty":
        return _reverse(_DIFFICULTY_ZH, text, cls)


class ErrorCategory(str, Enum):
    BOUNDARY = "boundary"
    OVERFLOW = "overflow"
    NO_IDEA = "no_idea"
    SYNTAX_BUG = "syntax_bug"
    OTHER = "other"

    @property
    def zh(self) -> str:
        return _ERROR_CATEGORY_ZH[self]

    @classmethod
    def from_zh(cls, text: str) -> "ErrorCategory":
        return _reverse(_ERROR_CATEGORY_ZH, text, cls)


class ReviewStatus(str, Enum):
    """只有两态。

    `todo`（未复习）已被移除：它的定义就是 `last_review_time is null`，是可派生
    的事实，存成状态字段会制造第二个真相来源，并导致「新建的错题永远不进待复习
    队列」这一漏洞（见项目文档 2.1.3）。
    """

    DUE = "due"
    MASTERED = "mastered"

    @property
    def zh(self) -> str:
        return _REVIEW_STATUS_ZH[self]

    @classmethod
    def from_zh(cls, text: str) -> "ReviewStatus":
        return _reverse(_REVIEW_STATUS_ZH, text, cls)


class StatusFilter(str, Enum):
    """列表筛选口径（见项目文档 2.1.2）。

    `DUE` 与 `DUE_TODAY` 是**两件不同的事**，这里混淆过一次，所以写明：

    - `DUE`：按**状态**筛选，`review_status == due`。刚复习完、下次排在几天后的条目
      仍然属于这一档 —— 它还在复习轮次里，只是今天不用再看。
    - `DUE_TODAY`：按**队列**筛选，即"今天到期、该复习的"。它比 `DUE` 窄。
      曾经把 `DUE` 直接当成队列语义，结果刚复习完的条目在每一个筛选口径下都找不到，
      界面上看起来像是数据丢了。
    - `UNREVIEWED`：派生视图（`last_review_time is null`），不落库。
    """

    ALL = "all"
    UNREVIEWED = "unreviewed"
    DUE = "due"
    DUE_TODAY = "due_today"
    MASTERED = "mastered"


_DIFFICULTY_ZH = {
    Difficulty.EASY: "简单",
    Difficulty.MEDIUM: "中等",
    Difficulty.HARD: "困难",
}
_ERROR_CATEGORY_ZH = {
    ErrorCategory.BOUNDARY: "边界错误",
    ErrorCategory.OVERFLOW: "溢出",
    ErrorCategory.NO_IDEA: "思路不会",
    ErrorCategory.SYNTAX_BUG: "低级语法 bug",
    ErrorCategory.OTHER: "其他",
}
_REVIEW_STATUS_ZH = {
    ReviewStatus.DUE: "待复习",
    ReviewStatus.MASTERED: "已掌握",
}


def _reverse(mapping: dict, text: str, enum_cls):
    """按中文标签或英文值反查枚举成员。"""
    target = (text or "").strip()
    for member, label in mapping.items():
        if target == label:
            return member
    return enum_cls(target.lower())


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SrsState:
    """SM-2 调度参数。不可变：评分产生新实例，便于把算法当纯函数测试。"""

    ease: float
    interval: int
    repetitions: int
    next_review: date


@dataclass
class Note:
    """`notes/{id}.md` 的正文各小节。"""

    wrong_idea: str = ""
    wrong_code: str = ""
    cause_detail: str = ""
    correct_idea: str = ""
    ac_code: str = ""
    summary: str = ""

    def is_empty(self) -> bool:
        return not any(
            value.strip()
            for value in (
                self.wrong_idea,
                self.wrong_code,
                self.cause_detail,
                self.correct_idea,
                self.ac_code,
                self.summary,
            )
        )

    def to_dict(self) -> dict:
        return {
            "wrong_idea": self.wrong_idea,
            "wrong_code": self.wrong_code,
            "cause_detail": self.cause_detail,
            "correct_idea": self.correct_idea,
            "ac_code": self.ac_code,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "Note":
        data = data or {}
        return cls(
            wrong_idea=str(data.get("wrong_idea") or ""),
            wrong_code=str(data.get("wrong_code") or ""),
            cause_detail=str(data.get("cause_detail") or ""),
            correct_idea=str(data.get("correct_idea") or ""),
            ac_code=str(data.get("ac_code") or ""),
            summary=str(data.get("summary") or ""),
        )


def _parse_date(value) -> date:
    """接受 `date` 或 `YYYY-MM-DD` 字符串。"""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value.strip()[:10])
    raise ValueError(f"无法解析日期：{value!r}")


@dataclass
class MistakeEntry:
    """一条错题。可直接序列化为 `index.json` 中的元素。

    注意 `id` 同时是 md 文件名，读入时必须用 `storage.validate_id()` 校验。
    """

    id: str
    title: str
    srs: SrsState
    link: str = ""
    tags: list[str] = field(default_factory=list)
    difficulty: Difficulty = Difficulty.MEDIUM
    error_category: ErrorCategory = ErrorCategory.OTHER
    review_status: ReviewStatus = ReviewStatus.DUE
    created_at: str = ""
    last_review_time: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "link": self.link,
            "tags": list(self.tags),
            "difficulty": self.difficulty.value,
            "error_category": self.error_category.value,
            "review_status": self.review_status.value,
            "created_at": self.created_at,
            "last_review_time": self.last_review_time,
            "srs": {
                "ease": round(float(self.srs.ease), 4),
                "interval": int(self.srs.interval),
                "repetitions": int(self.srs.repetitions),
                "next_review": self.srs.next_review.isoformat(),
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MistakeEntry":
        if not isinstance(data, dict):
            raise ValueError(f"条目应为对象，实际为 {type(data).__name__}")
        if "id" not in data:
            raise ValueError("条目缺少 id 字段")
        raw_srs = data.get("srs")
        if not isinstance(raw_srs, dict):
            raw_srs = {}
        srs = SrsState(
            ease=float(raw_srs.get("ease", EASE_INITIAL)),
            interval=int(raw_srs.get("interval", 0)),
            repetitions=int(raw_srs.get("repetitions", 0)),
            next_review=_parse_date(raw_srs.get("next_review", date.today())),
        )
        tags = data.get("tags") or []
        if not isinstance(tags, (list, tuple)):
            raise ValueError("tags 应为数组")
        last_review = data.get("last_review_time")
        return cls(
            id=str(data["id"]),
            title=str(data.get("title") or ""),
            srs=srs,
            link=str(data.get("link") or ""),
            tags=[str(tag) for tag in tags],
            difficulty=Difficulty(data.get("difficulty") or Difficulty.MEDIUM.value),
            error_category=ErrorCategory(
                data.get("error_category") or ErrorCategory.OTHER.value
            ),
            review_status=ReviewStatus(
                data.get("review_status") or ReviewStatus.DUE.value
            ),
            created_at=str(data.get("created_at") or ""),
            last_review_time=None if last_review is None else str(last_review),
        )
