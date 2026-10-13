"""把代码块放到一个大窗口里查看 / 编辑。

为什么需要它：详情区一屏要放下 6 个文本块，代码框再高也有上限 —— 一段 40 行的 AC 代码
在表单里怎么都看不全。这里给一个接近全屏的等宽编辑器，改完写回原字段。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

import ui.theme as theme
from ui.highlighter import attach as attach_cpp_highlighter


class CodeDialog(QDialog):
    """等宽、不折行、接近全屏的代码编辑器。"""

    def __init__(self, text: str, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{title} — 放大查看")
        self.resize(1000, 760)
        self.setMinimumSize(620, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.editor = QPlainTextEdit(text)
        self.editor.setFont(theme.mono_font(11))
        # 代码不该折行：长行用横向滚动条看，折行反而更难读
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setTabChangesFocus(False)
        attach_cpp_highlighter(self.editor)
        layout.addWidget(self.editor, 1)

        row = QHBoxLayout()
        self.info = QLabel(_line_info(text))
        self.info.setObjectName("hint")
        row.addWidget(self.info)
        row.addStretch(1)

        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)

        confirm = QPushButton("写回")
        confirm.setObjectName("primary")
        confirm.setDefault(True)
        confirm.clicked.connect(self.accept)
        row.addWidget(confirm)
        layout.addLayout(row)

        self.editor.textChanged.connect(
            lambda: self.info.setText(_line_info(self.editor.toPlainText()))
        )

    def text(self) -> str:
        return self.editor.toPlainText()

    @classmethod
    def edit(cls, parent, text: str, title: str) -> str | None:
        """打开对话框；用户确认则返回新文本，取消返回 None。"""
        dialog = cls(text, title, parent)
        if dialog.exec() == QDialog.Accepted:
            return dialog.text()
        return None


def _line_info(text: str) -> str:
    lines = text.splitlines()
    longest = max((len(line) for line in lines), default=0)
    return f"{len(lines)} 行 · 最长 {longest} 列"
