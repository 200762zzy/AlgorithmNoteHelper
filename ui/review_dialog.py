"""「完成复习」对话框：三档评分（忘记 / 困难 / 轻松）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

# 三档评分到 SM-2 quality 的映射（见项目文档 2.1.3）
QUALITY_CHOICES = (
    (1, "忘记", "完全想不起来"),
    (3, "困难", "想起来了但很吃力"),
    (5, "轻松", "秒杀"),
)


class ReviewDialog(QDialog):
    """选择本次复习的档位。三个选项等权，不设强调色（强调只留给主操作）。"""

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self.setWindowTitle("完成复习")
        self.setModal(True)
        self._quality: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel(f"「{entry.title}」")
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        state = QLabel(
            f"当前：间隔 {entry.srs.interval} 天 · 难度系数 {entry.srs.ease:.2f} · "
            f"已复习 {entry.srs.repetitions} 次 · 下次到期 {entry.srs.next_review}"
        )
        state.setObjectName("hint")
        state.setWordWrap(True)
        layout.addWidget(state)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #e3e6e9;")
        layout.addWidget(line)

        hint = QLabel("这次想起来了吗？")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._buttons: dict[int, QPushButton] = {}
        for quality, label, description in QUALITY_CHOICES:
            button = QPushButton(f"{label}\n{description}")
            button.setToolTip(description)
            button.setMinimumHeight(56)
            button.clicked.connect(lambda _=False, q=quality: self._choose(q))
            buttons.addWidget(button)
            self._buttons[quality] = button
        layout.addLayout(buttons)

        cancel_row = QHBoxLayout()
        cancel_row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        cancel_row.addWidget(cancel)
        layout.addLayout(cancel_row)

        # 三档分别对应数字键 1/2/3，键盘操作更快
        for index, quality in enumerate((1, 3, 5), start=1):
            button = self._buttons[quality]
            button.setShortcut(Qt.Key_1 + index - 1)

    def _choose(self, quality: int) -> None:
        self._quality = quality
        self.accept()

    @property
    def quality(self) -> int | None:
        return self._quality

    @classmethod
    def choose(cls, parent, entry) -> int | None:
        """返回所选 quality；用户取消时返回 None。"""
        dialog = cls(entry, parent)
        if dialog.exec() == QDialog.Accepted:
            return dialog.quality
        return None
