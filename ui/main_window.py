"""主窗口：顶部工具栏 + 左侧列表/筛选 + 右侧详情 + 状态栏（见项目文档 3.4）。

界面层不做业务判断：所有读写都经 `services.Library`，本模块只负责
「把用户动作翻译成 Library 调用」和「把结果搬回控件」。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from services import Library
from storage import StorageError
from ui.entry_editor import EntryEditor
from ui.entry_list import EntryListPanel
from ui.import_dialog import ImportDialog
from ui.quick_add import QuickAddDialog
from ui.review_dialog import ReviewDialog
from ui.schedule_dialog import ScheduleDialog

QUALITY_LABELS = {1: "忘记", 3: "困难", 5: "轻松"}

LEFT_DEFAULT_WIDTH = 340


class MainWindow(QMainWindow):
    def __init__(self, library: Library, parent=None, report_consistency: bool = True):
        super().__init__(parent)
        self.library = library
        self._refreshing = False
        self._current_id: str | None = None

        self.setMinimumSize(880, 560)
        self.resize(1180, 780)

        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._connect()

        self._update_window_title()
        self._refresh()
        # 启动一致性检查用的是模态对话框；无人值守的自检要把它关掉，否则会挂住
        if report_consistency:
            self._report_consistency()

    # -- 构建 ------------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar("主工具栏")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(bar)

        self.action_new = QAction("新建", self)
        self.action_new.setShortcut(QKeySequence("Ctrl+N"))
        self.action_new.setToolTip("新建一条错题（Ctrl+N）")
        bar.addAction(self.action_new)

        self.action_quick = QAction("剪贴板快速新建", self)
        self.action_quick.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.action_quick.setToolTip("从剪贴板首行建条目，两次按键完成录入（Ctrl+Shift+N）")
        bar.addAction(self.action_quick)

        self.action_save = QAction("保存", self)
        self.action_save.setShortcut(QKeySequence.StandardKey.Save)
        self.action_save.setToolTip("保存当前错题（Ctrl+S）")
        bar.addAction(self.action_save)

        self.action_schedule = QAction("复习计划", self)
        self.action_schedule.setToolTip(
            "按到期日看整个复习循环：未来两周的到期分布 + 分组清单，双击可直接跳过去"
        )
        bar.addAction(self.action_schedule)

        bar.addSeparator()

        self.action_export_md = QAction("导出 md", self)
        self.action_export_md.setToolTip("把当前错题导出为 Markdown 到外部目录，给 Typora / Obsidian 用")
        bar.addAction(self.action_export_md)

        self.action_export_snapshot = QAction("导出快照", self)
        self.action_export_snapshot.setToolTip("导出含全部正文的单文件快照，可直接分享给同学")
        bar.addAction(self.action_export_snapshot)

        self.action_import_snapshot = QAction("导入快照", self)
        self.action_import_snapshot.setToolTip("恢复自己的备份，或导入同学分享的题解包")
        bar.addAction(self.action_import_snapshot)

        bar.addSeparator()

        self.action_delete = QAction("删除", self)
        bar.addAction(self.action_delete)

        self.action_open_data = QAction("打开数据目录", self)
        bar.addAction(self.action_open_data)

        # 主操作唯一突出：工具栏里只有「新建」用强调色
        button = bar.widgetForAction(self.action_new)
        if button is not None:
            button.setObjectName("primary")

    def _build_body(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 6, 10)
        left_layout.setSpacing(0)
        self.panel = EntryListPanel()
        left_layout.addWidget(self.panel)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 10, 10, 10)
        right_layout.setSpacing(0)
        self.editor = EntryEditor()
        right_layout.addWidget(self.editor)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([LEFT_DEFAULT_WIDTH, 840])
        self.splitter = splitter
        self.setCentralWidget(splitter)

    def _build_statusbar(self) -> None:
        self.data_dir_label = QLabel(f"数据目录：{self.library.layout.root}")
        self.data_dir_label.setToolTip("数据目录可能因权限回落到 %APPDATA%，见状态栏提示")
        self.statusBar().addPermanentWidget(self.data_dir_label)

    def _connect(self) -> None:
        self.panel.selection_changed.connect(self._on_selection)
        self.panel.filters_changed.connect(lambda: self._refresh())
        self.editor.dirty_changed.connect(lambda _dirty: self._update_window_title())
        self.editor.review_button.clicked.connect(self._on_review)

        self.action_new.triggered.connect(self._on_new)
        self.action_quick.triggered.connect(self._on_quick_add)
        self.action_save.triggered.connect(lambda: self._save())
        self.action_schedule.triggered.connect(self._on_schedule)
        self.action_export_md.triggered.connect(self._on_export_md)
        self.action_export_snapshot.triggered.connect(self._on_export_snapshot)
        self.action_import_snapshot.triggered.connect(self._on_import_snapshot)
        self.action_delete.triggered.connect(self._on_delete)
        self.action_open_data.triggered.connect(self._on_open_data_dir)

    # -- 刷新 ------------------------------------------------------------

    def _refresh(self, select_id: str | None = None) -> None:
        entries = self.library.search(**self.panel.filters())
        due_ids = {entry.id for entry in self.library.due_queue()}

        self.panel.set_tags(self.library.all_tags())
        self.panel.set_entries(entries, due_ids)
        self.panel.set_due_count(len(due_ids))

        available = {entry.id for entry in entries}
        target = select_id or self._current_id
        self._refreshing = True
        try:
            if target and target in available:
                self.panel.select(target)
            elif entries:
                self.panel.select(entries[0].id)
            else:
                self.panel.clear_selection()
                self._load_entry(None)
        finally:
            self._refreshing = False

    def _load_entry(self, entry_id: str | None) -> None:
        entry = None if entry_id is None else self.library.find(entry_id)
        if entry is None:
            self._current_id = None
            self.editor.clear()
        else:
            self._current_id = entry.id
            self.editor.load(entry, self.library.read_note(entry.id))
        self._update_window_title()

    def _on_selection(self, entry_id: str) -> None:
        if not self._refreshing and not self._guard_dirty():
            self._revert_selection()
            return
        self._load_entry(entry_id or None)

    def _revert_selection(self) -> None:
        """用户放弃切换时，把列表选中项拨回去。"""
        self._refreshing = True
        try:
            if self._current_id:
                self.panel.select(self._current_id)
            else:
                self.panel.clear_selection()
        finally:
            self._refreshing = False

    def _update_window_title(self) -> None:
        base = "AlgorithmNoteHelper 算法错题助手"
        if self.editor.entry_id and not self.editor.is_new():
            entry = self.library.find(self.editor.entry_id)
            if entry is not None:
                marker = " *" if self.editor.is_dirty() else ""
                self.setWindowTitle(f"{entry.title}{marker} — {base}")
                return
        if self.editor.is_new():
            marker = " *" if self.editor.is_dirty() else ""
            self.setWindowTitle(f"新建错题{marker} — {base}")
            return
        self.setWindowTitle(base)

    # -- 未保存保护 ------------------------------------------------------

    def _guard_dirty(self) -> bool:
        """有未保存修改时先问一句。返回 True 表示可以继续。"""
        if not self.editor.is_dirty():
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("有未保存的修改")
        box.setText("当前错题有未保存的修改。")
        box.setInformativeText("要先保存吗？")
        save = box.addButton("保存", QMessageBox.AcceptRole)
        discard = box.addButton("放弃修改", QMessageBox.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(save)
        box.setEscapeButton(cancel)
        box.exec()

        clicked = box.clickedButton()
        if clicked is save:
            return self._save()
        if clicked is discard:
            self.editor.mark_clean()
            return True
        return False

    # -- 动作 ------------------------------------------------------------

    def _save(self) -> bool:
        error = self.editor.validation_error()
        if error:
            self.editor.flag_error(error)
            self._status(error, error=True)
            return False

        data = self.editor.collect()
        note = data.pop("note")
        try:
            if self.editor.is_new():
                entry = self.library.create(
                    data["title"],
                    link=data["link"],
                    tags=data["tags"],
                    difficulty=data["difficulty"],
                    error_category=data["error_category"],
                    note=note,
                )
                message = f"已新建「{entry.title}」，已进入待复习队列"
            else:
                entry = self.library.update(self.editor.entry_id, note=note, **data)
                message = f"已保存「{entry.title}」"
        except (StorageError, ValueError) as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return False

        self._current_id = entry.id
        self.editor.mark_clean()
        self._refresh(select_id=entry.id)
        self._status(message)
        return True

    def _on_new(self) -> None:
        if not self._guard_dirty():
            return
        self._current_id = None
        self.panel.clear_selection()
        self.editor.load_new()
        self._update_window_title()
        self._status("正在新建错题：填好题目简述后按 Ctrl+S 保存")

    def _on_quick_add(self) -> None:
        if not self._guard_dirty():
            return
        text = QApplication.clipboard().text()
        data = QuickAddDialog.run(self, text)
        if not data:
            return
        entry = self.library.create(data["title"], link=data["link"])
        self._current_id = entry.id
        self._refresh(select_id=entry.id)
        self._status(f"已快速新建「{entry.title}」，难度/错因等字段可稍后补")

    def _on_review(self) -> None:
        entry_id = self.editor.entry_id
        if entry_id is None:
            self._status("先选中或保存一条错题，再记录复习", error=True)
            return
        if not self._guard_dirty():
            return
        entry = self.library.get(entry_id)
        quality = ReviewDialog.choose(self, entry)
        if quality is None:
            return
        updated = self.library.review(entry.id, quality)
        self._refresh(select_id=entry.id)
        self._status(
            f"已记录复习（{QUALITY_LABELS[quality]}）：间隔 {updated.srs.interval} 天，"
            f"下次 {updated.srs.next_review}。该条已移出「今天该复习」队列，"
            f"状态仍是「{updated.review_status.zh}」。"
        )

    def _on_delete(self) -> None:
        entry_id = self.editor.entry_id
        if entry_id is None:
            self._status("先选中一条错题再删除", error=True)
            return
        entry = self.library.get(entry_id)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("确认删除")
        box.setText(f"确定删除「{entry.title}」吗？")
        box.setInformativeText(
            f"索引条目与 notes/{entry.id}.md 会被一并删除，不可恢复。\n\n"
            "删除前会自动在 backups/ 存一份快照，但那不是常规备份。"
        )
        confirm = box.addButton("删除", QMessageBox.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() is not confirm:
            return

        self.library.delete(entry.id)
        self._current_id = None
        self._refresh()
        self._status(f"已删除「{entry.title}」")

    def _on_export_md(self) -> None:
        entry_id = self.editor.entry_id
        if entry_id is None:
            self._status("先选中一条错题再导出", error=True)
            return
        if not self._guard_dirty():
            return
        entry = self.library.get(entry_id)
        directory = QFileDialog.getExistingDirectory(self, "选择导出目录", str(Path.home()))
        if not directory:
            return
        target = self.library.export_md(entry.id, Path(directory))
        self._status(f"已导出到 {target}")

    def _on_export_snapshot(self) -> None:
        default_dir = str(self.library.layout.backups)
        directory = QFileDialog.getExistingDirectory(self, "选择快照导出目录", default_dir)
        if not directory:
            return
        target = self.library.export_snapshot(dest_dir=Path(directory))
        self._status(f"已导出快照 {target.name}（含全部正文，可直接分享给同学）")

    def _on_import_snapshot(self) -> None:
        if not self._guard_dirty():
            return
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择快照文件",
            str(self.library.layout.backups),
            "快照 (*.json);;所有文件 (*)",
        )
        if not path:
            return

        try:
            entries, conflicts = self.library.preview_snapshot(Path(path))
        except StorageError as exc:
            QMessageBox.critical(self, "无法读取快照", str(exc))
            return

        if not entries:
            self._status("这份快照里没有条目")
            return

        dialog = ImportDialog(len(entries), len(conflicts), self)
        if dialog.exec() != QDialog.Accepted:
            return

        try:
            result = self.library.import_snapshot(Path(path), conflict=dialog.conflict())
        except (StorageError, ValueError) as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return

        self._current_id = None
        self._refresh()
        self._status(f"导入完成：{result.summary()}")

    def _on_open_data_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.layout.root)))

    def _on_schedule(self) -> None:
        """复习计划：看整个复习循环，双击某条跳过去。"""
        if not self._guard_dirty():
            return
        dialog = ScheduleDialog(self.library, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        chosen = dialog.chosen_entry_id()
        entry = None if chosen is None else self.library.find(chosen)
        if entry is None:
            return
        # 目标可能被当前筛选挡住（比如它下次排在几天后），先复位筛选再选中
        self.panel.clear_filters()
        self._refresh(select_id=entry.id)
        self._status(f"已定位到「{entry.title}」，下次复习 {entry.srs.next_review}")

    # -- 启动自检与收尾 --------------------------------------------------

    def _report_consistency(self) -> None:
        """启动时做索引与 notes/ 的一致性检查，只报告、不自动清理（见文档 6）。"""
        report = self.library.consistency()
        if report.is_clean:
            return

        lines: list[str] = []
        if report.missing_notes:
            lines.append(f"索引里有、磁盘上没有的正文：{len(report.missing_notes)} 条")
            lines += [f"    {item}" for item in report.missing_notes[:5]]
            if len(report.missing_notes) > 5:
                lines.append("    …")
        if report.orphan_notes:
            lines.append(f"磁盘上有、索引里没有的 md：{len(report.orphan_notes)} 个")
            lines += [f"    {item}" for item in report.orphan_notes[:5]]
            if len(report.orphan_notes) > 5:
                lines.append("    …")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("数据一致性检查")
        box.setText("索引与 notes/ 目录不一致。程序只报告，不会自动删除任何文件。")
        box.setInformativeText("\n".join(lines))
        box.exec()
        self._status(report.summary(), error=True)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._guard_dirty():
            event.accept()
        else:
            event.ignore()

    def _status(self, message: str, error: bool = False) -> None:
        self.statusBar().showMessage(("注意：" if error else "") + message, 6000)
