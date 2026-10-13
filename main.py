"""程序入口：解析数据目录、单实例锁、装配三层（见项目文档 3.1）。

只有本文件与 `ui/` 允许 import Qt；业务层与持久化层保持纯 Python。
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

import paths
from services import Library
from ui.main_window import MainWindow
from ui.theme import apply_theme


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
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
