"""复习计划：把「循环复习队列」画出来。

两件事：
- 上方柱状图给出未来若干天的**到期分布**（最左边一根是逾期），一眼看出复习压力落在哪天；
- 下方按到期日**分组列出**具体是哪几道，双击可直接跳到主窗口里那一条。

这里展示的是"复习循环本身"，所以已掌握的条目也在其中——它们不是终点，只是间隔被拉长了。
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui.theme as theme
from models import MistakeEntry, ReviewStatus, today as default_today

CHART_DAYS = 14

_BAR_COLOR = QColor("#a9c0b4")
_TODAY_COLOR = QColor(theme.ACCENT)
_OVERDUE_COLOR = QColor("#c0714a")
_GRID_COLOR = QColor("#e3e6e9")
_TEXT_COLOR = QColor("#5c656d")
_BACKGROUND = QColor("#ffffff")


class DueChart(QWidget):
    """未来若干天的到期分布柱状图。最左边一根代表逾期。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars: list[tuple[str, int, QColor]] = []
        self.setMinimumHeight(150)

    def set_bars(self, bars: list[tuple[str, int, QColor]]) -> None:
        self._bars = bars
        self.update()

    def bars(self) -> list[tuple[str, int, QColor]]:
        return list(self._bars)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), _BACKGROUND)
        if not self._bars:
            return

        width = float(self.width())
        height = float(self.height())
        top = 24.0
        bottom = height - 28.0
        slot = width / len(self._bars)
        bar_width = max(6.0, slot * 0.54)
        peak = max(count for _label, count, _color in self._bars) or 1

        painter.setPen(QPen(_GRID_COLOR, 1))
        painter.drawLine(0, int(bottom), int(width), int(bottom))

        font = QFont(self.font())
        font.setPointSize(8)
        painter.setFont(font)

        for index, (label, count, color) in enumerate(self._bars):
            center = slot * (index + 0.5)
            if count:
                bar_height = (bottom - top) * count / peak
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(color))
                painter.drawRoundedRect(
                    QRectF(center - bar_width / 2, bottom - bar_height, bar_width, bar_height),
                    3.0,
                    3.0,
                )
                painter.setPen(_TEXT_COLOR)
                painter.drawText(
                    QRectF(center - slot / 2, bottom - bar_height - 18, slot, 16),
                    Qt.AlignHCenter | Qt.AlignBottom,
                    str(count),
                )
            painter.setPen(_TEXT_COLOR)
            painter.drawText(
                QRectF(center - slot / 2, bottom + 5, slot, 20),
                Qt.AlignHCenter | Qt.AlignTop,
                label,
            )


class ScheduleDialog(QDialog):
    """复习计划视图。双击某条 → 关闭并让主窗口跳过去。"""

    def __init__(self, library, day: date | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("复习计划")
        self.resize(880, 660)
        self.setMinimumSize(620, 460)

        self._day = library._day(day) if day is None else day  # noqa: SLF001
        self._chosen: str | None = None
        schedule = library.schedule(day=self._day, horizon_days=CHART_DAYS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addWidget(self._summary_label(library))
        layout.addWidget(self._hint_label())

        self.chart = DueChart()
        self.chart.set_bars(self._bars(schedule))
        layout.addWidget(self.chart)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["题目", "标签 · 难度 · 状态 · 到期"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setRootIsDecorated(True)
        self.tree.itemDoubleClicked.connect(self._on_activated)
        layout.addWidget(self.tree, 1)

        if not library.entries:
            empty = QLabel("还没有错题。新建一条之后，它的复习循环就会出现在这里。")
            empty.setObjectName("hint")
            layout.addWidget(empty)

        self._fill_tree(schedule)

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("关闭")
        close.setObjectName("primary")
        close.setDefault(True)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)

    # -- 对外 ------------------------------------------------------------

    def chosen_entry_id(self) -> str | None:
        return self._chosen

    # -- 构建 ------------------------------------------------------------

    def _summary_label(self, library) -> QLabel:
        entries = library.entries
        unreviewed = sum(1 for e in entries if e.last_review_time is None)
        mastered = sum(1 for e in entries if e.review_status is ReviewStatus.MASTERED)
        due_today = len(library.due_queue(self._day))
        label = QLabel(
            f"共 {len(entries)} 条 · 未复习 {unreviewed} · 今天该复习 {due_today} · 已掌握 {mastered}"
        )
        label.setStyleSheet("font-weight: 600;")
        return label

    def _hint_label(self) -> QLabel:
        label = QLabel(
            "两根柱子之间的间隔就是 SM-2 拉长的复习间隔。已掌握的条目也在其中 —— "
            "它们逾期超过宽限期后会重新回到「今天该复习」。双击某条可直接跳过去。"
        )
        label.setObjectName("hint")
        label.setWordWrap(True)
        return label

    def _bars(self, schedule) -> list[tuple[str, int, QColor]]:
        bars: list[tuple[str, int, QColor]] = [("逾期", len(schedule.overdue), _OVERDUE_COLOR)]
        for offset, when in enumerate(sorted(schedule.by_day)):
            if offset == 0:
                label, color = "今天", _TODAY_COLOR
            elif offset == 1:
                label, color = "明天", _BAR_COLOR
            else:
                label, color = f"{when.month}-{when.day}", _BAR_COLOR
            bars.append((label, len(schedule.by_day[when]), color))
        return bars

    def _fill_tree(self, schedule) -> None:
        self._add_bucket("逾期未复习", schedule.overdue, highlight=True)
        for offset, when in enumerate(sorted(schedule.by_day)):
            if offset == 0:
                label = f"今天 · {when}"
            elif offset == 1:
                label = f"明天 · {when}"
            else:
                label = f"{when.month} 月 {when.day} 日"
            self._add_bucket(label, schedule.by_day[when], highlight=(offset == 0))
        if schedule.later:
            self._add_bucket(f"{CHART_DAYS} 天以后", schedule.later)

    def _add_bucket(self, label: str, entries: list[MistakeEntry], *, highlight: bool = False) -> None:
        if not entries:
            return
        top = QTreeWidgetItem([f"{label}（{len(entries)}）", ""])
        font = top.font(0)
        font.setBold(True)
        top.setFont(0, font)
        if highlight:
            top.setForeground(0, QBrush(_OVERDUE_COLOR if "逾期" in label else _TODAY_COLOR))
        self.tree.addTopLevelItem(top)

        for entry in entries:
            child = QTreeWidgetItem([entry.title, _entry_meta(entry)])
            child.setData(0, Qt.UserRole, entry.id)
            child.setToolTip(0, entry.title)
            if entry.review_status is ReviewStatus.MASTERED:
                child.setForeground(0, QBrush(QColor("#8b939b")))
                child.setForeground(1, QBrush(QColor("#8b939b")))
            top.addChild(child)
        top.setExpanded(True)

    def _on_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        entry_id = item.data(0, Qt.UserRole)
        if entry_id:
            self._chosen = str(entry_id)
            self.accept()


def _entry_meta(entry: MistakeEntry) -> str:
    parts: list[str] = []
    if entry.tags:
        parts.append("、".join(entry.tags[:3]))
    parts.append(entry.difficulty.zh)
    parts.append(entry.review_status.zh)
    when = entry.srs.next_review
    parts.append(f"{when.month}-{when.day}")
    return " · ".join(parts)
