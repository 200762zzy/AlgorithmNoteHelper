"""程序入口：解析数据目录、单实例锁、装配三层（见项目文档 3.1）。

只有本文件与 `ui/` 允许 import Qt；业务层与持久化层保持纯 Python。

命令行：
    python main.py                  正常启动界面
    python main.py --self-check      不启动界面的自检（打包后的 exe 也支持）
    python main.py --self-check-gui  再验证一次 Qt 平台插件与界面层能否加载
    python main.py --version         打印版本
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

import paths
from services import Library
from storage import APP_VERSION
from ui.main_window import MainWindow
from ui.theme import apply_theme


def self_check() -> int:
    """不启动界面的自检。

    打包成 exe 之后 GUI 没法在无人值守的情况下验证，这个开关让分发件能被真正跑一遍
    （解析数据目录 → 打开题库 → 报告一致性）。`--windowed` 的 exe 没有控制台可打印，
    所以结果同时写进数据目录下的 `self-check.log`，同学遇到问题也能直接把它发回来。
    """
    try:
        data_dir = paths.resolve_data_dir()
    except paths.DataDirUnavailable as exc:
        lines = [f"[自检失败] {exc}"]
        _emit(lines, None)
        return 2

    layout = paths.ensure_layout(data_dir)
    library = Library(layout)
    report = library.consistency()

    lines = [
        f"AlgorithmNoteHelper {APP_VERSION}",
        f"运行方式：{'打包后的 exe' if getattr(sys, 'frozen', False) else '源码'}",
        f"Python  ：{sys.version.split()[0]}",
        f"数据目录：{layout.root}",
        f"错题条数：{len(library.entries)}",
        f"待复习  ：{len(library.due_queue())}",
        f"一致性  ：{report.summary()}",
        "自检通过",
    ]
    _emit(lines, layout.root / "self-check.log")
    return 0


def gui_check() -> int:
    """构造一次真实窗口，但**不显示、不进事件循环**。

    `--self-check` 根本不创建 QApplication，所以验证不到打包最容易翻车的一环：
    Qt 平台插件有没有被正确打进去。这里创建 QApplication（这一步就会加载平台插件）
    并装配整个界面层，跑完立刻退出——屏幕上不会闪任何窗口。

    实现约束：**只以只读方式打开真实数据目录，不写任何文件、不建临时目录。**
    早先的实现会用 `mkdtemp` 造一条样例数据，而系统临时目录不可写时 `tempfile`
    会静默回退到当前工作目录，结果在仓库根留下一堆 `anh-guicheck-*` 垃圾目录。
    """
    try:
        data_dir = paths.resolve_data_dir()
    except paths.DataDirUnavailable as exc:
        _emit([f"[界面自检失败] {exc}"], None)
        return 2

    layout = paths.ensure_layout(data_dir)
    log_path = layout.root / "gui-check.log"
    library = Library(layout)
    expected_rows = len(library.entries)

    try:
        app = QApplication.instance() or QApplication(sys.argv)
        apply_theme(app)
    except Exception as exc:  # pragma: no cover - 只在打包缺失插件时触发
        _emit([f"[界面自检失败] 无法初始化 Qt：{exc!r}"], log_path)
        return 3

    try:
        window = MainWindow(library, report_consistency=False)
        window.resize(1200, 800)
        pixmap = window.grab()
        rows = window.panel.list.count()
        if rows != expected_rows:
            raise AssertionError(f"列表应有 {expected_rows} 条，实际 {rows} 条")
        lines = [
            f"AlgorithmNoteHelper {APP_VERSION} 界面自检",
            f"运行方式：{'打包后的 exe' if getattr(sys, 'frozen', False) else '源码'}",
            f"Qt 平台插件：{app.platformName()}",
            f"窗口标题：{window.windowTitle()}",
            f"列表条数：{rows}",
            f"离屏截图：{pixmap.width()}x{pixmap.height()}",
            "界面自检通过",
        ]
        window.close()
    except Exception as exc:
        _emit([f"[界面自检失败] {type(exc).__name__}: {exc}"], log_path)
        return 4

    _emit(lines, log_path)
    return 0


def _emit(lines: list[str], log_path) -> None:
    text = "\n".join(lines)
    try:
        print(text)
    except Exception:  # pragma: no cover - windowed exe 没有 stdout
        pass
    if log_path is None:
        return
    try:
        log_path.write_text(text + "\n", encoding="utf-8")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)

    if "--version" in args:
        _emit([APP_VERSION], None)
        return 0
    if "--self-check" in args:
        return self_check()
    if "--self-check-gui" in args:
        return gui_check()

    app = QApplication(args)
    app.setApplicationName("AlgorithmNoteHelper")
    app.setApplicationDisplayName("AlgorithmNoteHelper 算法错题助手")
    apply_theme(app)

    try:
        data_dir = paths.resolve_data_dir()
    except paths.DataDirUnavailable as exc:
        QMessageBox.critical(None, "无法确定数据目录", str(exc))
        return 2

    layout = paths.ensure_layout(data_dir)

    # 单实例：双击两次 exe 会让两个进程各持一份内存索引，退出时互相覆盖，
    # 造成静默丢数据（见项目文档 2.1.5）。锁必须活到 app.exec() 结束，
    # 所以放在 main() 的局部变量里。
    lock = QLockFile(str(layout.lock))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(200):
        QMessageBox.information(
            None,
            "已经在运行",
            "AlgorithmNoteHelper 已经有一个实例在运行。\n\n"
            "为保护数据，同一时间只允许一个实例；请切换到已经打开的那个窗口。",
        )
        return 0

    window = MainWindow(Library(layout))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
