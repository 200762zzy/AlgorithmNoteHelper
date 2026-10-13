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

from PySide6.QtCore import Qt  # noqa: E402

from models import Difficulty, Note, StatusFilter  # noqa: E402
from services import Library  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.quick_add import derive_title, interpret_clipboard  # noqa: E402
from ui.review_dialog import QUALITY_CHOICES  # noqa: E402

DAY = date(2026, 10, 13)


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
    # 两条新建的错题当天就都在「今天该复习」队列里
    assert window.panel.due_button.text() == "今天该复习 (2)"
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


def test_due_button_selects_the_due_today_filter(window):
    window.panel.due_button.click()
    assert window.panel.filters()["status"] is StatusFilter.DUE_TODAY


def test_reviewed_entry_stays_visible_under_the_due_status_filter(window):
    """回归（界面上报的真实缺陷）：复习完的条目不能从列表里"消失"。

    曾经「待复习」筛选是队列语义，刚复习完的条目于是在每个筛选口径下都不显示，
    用户以为记录丢了。
    """
    entry = window.library.entries[0]
    window.library.review(entry.id, 3)  # 困难 → 下次排到明天

    def rows(status):
        window.panel.status.setCurrentIndex(window.panel.status.findData(status))
        return window.panel.list.count()

    assert rows(StatusFilter.ALL.value) == 2
    assert rows(StatusFilter.DUE.value) == 2  # 状态口径：两条都还在复习轮次里
    assert rows(StatusFilter.DUE_TODAY.value) == 1  # 队列口径：只剩今天到期的那条


def test_list_second_line_shows_when_the_entry_comes_back(window):
    """列表第二行要把排期写出来，否则用户看不出条目"去哪了"。"""
    entry = window.library.entries[0]
    window.library.review(entry.id, 3)
    other = window.library.entries[1]
    window._refresh()  # 直接改库之后必须刷新，真实路径上 _on_review 会做这件事

    soon = entry.srs.next_review
    assert f"待复习 · {soon.month}-{soon.day}" in _second_line(window, entry.id)
    assert "待复习 · 今天" in _second_line(window, other.id)


def _second_line(window, entry_id):
    for row in range(window.panel.list.count()):
        item = window.panel.list.item(row)
        if item.data(Qt.UserRole) == entry_id:
            return item.text()
    raise AssertionError(f"列表里找不到 {entry_id}")


# --- 复习计划视图 -----------------------------------------------------------


def test_schedule_dialog_groups_the_review_cycle(window, day):
    """复习计划要按到期日分组，并把今天／明天标出来。"""
    from ui.schedule_dialog import ScheduleDialog

    entry = window.library.entries[0]
    window.library.review(entry.id, 3)  # 排到明天

    dialog = ScheduleDialog(window.library, day=day, parent=window)
    labels = [
        dialog.tree.topLevelItem(index).text(0)
        for index in range(dialog.tree.topLevelItemCount())
    ]
    assert any("今天" in label for label in labels)
    assert any("明天" in label for label in labels)

    bars = dialog.chart.bars()
    assert bars[0][0] == "逾期"
    assert bars[1][0] == "今天" and bars[1][1] == 1
    assert bars[2][0] == "明天" and bars[2][1] == 1
    assert dialog.chosen_entry_id() is None
    dialog.close()


def test_schedule_dialog_double_click_returns_the_entry(window, day):
    from ui.schedule_dialog import ScheduleDialog

    entry = window.library.entries[0]
    dialog = ScheduleDialog(window.library, day=day, parent=window)

    bucket = dialog.tree.topLevelItem(0)
    child = bucket.child(0)
    dialog._on_activated(child, 0)  # 模拟双击

    assert dialog.chosen_entry_id() == entry.id
    dialog.close()


def test_code_boxes_get_enough_room_and_can_be_zoomed(window):
    """代码框必须够高、能随窗口伸展、且不被折行；并配有「放大」按钮。

    上一版把所有文本框设成定高 140px，40 行的 AC 代码只能看到 7 行。
    """
    from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QSizePolicy

    editor = window.editor.ac_code_edit
    assert editor.minimumHeight() >= 180
    assert editor.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert editor.lineWrapMode() == QPlainTextEdit.NoWrap
    assert window.editor.wrong_code_edit.minimumHeight() >= 180

    # 两个代码框各配一个「放大」按钮
    buttons = [button.text() for button in window.findChildren(QPushButton)]
    assert buttons.count("放大") == 2


