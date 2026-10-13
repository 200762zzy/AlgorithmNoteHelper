"""左侧面板：错题列表 + 筛选栏（见项目文档 3.4）。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from models import Difficulty, ReviewStatus, StatusFilter

ALL = "__all__"

_DIFFICULTY_CHOICES = (
    (ALL, "全部难度"),
    (Difficulty.EASY.value, "简单"),
    (Difficulty.MEDIUM.value, "中等"),
    (Difficulty.HARD.value, "困难"),
)
_STATUS_CHOICES = (
    (ALL, "全部状态"),
    (StatusFilter.UNREVIEWED.value, "未复习"),
    (StatusFilter.DUE.value, "待复习"),
    (StatusFilter.DUE_TODAY.value, "今天该复习"),
    (StatusFilter.MASTERED.value, "已掌握"),
)

_MASTERED_COLOR = QColor("#8b939b")


class EntryListPanel(QWidget):
    """列表与筛选。只负责展示与收集条件，不做任何数据读写。"""

    selection_changed = Signal(str)
    filters_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText("搜索题目简述 / 标签 / 错因")
        self.keyword.setClearButtonEnabled(True)
        layout.addWidget(self.keyword)

        row_one = QHBoxLayout()
        row_one.setSpacing(6)
        self.tag = QComboBox()
        self.difficulty = QComboBox()
        for value, label in _DIFFICULTY_CHOICES:
            self.difficulty.addItem(label, value)
        row_one.addWidget(self.tag, 1)
        row_one.addWidget(self.difficulty, 1)
        layout.addLayout(row_one)

        row_two = QHBoxLayout()
        row_two.setSpacing(6)
        self.status = QComboBox()
        for value, label in _STATUS_CHOICES:
            self.status.addItem(label, value)
        self.due_button = QPushButton("今天该复习 (0)")
        self.due_button.setToolTip(
            "只看今天到期、该复习的条目（每周复盘用）。"
            "注意它比「待复习」状态更窄：刚复习完的条目状态仍是待复习，但今天不用再看"
        )
        row_two.addWidget(self.status, 1)
        row_two.addWidget(self.due_button)
        layout.addLayout(row_two)

        self.list = QListWidget()
        self.list.setUniformItemSizes(False)
        self.list.setWordWrap(False)
        layout.addWidget(self.list, 1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("hint")
        layout.addWidget(self.count_label)

        self.set_tags([])

        self.keyword.textChanged.connect(self._emit_filters)
        for combo in (self.tag, self.difficulty, self.status):
            combo.currentIndexChanged.connect(self._emit_filters)
        self.due_button.clicked.connect(self._on_due_clicked)
        self.list.currentItemChanged.connect(self._on_current_changed)

    # -- 对外接口 --------------------------------------------------------

    def filters(self) -> dict:
        """把控件状态翻译成 `Library.search()` 的关键字参数。"""
        tag = self.tag.currentData()
        difficulty = self.difficulty.currentData()
        status = self.status.currentData()
        return {
            "keyword": self.keyword.text().strip() or None,
            "tags": None if tag in (None, ALL) else [tag],
            "difficulty": None if difficulty in (None, ALL) else Difficulty(difficulty),
            "status": None if status in (None, ALL) else StatusFilter(status),
        }

    def set_entries(self, entries, due_ids: set[str] | None = None) -> None:
        """重建列表。重建期间屏蔽信号，避免把「清空」误当成用户切换选中项。"""
        due_ids = due_ids or set()
        self._loading = True
        self.list.blockSignals(True)
        self.list.clear()
        for entry in entries:
            item = QListWidgetItem(_item_text(entry, entry.id in due_ids))
            item.setData(Qt.UserRole, entry.id)
            item.setToolTip(entry.title)
            if entry.review_status is ReviewStatus.MASTERED:
                item.setForeground(QBrush(_MASTERED_COLOR))
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._loading = False
        self.count_label.setText(f"共 {len(entries)} 条" if entries else "没有符合条件的错题")

    def set_tags(self, tags: list[str]) -> None:
        """刷新标签下拉，尽量保持当前选择。"""
        previous = self.tag.currentData()
        self.tag.blockSignals(True)
        self.tag.clear()
        self.tag.addItem("全部标签", ALL)
        for tag in tags:
            self.tag.addItem(tag, tag)
        index = self.tag.findData(previous)
        self.tag.setCurrentIndex(index if index >= 0 else 0)
        self.tag.blockSignals(False)

    def set_due_count(self, count: int) -> None:
        self.due_button.setText(f"今天该复习 ({count})")

    def select(self, entry_id: str) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.UserRole) == entry_id:
                self.list.setCurrentItem(item)
                return

    def current_id(self) -> str | None:
        item = self.list.currentItem()
        return None if item is None else item.data(Qt.UserRole)

    def clear_selection(self) -> None:
        self._loading = True
        self.list.blockSignals(True)
        self.list.setCurrentItem(None)
        self.list.blockSignals(False)
        self._loading = False

    def clear_filters(self) -> None:
        """把所有筛选条件复位，但**不**触发刷新（由调用方决定何时刷新）。

        从「复习计划」跳到某一条时必须先做这件事：目标条目可能被关键词、标签或
        状态筛选挡在外面。
        """
        self._loading = True
        try:
            self.keyword.clear()
            for combo in (self.tag, self.difficulty, self.status):
                combo.setCurrentIndex(0)
        finally:
            self._loading = False

    # -- 内部 ------------------------------------------------------------

    def _emit_filters(self, *_args) -> None:
        if not self._loading:
            self.filters_changed.emit()

    def _on_current_changed(self, current, _previous) -> None:
        if self._loading:
            return
        entry_id = None if current is None else current.data(Qt.UserRole)
        self.selection_changed.emit(entry_id or "")

    def _on_due_clicked(self) -> None:
        index = self.status.findData(StatusFilter.DUE_TODAY.value)
        if index >= 0:
            self.status.setCurrentIndex(index)
        else:
            self.filters_changed.emit()


def _item_text(entry, is_due_today: bool) -> str:
    meta = []
    if entry.tags:
        shown = "、".join(entry.tags[:3])
        if len(entry.tags) > 3:
            shown += f" +{len(entry.tags) - 3}"
        meta.append(shown)
    meta.append(entry.difficulty.zh)
    meta.append(entry.error_category.zh)
    meta.append(_schedule_text(entry, is_due_today))
    first_line = ("● " if is_due_today else "") + entry.title
    return f"{first_line}\n{' · '.join(meta)}"


def _schedule_text(entry, is_due_today: bool) -> str:
    """把排期写进列表第二行。

    这一行是修一个真实缺陷的产物：复习完的条目状态**仍是「待复习」**，但已经不在
    「今天该复习」队列里了。不显示下次日期的话，用户只会看到它"消失了"。
    """
    if entry.review_status is ReviewStatus.MASTERED:
        return f"已掌握 · {_short_date(entry.srs.next_review)}"
    if is_due_today:
        return "待复习 · 今天"
    return f"待复习 · {_short_date(entry.srs.next_review)}"


def _short_date(value) -> str:
    return f"{value.month}-{value.day}"
