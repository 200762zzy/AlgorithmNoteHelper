"""导入快照前的预览与冲突策略选择（见项目文档 2.1.4）。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from services import CONFLICT_COPY, CONFLICT_OVERWRITE, CONFLICT_SKIP

_CONFLICT_CHOICES = (
    (CONFLICT_SKIP, "跳过（保留我的记录）"),
    (CONFLICT_OVERWRITE, "覆盖（改用快照里的版本）"),
    (CONFLICT_COPY, "收为副本（两条都留下，重新生成 id）"),
)


class ImportDialog(QDialog):
    """展示「新增多少、冲突多少」，并让用户选冲突怎么处理。"""

    def __init__(self, total: int, conflicts: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入快照")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        summary = QLabel(f"这份快照含 **{total}** 条，其中 **{conflicts}** 条与本地重复。".replace("**", ""))
        summary.setWordWrap(True)
        layout.addWidget(summary)

        if conflicts:
            hint = QLabel(
                "重复的条目按下面的方式处理。「收为副本」适合把同学的题解收进来时"
                "两边都保留，「覆盖」会丢掉你本地的版本。"
            )
        else:
            hint = QLabel("没有重复条目，可以放心导入。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.conflict_combo = QComboBox()
        for value, label in _CONFLICT_CHOICES:
            self.conflict_combo.addItem(label, value)
        self.conflict_combo.setEnabled(bool(conflicts))
        layout.addWidget(self.conflict_combo)

        note = QLabel("导入前会自动把当前数据存一份快照到 backups/。")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        confirm = QPushButton("导入")
        confirm.setObjectName("primary")
        confirm.setDefault(True)
        confirm.clicked.connect(self.accept)
        row.addWidget(confirm)
        layout.addLayout(row)

    def conflict(self) -> str:
        return self.conflict_combo.currentData()