def test_code_editors_and_the_zoom_dialog_carry_the_cpp_highlighter(window):
    """高亮必须真的挂上去 —— 只 import 了模块但没 attach 是最容易犯的错。"""
    from ui.code_dialog import CodeDialog

    assert window.editor.ac_code_edit.cpp_highlighter is not None
    assert window.editor.wrong_code_edit.cpp_highlighter is not None

    dialog = CodeDialog("int main() { return 0; }", "AC 代码（C++）")
    assert dialog.editor.cpp_highlighter is not None
    dialog.close()


def test_code_dialog_returns_edited_text(qapp):
    from ui.code_dialog import CodeDialog

    dialog = CodeDialog("int main() {}", "AC 代码（C++）")
    assert dialog.text() == "int main() {}"
    assert "放大查看" in dialog.windowTitle()

    dialog.editor.setPlainText("// 改过了\nreturn 0;")
    assert dialog.text() == "// 改过了\nreturn 0;"
    assert "2 行" in dialog.info.text()
    dialog.close()


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


def test_single_instance_lock_refuses_a_second_holder(layout):
    """单实例锁是防丢数据的（双开退出时会互相覆盖索引），所以验证真实行为。

    QLockFile 会记录持有者的 pid/host，并依据 `staleLockTime` 判断锁是否还有效，
    因此同一进程内第二次 tryLock 也必须失败。
    """
    from PySide6.QtCore import QLockFile

    first = QLockFile(str(layout.lock))
    first.setStaleLockTime(30_000)
    assert first.tryLock(200) is True

    second = QLockFile(str(layout.lock))
    second.setStaleLockTime(30_000)
    assert second.tryLock(200) is False

    first.unlock()
    assert second.tryLock(200) is True
    second.unlock()


def test_self_check_runs_without_opening_the_window(monkeypatch, tmp_path, capsys):
    """`--self-check` 是验证打包后分发件的唯一非交互手段。

    顺带守住一条测试纪律：这里用 ANH_DATA_DIR 把数据目录指到临时目录，
    测试**绝不能**碰真实的数据目录。
    """
    import main

    monkeypatch.setenv("ANH_DATA_DIR", str(tmp_path / "data"))
    assert main.main(["--self-check"]) == 0

    out = capsys.readouterr().out
    assert "自检通过" in out
    assert "错题条数：0" in out

    # windowed 的 exe 没有控制台，结果必须同时落盘
    log = tmp_path / "data" / "self-check.log"
    assert log.exists()
    assert "自检通过" in log.read_text(encoding="utf-8")


def test_version_flag(capsys):
    import main
    from storage import APP_VERSION

    assert main.main(["--version"]) == 0
    assert APP_VERSION in capsys.readouterr().out


def test_gui_self_check_constructs_the_window(monkeypatch, tmp_path, qapp):
    """界面自检要能证明「Qt 平台插件 + 整个界面层」在打包环境下也能加载。

    这是 `--self-check` 覆盖不到的部分（它不创建 QApplication），
    也是 PyInstaller 最常出问题的地方。它还必须是**只读**的：不能写数据、
    也不能建临时目录（`tempfile` 在系统临时目录不可写时会回退到当前工作目录，
    从而到处留垃圾目录）。
    """
    import main
    import paths
    from services import Library

    data_dir = tmp_path / "data"
    monkeypatch.setenv("ANH_DATA_DIR", str(data_dir))
    Library(paths.ensure_layout(data_dir), today_fn=lambda: DAY).create("自检样例")

    before = sorted(p.name for p in data_dir.iterdir())
    assert main.main(["--self-check-gui"]) == 0

    log = data_dir / "gui-check.log"
    assert log.exists()
    text = log.read_text(encoding="utf-8")
    assert "界面自检通过" in text
    assert "列表条数：1" in text

    # 只读：除了自检日志之外不应该多出任何东西（更不应该出现临时目录）
    after = sorted(p.name for p in data_dir.iterdir() if p.name != "gui-check.log")
    assert after == before
    assert not list(tmp_path.glob("anh-guicheck-*"))
