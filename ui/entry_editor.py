"""右侧面板：详情编辑区（字段-控件映射见项目文档 3.4）。

编辑器有三种模式：
- `empty`：没有选中任何条目；
- `new`：正在编辑一条尚未落盘的新错题（只有点了保存才会写进索引）；
- `edit`：正在编辑一条已有条目。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import ui.theme as theme
from models import Difficulty, ErrorCategory, Note, ReviewStatus
from ui.code_dialog import CodeDialog
from ui.highlighter import attach as attach_cpp_highlighter

MODE_EMPTY = "empty"
MODE_NEW = "new"
MODE_EDIT = "edit"

_DIFFICULTY_CHOICES = (
    (Difficulty.EASY.value, "简单"),
    (Difficulty.MEDIUM.value, "中等"),
    (Difficulty.HARD.value, "困难"),
)
_ERROR_CATEGORY_CHOICES = (
    (ErrorCategory.BOUNDARY.value, "边界错误"),
    (ErrorCategory.OVERFLOW.value, "溢出"),
    (ErrorCategory.NO_IDEA.value, "思路不会"),
    (ErrorCategory.SYNTAX_BUG.value, "低级语法 bug"),
    (ErrorCategory.OTHER.value, "其他"),
)
_STATUS_CHOICES = (
    (ReviewStatus.DUE.value, "待复习"),
    (ReviewStatus.MASTERED.value, "已掌握"),
)


class TagEditor(QWidget):
    """标签输入：回车添加、可多选删除（见文档 3.4 的控件映射）。"""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入标签后回车添加，可用逗号分隔多个")
        self.input.returnPressed.connect(self.add_from_input)
        row.addWidget(self.input, 1)
        add_button = QPushButton("添加")
        add_button.clicked.connect(self.add_from_input)
        row.addWidget(add_button)
        self.remove_button = QPushButton("删除选中")
        self.remove_button.clicked.connect(self.remove_selected)
        row.addWidget(self.remove_button)
        layout.addLayout(row)

        self.list = QListWidget()
        self.list.setObjectName("tagList")
        self.list.setMaximumHeight(56)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        layout.addWidget(self.list)

    def add_from_input(self) -> None:
        raw = self.input.text()
        if not raw.strip():
            return
        for chunk in raw.replace("，", ",").split(","):
            self.add_tag(chunk)
        self.input.clear()

    def add_tag(self, tag: str) -> bool:
        text = tag.strip()
        if not text:
            return False
        if text.lower() in {self._tag_at(row).lower() for row in range(self.list.count())}:
            return False
        self.list.addItem(text)
        self.changed.emit()
        return True

    def remove_selected(self) -> None:
        items = self.list.selectedItems()
        if not items:
            return
        for item in items:
            self.list.takeItem(self.list.row(item))
        self.changed.emit()

    def set_tags(self, tags: list[str]) -> None:
        self._loading = True
        self.list.clear()
        for tag in tags:
            self.list.addItem(tag)
        self.input.clear()
        self._loading = False

    def tags(self) -> list[str]:
        return [self._tag_at(row) for row in range(self.list.count())]

    def _tag_at(self, row: int) -> str:
        item = self.list.item(row)
        return "" if item is None else item.text()


class EntryEditor(QWidget):
    """详情编辑区。不做校验以外的业务判断，落盘一律交给 MainWindow 调 Library。"""

    dirty_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = MODE_EMPTY
        self._entry_id: str | None = None
        self._dirty = False
        self._loading = False
        self._build()
        self._set_enabled(False)

    # -- 构建 ------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self.placeholder = QLabel("从左侧选择一条错题，或点工具栏的「新建」")
        self.placeholder.setObjectName("hint")
        self.placeholder.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.placeholder)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, 1)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 8, 2)
        layout.setSpacing(12)

        # 题目信息
        info_box = QGroupBox("题目信息")
        info = QFormLayout(info_box)
        info.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info.setSpacing(8)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("题目简述（必填）")
        info.addRow("题目简述 *", self.title_edit)

        self.link_edit = QLineEdit()
        self.link_edit.setPlaceholderText("题目链接（可空）")
        info.addRow("题目链接", self.link_edit)

        self.tag_editor = TagEditor()
        info.addRow("标签", self.tag_editor)

        self.difficulty_combo = QComboBox()
        for value, label in _DIFFICULTY_CHOICES:
            self.difficulty_combo.addItem(label, value)
        info.addRow("难度", self.difficulty_combo)

        self.category_combo = QComboBox()
        for value, label in _ERROR_CATEGORY_CHOICES:
            self.category_combo.addItem(label, value)
        info.addRow("错因分类", self.category_combo)

        layout.addWidget(info_box)

        # 错误与订正
        body_box = QGroupBox("错误与订正")
        body = QVBoxLayout(body_box)
        body.setSpacing(5)

        self.wrong_idea_edit = self._add_text_block(
            body, "我的错误思路", "当时是怎么想的、错在哪一步", mono=False, height=80
        )
        self.wrong_code_edit = self._add_text_block(
            body, "错误代码（C++）", "// 错误代码", mono=True, height=200
        )
        self.cause_detail_edit = self._add_text_block(
            body, "错因详述", "如：边界错误 —— 数组开到 n 而非 n+1", mono=False, height=80
        )
        self.correct_idea_edit = self._add_text_block(
            body, "正确思路", "关键观察、状态定义、转移方程等", mono=False, height=88
        )
        self.ac_code_edit = self._add_text_block(
            body, "AC 代码（C++）", "// 正确代码", mono=True, height=200
        )
        self.summary_edit = self._add_text_block(
            body, "复盘总结", "这类题的通用套路、下次如何避免", mono=False, height=80
        )
        layout.addWidget(body_box)

        # 复习
        review_box = QGroupBox("复习")
        review = QHBoxLayout(review_box)
        review.setSpacing(8)
        review.addWidget(QLabel("复习状态"))
        self.status_combo = QComboBox()
        for value, label in _STATUS_CHOICES:
            self.status_combo.addItem(label, value)
        self.status_combo.setToolTip("可手动覆盖 SM-2 的结果；手动值写入后，下次评分仍按 SM-2 续算")
        review.addWidget(self.status_combo)
        self.review_hint = QLabel("")
        self.review_hint.setObjectName("hint")
        # 必须允许收缩并换行：这行文字（间隔/系数/下次）的最小宽度会把详情区
        # 顶到 520px 以上，900px 窄窗下就会冒出横向滚动条。
        self.review_hint.setWordWrap(True)
        self.review_hint.setMinimumWidth(110)
        review.addWidget(self.review_hint, 1)
        self.review_button = QPushButton("完成复习")
        self.review_button.setObjectName("primary")
        review.addWidget(self.review_button)
        layout.addWidget(review_box)

        # 不再加尾部 stretch：多余空间应当给 Expanding 的代码框，而不是留白

        # 脏标记
        self.title_edit.textChanged.connect(self._on_edited)
        self.link_edit.textChanged.connect(self._on_edited)
        self.difficulty_combo.currentIndexChanged.connect(self._on_edited)
        self.category_combo.currentIndexChanged.connect(self._on_edited)
        self.status_combo.currentIndexChanged.connect(self._on_edited)
        self.tag_editor.changed.connect(self._on_edited)
        for editor in self._text_editors():
            editor.textChanged.connect(self._on_edited)

    def _add_text_block(
        self, parent_layout, label: str, placeholder: str, *, mono: bool, height: int
    ):
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(QLabel(label))
        header.addStretch(1)

        editor = QPlainTextEdit()
        editor.setPlaceholderText(placeholder)

        if mono:
            # 代码是这个工具里最需要通读的内容，所以给它两样东西：
            # 1) 足够的最小高度 + 纵向 Expanding —— 窗口变高时多余空间全给代码框；
            # 2) 不折行 —— 长行用横向滚动条看，折行反而更难读。
            editor.setFont(theme.mono_font(10))
            editor.setLineWrapMode(QPlainTextEdit.NoWrap)
            editor.setMinimumHeight(height)
            editor.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            attach_cpp_highlighter(editor)
            zoom = QPushButton("放大")
            zoom.setToolTip("用接近全屏的窗口查看／编辑这段代码")
            zoom.clicked.connect(lambda _=False, box=editor, name=label: self._zoom(box, name))
            header.addWidget(zoom)
        else:
            # 散文框定高：QPlainTextEdit 默认纵向 Expanding，若只设最小高度，
            # 剩余空间会被最上面那个框独吞，表单看起来头重脚轻。
            editor.setFixedHeight(height)

        parent_layout.addLayout(header)
        parent_layout.addWidget(editor)
        return editor

    def _zoom(self, editor: QPlainTextEdit, title: str) -> None:
        updated = CodeDialog.edit(self, editor.toPlainText(), title)
        if updated is None or updated == editor.toPlainText():
            return
        # setPlainText 会触发 textChanged，脏标记由 _on_edited 统一处理
        editor.setPlainText(updated)

    def _text_editors(self) -> tuple[QPlainTextEdit, ...]:
        return (
            self.wrong_idea_edit,
            self.wrong_code_edit,
            self.cause_detail_edit,
            self.correct_idea_edit,
            self.ac_code_edit,
            self.summary_edit,
        )

    # -- 状态 ------------------------------------------------------------

    @property
    def entry_id(self) -> str | None:
        return self._entry_id

    @property
    def mode(self) -> str:
        return self._mode

    def is_new(self) -> bool:
        return self._mode == MODE_NEW

    def is_dirty(self) -> bool:
        return self._dirty

    def mark_clean(self) -> None:
        self._dirty = False
        self.dirty_changed.emit(False)

    def _on_edited(self, *_args) -> None:
        if self._loading or self._mode == MODE_EMPTY:
            return
        if not self._dirty:
            self._dirty = True
            self.dirty_changed.emit(True)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (
            self.title_edit,
            self.link_edit,
            self.tag_editor,
            self.difficulty_combo,
            self.category_combo,
            self.status_combo,
            self.review_button,
            *self._text_editors(),
        ):
            widget.setEnabled(enabled)

    # -- 载入 ------------------------------------------------------------

    def clear(self) -> None:
        """没有选中条目。"""
        self._loading = True
        self._mode = MODE_EMPTY
        self._entry_id = None
        self.placeholder.setVisible(True)
        self._set_enabled(False)
        self._reset_fields()
        self._loading = False
        self.mark_clean()

    def load_new(self) -> None:
        """开始一条尚未落盘的新错题：默认「中等 / 其他 / 待复习」。"""
        self._loading = True
        self._mode = MODE_NEW
        self._entry_id = None
        self._reset_fields()
        self._set_enabled(True)
        self.placeholder.setVisible(False)
        self.review_hint.setText("新条目保存后立即进入待复习队列")
        self._loading = False
        self.mark_clean()
        self.title_edit.setFocus()

    def load(self, entry, note: Note) -> None:
        self._loading = True
        self._mode = MODE_EDIT
        self._entry_id = entry.id

        self.title_edit.setText(entry.title)
        self.link_edit.setText(entry.link)
        self.tag_editor.set_tags(entry.tags)
        _select_data(self.difficulty_combo, entry.difficulty.value)
        _select_data(self.category_combo, entry.error_category.value)
        _select_data(self.status_combo, entry.review_status.value)
        self.wrong_idea_edit.setPlainText(note.wrong_idea)
        self.wrong_code_edit.setPlainText(note.wrong_code)
        self.cause_detail_edit.setPlainText(note.cause_detail)
        self.correct_idea_edit.setPlainText(note.correct_idea)
        self.ac_code_edit.setPlainText(note.ac_code)
        self.summary_edit.setPlainText(note.summary)

        self.review_hint.setText(
            f"间隔 {entry.srs.interval} 天 · 系数 {entry.srs.ease:.2f} · 下次 {entry.srs.next_review}"
        )
        self._clear_error()
        self._set_enabled(True)
        self.placeholder.setVisible(False)
        self._loading = False
        self.mark_clean()

    def _reset_fields(self) -> None:
        self.title_edit.clear()
        self.link_edit.clear()
        self.tag_editor.set_tags([])
        _select_data(self.difficulty_combo, Difficulty.MEDIUM.value)
        _select_data(self.category_combo, ErrorCategory.OTHER.value)
        _select_data(self.status_combo, ReviewStatus.DUE.value)
        for editor in self._text_editors():
            editor.setPlainText("")
        self.review_hint.setText("")
        self._clear_error()

    # -- 取值与校验 ------------------------------------------------------

    def title(self) -> str:
        return self.title_edit.text().strip()

    def validation_error(self) -> str | None:
        """唯一必填字段是题目简述（见文档 2.1.1）。"""
        if not self.title():
            return "题目简述不能为空"
        return None

    def flag_error(self, message: str) -> None:
        self.title_edit.setProperty("error", "true")
        self._repolish(self.title_edit)
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def _clear_error(self) -> None:
        self.title_edit.setProperty("error", "false")
        self._repolish(self.title_edit)

    @staticmethod
    def _repolish(widget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def collect(self) -> dict:
        """收集界面上的值，供 Library 调用。"""
        return {
            "title": self.title(),
            "link": self.link_edit.text().strip(),
            "tags": self.tag_editor.tags(),
            "difficulty": Difficulty(self.difficulty_combo.currentData()),
            "error_category": ErrorCategory(self.category_combo.currentData()),
            "review_status": ReviewStatus(self.status_combo.currentData()),
            "note": self.collect_note(),
        }

    def collect_note(self) -> Note:
        return Note(
            wrong_idea=self.wrong_idea_edit.toPlainText(),
            wrong_code=self.wrong_code_edit.toPlainText(),
            cause_detail=self.cause_detail_edit.toPlainText(),
            correct_idea=self.correct_idea_edit.toPlainText(),
            ac_code=self.ac_code_edit.toPlainText(),
            summary=self.summary_edit.toPlainText(),
        )


def _select_data(combo: QComboBox, value: str) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)
