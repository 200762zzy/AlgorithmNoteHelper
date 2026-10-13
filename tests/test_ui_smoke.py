"""界面接线冒烟测试。

项目文档 5.3 明确不做 PySide6 的自动化 UI 测试（成本高、收益低）。这里只做
**最低限度的接线验证**：窗口能构造、动作能触发、字段能载入、空标题能被拦住。
真正的交互与视觉仍靠 5.1 的手工用例与 3.5 的截图自查覆盖。

没有安装 PySide6 时整个文件跳过。
"""

from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets", reason="未安装 PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from models import Difficulty, Note, StatusFilter  # noqa: E402
from services import Library  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.quick_add import derive_title, interpret_clipboard  # noqa: E402
from ui.review_dialog import QUALITY_CHOICES  # noqa: E402

DAY = date(2026, 10, 13)


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def window(qapp, layout, day):
    library = Library(layout, today_fn=lambda: day)
    library.create(
        "P1001 前缀和与差分",
        tags=["前缀和", "差分"],
        difficulty=Difficulty.HARD,
        note=Note(summary="多开一位"),
    )
    library.create("第二条")
    win = MainWindow(library)
    yield win
    # 收尾时先清掉脏标记，否则 closeEvent 会弹「未保存」对话框把测试挂住
    win.editor.mark_clean()
    win.close()


# --- 装配 -------------------------------------------------------------------


def test_window_loads_the_first_entry(window):
    assert window.editor.entry_id == window.library.entries[0].id
    assert window.editor.title_edit.text() == "P1001 前缀和与差分"
    assert window.editor.tag_editor.tags() == ["前缀和", "差分"]
    assert window.editor.summary_edit.toPlainText() == "多开一位"


def test_toolbar_reports_due_count(window):
    # 两条新建的错题当天就都在待复习队列里
    assert window.panel.due_button.text() == "待复习 (2)"
    assert window.panel.count_label.text() == "共 2 条"


def test_selecting_an_entry_loads_its_note(window, layout):
    second = window.library.entries[1]
    window.panel.select(second.id)
    assert window.editor.entry_id == second.id
    assert window.editor.title_edit.text() == "第二条"


# --- 新建与校验 -------------------------------------------------------------


def test_new_creates_a_draft_without_touching_the_index(window):
    before = len(window.library.entries)
    window.action_new.trigger()

    assert window.editor.is_new()
    assert window.editor.entry_id is None
    assert len(window.library.entries) == before  # 草稿不落盘
    assert window.editor.difficulty_combo.currentData() == Difficulty.MEDIUM.value


def test_save_refuses_an_empty_title(window):
    window.action_new.trigger()
    assert window.editor.validation_error() == "题目简述不能为空"

    assert window._save() is False
    assert len(window.library.entries) == 2
    assert window.editor.title_edit.property("error") == "true"


def test_save_on_a_new_draft_persists_it(window):
    window.action_new.trigger()
    window.editor.title_edit.setText("刚录的一条")
    assert window._save() is True

    assert not window.editor.is_new()
    assert window.editor.entry_id is not None
    assert window.library.get(window.editor.entry_id).title == "刚录的一条"
    assert window.editor.is_dirty() is False


def test_editing_marks_dirty_and_saving_clears_it(window):
    assert window.editor.is_dirty() is False
    window.editor.summary_edit.setPlainText("改动")
    assert window.editor.is_dirty() is True

    assert window._save() is True
    assert window.editor.is_dirty() is False
    assert window.library.read_note(window.editor.entry_id).summary == "改动"


# --- 筛选 -------------------------------------------------------------------


def test_filters_translate_to_library_keyword_arguments(window):
    panel = window.panel
    panel.keyword.setText("差分")
    panel.difficulty.setCurrentIndex(panel.difficulty.findData(Difficulty.HARD.value))

    filters = panel.filters()
    assert filters["keyword"] == "差分"
    assert filters["difficulty"] is Difficulty.HARD
    assert filters["status"] is None

    assert [e.title for e in window.library.search(**filters)] == ["P1001 前缀和与差分"]


def test_due_button_switches_to_the_due_filter(window):
    window.panel.due_button.click()
    assert window.panel.filters()["status"] is StatusFilter.DUE


# --- 对话框的纯逻辑 ---------------------------------------------------------


def test_review_choices_are_the_three_documented_tiers():
    assert [quality for quality, _label, _desc in QUALITY_CHOICES] == [1, 3, 5]


def test_clipboard_url_becomes_link_with_derived_title():
    title, link = interpret_clipboard("https://oj.example.com/p/1001")
    assert link == "https://oj.example.com/p/1001"
    assert title == "1001"


def test_clipboard_plain_text_becomes_the_title():
    assert interpret_clipboard("P1001 前缀和与差分") == ("P1001 前缀和与差分", "")


def test_clipboard_empty_input_is_safe():
    assert interpret_clipboard("") == ("", "")
    assert interpret_clipboard("   \n  \n") == ("", "")


def test_derived_title_falls_back_when_the_url_has_no_path():
    assert derive_title("https://oj.example.com") == "待补标题"
    assert derive_title("https://oj.example.com/") == "待补标题"


def test_derived_title_uses_the_last_path_segment():
    assert derive_title("https://oj.example.com/p/1001") == "1001"
    assert derive_title("https://www.luogu.com.cn/problem/P1001") == "P1001"
    assert derive_title("https://oj.example.com/problems/1001.html") == "1001"
    # 末段可能很短（/p/ 只能给出 "p"），快速新建对话框里可以直接改掉
    assert derive_title("https://oj.example.com/p/") == "p"


# --- 入口 -------------------------------------------------------------------


def test_entry_point_module_is_importable():
    """入口本身没有别的测试覆盖，这里至少保证它可以被导入、动作没打错字。"""
    import main

    assert callable(main.main)
