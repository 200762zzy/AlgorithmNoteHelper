"""视觉原则与样式表（见项目文档 3.5）。

本期只实现「干净克制」这一档：中性灰底 + 单一强调色，主操作唯一突出。
多方案探索与截图精修留到 M5，且只修 1–3 个最刺眼的问题。
"""

from __future__ import annotations

from PySide6.QtGui import QFont

# 唯一强调色
ACCENT = "#2f6f4f"
ACCENT_HOVER = "#357a58"
DANGER = "#a8322a"

# 中文字体栈：显式设置，避免默认字体在大字号下发虚
UI_FONT_FAMILIES = [
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Source Han Sans SC",
    "Noto Sans CJK SC",
    "PingFang SC",
    "sans-serif",
]
MONO_FONT_FAMILIES = [
    "Cascadia Mono",
    "Consolas",
    "JetBrains Mono",
    "Courier New",
    "monospace",
]

# 代码高亮的语义配色。刻意低饱和：文档 3.5 的"克制"针对的是界面装饰，而代码语义
# 天生需要几种颜色来区分——所以取低饱和的中性色，避免和界面本身抢注意力。
CODE_COLORS = {
    "comment": {"color": "#8a9199", "italic": True},
    "keyword": {"color": "#0f6b9a", "bold": True},
    "type": {"color": "#7a4fa3"},
    "function": {"color": "#2c6eb5"},
    "number": {"color": "#b0603a"},
    "string": {"color": "#2f7a4f"},
    "preprocessor": {"color": "#8a6a2f"},
}

STYLESHEET = f"""
QWidget {{
    background-color: #f2f3f5;
    color: #23272b;
}}

QMainWindow::separator {{ background: #dcdfe3; width: 1px; height: 1px; }}

QToolBar {{
    background: #ffffff;
    border-bottom: 1px solid #dcdfe3;
    padding: 6px 8px;
    spacing: 4px;
}}
QToolButton {{
    padding: 5px 10px;
    border: 1px solid transparent;
    border-radius: 4px;
    background: transparent;
}}
QToolButton:hover {{ background: #eceef1; }}
QToolButton:pressed {{ background: #e2e5e9; }}
QToolBar QToolButton#primary {{
    background: {ACCENT};
    color: #ffffff;
    font-weight: 600;
    border: 1px solid {ACCENT};
}}
QToolBar QToolButton#primary:hover {{ background: {ACCENT_HOVER}; }}

QPushButton {{
    background: #ffffff;
    border: 1px solid #cfd4da;
    border-radius: 4px;
    padding: 5px 12px;
}}
QPushButton:hover {{ background: #f6f7f9; }}
QPushButton:pressed {{ background: #eceef1; }}
QPushButton:disabled {{ color: #a7aeb5; background: #f5f6f7; }}
QPushButton#primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#danger {{ color: {DANGER}; }}

QLineEdit, QPlainTextEdit, QComboBox, QListWidget {{
    background: #ffffff;
    border: 1px solid #cfd4da;
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: #cfe3d7;
    selection-color: #1c1f22;
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QListWidget:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit[error="true"] {{
    border: 1px solid #c0392b;
    background: #fdf3f2;
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {{
    background: #f5f6f7;
    color: #9aa1a8;
}}

QComboBox::drop-down {{ border: none; width: 18px; }}

QListWidget {{ padding: 0px; }}
QListWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid #eef0f2;
    color: #23272b;
}}
QListWidget::item:selected {{
    background: #e4efe8;
    color: #1c1f22;
}}

/* 标签列表：是「标签输入」的附属显示，不该和旁边的输入框抢视觉重量 */
QListWidget#tagList {{ background: #fbfbfc; }}
QListWidget#tagList::item {{ padding: 2px 6px; border-bottom: none; }}

QGroupBox {{
    background: #ffffff;
    border: 1px solid #dcdfe3;
    border-radius: 6px;
    margin-top: 11px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 5px;
    background-color: #f2f3f5;   /* 与页面底色一致，标题才能"切断"卡片边框 */
    color: #4a5158;
}}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QStatusBar {{ background: #ffffff; border-top: 1px solid #dcdfe3; }}
QStatusBar QLabel {{ background: transparent; }}

QLabel#hint {{ color: #7a828a; }}
QLabel#panelTitle {{ color: #4a5158; font-weight: 600; }}

QSplitter::handle {{ background: #dcdfe3; }}
QSplitter::handle:horizontal {{ width: 1px; }}
"""


def ui_font(point_size: int = 10) -> QFont:
    font = QFont()
    font.setFamilies(UI_FONT_FAMILIES)
    font.setPointSize(point_size)
    return font


def mono_font(point_size: int = 10) -> QFont:
    font = QFont()
    font.setFamilies(MONO_FONT_FAMILIES)
    font.setPointSize(point_size)
    return font


def apply_theme(app) -> None:
    """把字体与样式表应用到 QApplication。"""
    app.setFont(ui_font())
    app.setStyleSheet(STYLESHEET)
