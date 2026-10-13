"""C++ 简单语法高亮（`QSyntaxHighlighter`）。

范围（见项目文档 2.2）：**只做高亮**，不做编辑增强 —— 行号、括号匹配、自动缩进、
代码折叠都不在此列。

实现上刻意分成两层：

- `scan_line()` 是**不依赖 Qt 的纯函数**，把一行切成 `(起点, 长度, 种类)` 片段。
  这样它可以被直接单测，不需要图形环境；
- `CppHighlighter` 只负责把片段刷成颜色。

分词用逐字符扫描而不是一堆正则堆叠，是为了处理两类真实代码里一定会遇到的情况：
字符串里的 `//`（`"https://x"` 不是注释）与跨行的 `/* ... */`。
"""

from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

import ui.theme as theme

KIND_KEYWORD = "keyword"
KIND_TYPE = "type"
KIND_FUNCTION = "function"
KIND_NUMBER = "number"
KIND_STRING = "string"
KIND_COMMENT = "comment"
KIND_PREPROCESSOR = "preprocessor"

# 同一位置被多个规则命中时，后应用的赢。这个顺序保证注释 > 字符串 > 预处理 > 代码。
_PRIORITY = {
    KIND_KEYWORD: 0,
    KIND_TYPE: 1,
    KIND_NUMBER: 2,
    KIND_FUNCTION: 3,
    KIND_PREPROCESSOR: 4,
    KIND_STRING: 5,
    KIND_COMMENT: 6,
}

_STATE_NORMAL = 0
_STATE_BLOCK_COMMENT = 1

KEYWORDS = frozenset(
    """
    alignas alignof and asm auto break case catch class const constexpr continue
    decltype default delete do dynamic_cast else enum explicit export extern false
    for friend goto if inline mutable namespace new noexcept nullptr operator
    private protected public register reinterpret_cast return sizeof static
    static_assert static_cast struct switch template this throw true try typedef
    typeid typename union using virtual volatile while
    """.split()
)

# 类型名与刷题时最常出现的标准库名字。放在一类里，共用一个颜色。
TYPE_NAMES = frozenset(
    """
    bool char char16_t char32_t double float int long short signed unsigned void
    wchar_t size_t
    array bitset deque map pair priority_queue queue set stack string tuple
    unordered_map unordered_set vector
    abs begin ceil cin cerr clear cout empty end endl floor front back log log2
    lower_bound max memcpy memset min pop pop_back pow printf push push_back
    emplace_back round scanf size sort sqrt stable_sort swap unique upper_bound
    INT_MAX INT_MIN LLONG_MAX LLONG_MIN UINT_MAX
    """.split()
)

_IDENT = r"[A-Za-z_]\w*"
_NUMBER_RE = re.compile(
    r"\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)[uUlLfF]*"
)
_KEYWORD_RE = re.compile(rf"\b(?:{'|'.join(sorted(KEYWORDS, key=len, reverse=True))})\b")
_TYPE_RE = re.compile(rf"\b(?:{'|'.join(sorted(TYPE_NAMES, key=len, reverse=True))})\b")
_FUNCTION_RE = re.compile(rf"\b{_IDENT}(?=\s*\()")
_PREPROCESSOR_RE = re.compile(r"^\s*#\s*\w+")


