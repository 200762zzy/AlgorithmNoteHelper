"""剪贴板快速新建：把「录一条错题」压到两次按键 + 一次回车（见文档 2.1.1）。

从剪贴板首行推断标题与链接：
- 首行是 URL → 填入「题目链接」，标题从 URL 末段派生（标题是唯一必填字段，
  不能让快速通道绕开校验；派生出的标题可当场改掉）；
- 否则 → 作为标题，链接留空。

**范围说明：** 文档写的是「全局唤起」。本期只做应用内快捷键
（Ctrl+Shift+N）与工具栏按钮，真正的系统级全局热键需要
`RegisterHotKey` 之类的平台调用，列入 V0.2。
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

FALLBACK_TITLE = "待补标题"


def interpret_clipboard(text: str) -> tuple[str, str]:
    """把剪贴板文本解析成 (标题, 链接)。"""
    first_line = ""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            first_line = stripped
            break
    if not first_line:
        return "", ""
    if first_line.lower().startswith(("http://", "https://")):
        return derive_title(first_line), first_line
    return first_line, ""


def derive_title(url: str) -> str:
    """从 URL 末段派生一个可用的临时标题。"""
    try:
        path = urlparse(url).path
    except ValueError:
        return FALLBACK_TITLE
    for segment in reversed([part for part in path.split("/") if part]):
        cleaned = unquote(segment).rsplit(".", 1)[0].strip()
        if cleaned:
            return cleaned
    return FALLBACK_TITLE


class QuickAddDialog(QDialog):
    """一个只有标题与链接的小对话框，回车即保存。"""

    def __init__(self, clipboard_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("剪贴板快速新建")
        self.setModal(True)
        self.setMinimumWidth(460)

        title, link = interpret_clipboard(clipboard_text)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        hint = QLabel(
            "已从剪贴板取内容。只有题目简述是必填，其余字段保存后再补。"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(8)
        self.title_edit = QLineEdit(title)
        self.title_edit.setPlaceholderText("题目简述（必填）")
        self.link_edit = QLineEdit(link)
        self.link_edit.setPlaceholderText("题目链接（可空）")
        form.addRow("题目简述", self.title_edit)
        form.addRow("题目链接", self.link_edit)
        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        save = QPushButton("保存并继续刷题")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self._on_accept)
        row.addWidget(save)
        layout.addLayout(row)

        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def _on_accept(self) -> None:
        if not self.title_edit.text().strip():
            self.error_label.setText("题目简述不能为空")
            self.error_label.setVisible(True)
            self.title_edit.setProperty("error", "true")
            self._repolish(self.title_edit)
            self.title_edit.setFocus()
            return
        self.accept()

    @staticmethod
    def _repolish(widget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def result_data(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "link": self.link_edit.text().strip(),
        }

    @classmethod
    def run(cls, parent, clipboard_text: str) -> dict | None:
        dialog = cls(clipboard_text, parent)
        if dialog.exec() == QDialog.Accepted:
            return dialog.result_data()
        return None