def scan_line(
    text: str, in_block_comment: bool = False
) -> tuple[list[tuple[int, int, str]], bool]:
    """把一行 C++ 切成 `(起点, 长度, 种类)` 片段。

    返回 `(片段列表, 行尾是否仍在未闭合的块注释里)`。片段已按应用顺序排好：
    后应用的优先级更高，因此注释、字符串能覆盖掉落在它们内部的代码高亮。
    """
    segments: list[tuple[int, int, str]] = []
    protected: list[tuple[int, int]] = []  # 字符串 / 注释占据的区间，代码规则不得侵入

    def emit(start: int, end: int, kind: str) -> None:
        if end > start:
            segments.append((start, end - start, kind))

    length = len(text)
    index = 0
    unterminated_comment = False

    if in_block_comment:
        end = text.find("*/")
        if end == -1:
            emit(0, length, KIND_COMMENT)
            return segments, True
        emit(0, end + 2, KIND_COMMENT)
        protected.append((0, end + 2))
        index = end + 2

    while index < length:
        char = text[index]
        if char == "/" and text.startswith("//", index):
            emit(index, length, KIND_COMMENT)
            protected.append((index, length))
            index = length
            break
        if char == "/" and text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end == -1:
                emit(index, length, KIND_COMMENT)
                protected.append((index, length))
                unterminated_comment = True
                index = length
                break
            emit(index, end + 2, KIND_COMMENT)
            protected.append((index, end + 2))
            index = end + 2
            continue
        if char in ("'", '"'):
            end = _string_end(text, index)
            emit(index, end, KIND_STRING)
            protected.append((index, end))
            index = end
            continue
        index += 1

    _add_code_segments(text, segments, protected)
    segments.sort(key=lambda item: (_PRIORITY[item[2]], item[0]))
    return segments, unterminated_comment


def _string_end(text: str, start: int) -> int:
    """字符串 / 字符字面量的结束位置（含引号）。未闭合则到行尾。"""
    quote = text[start]
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == quote:
            return index + 1
        index += 1
    return len(text)


def _overlaps(start: int, end: int, protected: list[tuple[int, int]]) -> bool:
    return any(start < block_end and block_start < end for block_start, block_end in protected)


def _add_code_segments(
    text: str, segments: list[tuple[int, int, str]], protected: list[tuple[int, int]]
) -> None:
    for regex, kind in (
        (_KEYWORD_RE, KIND_KEYWORD),
        (_TYPE_RE, KIND_TYPE),
        (_NUMBER_RE, KIND_NUMBER),
        (_FUNCTION_RE, KIND_FUNCTION),
    ):
        for match in regex.finditer(text):
            start, end = match.span()
            if _overlaps(start, end, protected):
                continue
            if kind is KIND_FUNCTION and match.group(0) in KEYWORDS | TYPE_NAMES:
                # `if (`、`sort(` 这类已由关键词/类型规则处理过
                continue
            segments.append((start, end - start, kind))

    directive = _PREPROCESSOR_RE.match(text)
    if directive is None:
        return
    # 预处理指令涂到行尾，但遇到行尾注释就截断，并去掉尾部空白（否则会把
    # 注释前那几个空格也涂上色，看起来像多出一截）
    end = len(text)
    for block_start, _block_end in protected:
        if directive.start() < block_start < end:
            end = block_start
    while end > directive.end() and text[end - 1] in " \t":
        end -= 1
    if end > directive.end():
        segments.append((directive.start(), end - directive.start(), KIND_PREPROCESSOR))


def _make_format(spec: dict) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(spec["color"]))
    if spec.get("bold"):
        fmt.setFontWeight(QFont.Weight.Bold)
    if spec.get("italic"):
        fmt.setFontItalic(True)
    return fmt


class CppHighlighter(QSyntaxHighlighter):
    """把 `scan_line()` 的结果刷到文档上。"""

    def __init__(self, document):
        super().__init__(document)
        self._formats = {
            kind: _make_format(spec) for kind, spec in theme.CODE_COLORS.items()
        }

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt 命名
        in_comment = self.previousBlockState() == _STATE_BLOCK_COMMENT
        segments, still_in_comment = scan_line(text, in_comment)
        for start, length, kind in segments:
            fmt = self._formats.get(kind)
            if fmt is not None:
                self.setFormat(start, length, fmt)
        self.setCurrentBlockState(
            _STATE_BLOCK_COMMENT if still_in_comment else _STATE_NORMAL
        )


def attach(editor) -> CppHighlighter:
    """给一个 `QPlainTextEdit` 挂上 C++ 高亮。

    高亮器必须保持 Python 侧引用，否则可能在回收后静默失效 —— 所以挂到控件属性上。
    """
    highlighter = CppHighlighter(editor.document())
    editor.cpp_highlighter = highlighter
    return highlighter
