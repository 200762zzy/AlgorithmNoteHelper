"""C++ 语法高亮的测试。

分词逻辑（`scan_line`）是**纯函数**，所以主要断言都落在它上面，不需要图形环境。
再补两条走真实 `QSyntaxHighlighter` 的检查，确认颜色确实刷到了文档上、
以及跨行块注释的状态确实接续正确。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.highlighter import (  # noqa: E402
    KIND_COMMENT,
    KIND_FUNCTION,
    KIND_KEYWORD,
    KIND_NUMBER,
    KIND_PREPROCESSOR,
    KIND_STRING,
    KIND_TYPE,
    scan_line,
)

pytest.importorskip("PySide6.QtGui", reason="未安装 PySide6")


def pieces(text: str, kind: str, in_block_comment: bool = False) -> list[str]:
    """取出一行里某种片段的原文。"""
    segments, _still = scan_line(text, in_block_comment)
    return [text[start : start + length] for start, length, k in segments if k is kind]


def kinds(text: str, in_block_comment: bool = False) -> set[str]:
    segments, _still = scan_line(text, in_block_comment)
    return {kind for _start, _length, kind in segments}


# --- 纯函数分词 -------------------------------------------------------------


def test_keywords_types_numbers_and_functions_are_all_found():
    text = "int main() { return 1000000007LL; }"
    found = kinds(text)
    for expected in (KIND_KEYWORD, KIND_TYPE, KIND_NUMBER, KIND_FUNCTION):
        assert expected in found, expected
    assert pieces(text, KIND_NUMBER) == ["1000000007LL"]
    assert pieces(text, KIND_FUNCTION) == ["main"]


def test_keyword_before_paren_is_not_mistaken_for_a_function():
    text = "if (n == 0) solve(n);"
    assert "if" not in pieces(text, KIND_FUNCTION)
    assert "if" in pieces(text, KIND_KEYWORD)
    assert pieces(text, KIND_FUNCTION) == ["solve"]


def test_stdlib_name_before_paren_is_not_mistaken_for_a_function():
    """`sort` 已由类型/标准库规则染色，不该再当函数名。"""
    assert pieces("sort(a, a + n);", KIND_FUNCTION) == []
    assert "sort" in pieces("sort(a, a + n);", KIND_TYPE)


def test_slashes_inside_a_string_are_not_a_comment():
    """`"https://x"` 里的 `//` 不是注释 —— 这是逐字符扫描而不是纯正则的原因。"""
    text = 'string url = "https://example.com/a//b";'
    assert KIND_COMMENT not in kinds(text)
    assert pieces(text, KIND_STRING) == ['"https://example.com/a//b"']


def test_quotes_inside_a_comment_are_not_a_string():
    text = 'int x = 1;  // 这里的 " 不是字符串'
    assert KIND_COMMENT in kinds(text)
    assert KIND_STRING not in kinds(text)


def test_escaped_quote_does_not_end_the_string_early():
    text = r'printf("a\"b"); int x;'
    assert pieces(text, KIND_STRING) == [r'"a\"b"']
    assert "int" in pieces(text, KIND_TYPE)


def test_unterminated_block_comment_reports_the_state():
    text = "int x;  /* 从这里开始"
    found, still_in_comment = scan_line(text)
    assert still_in_comment is True
    assert KIND_COMMENT in {kind for _s, _l, kind in found}


def test_continuation_line_of_a_block_comment_is_all_comment():
    segments, still_in_comment = scan_line("还在注释里 int y; */", in_block_comment=True)
    assert still_in_comment is False
    assert {kind for _s, _l, kind in segments} == {KIND_COMMENT}


def test_closed_block_comment_lets_the_rest_of_the_line_be_code():
    text = "/* 说明 */ int x = 3;"
    assert "int" in pieces(text, KIND_TYPE)
    assert pieces(text, KIND_NUMBER) == ["3"]
    assert pieces(text, KIND_COMMENT) == ["/* 说明 */"]


def test_preprocessor_directive_is_highlighted_but_stops_at_the_comment():
    text = "#include <bits/stdc++.h>  // 例程"
    directive = pieces(text, KIND_PREPROCESSOR)
    assert directive == ["#include <bits/stdc++.h>"]
    assert "//" not in directive[0]


def test_unknown_identifiers_are_left_alone():
    """不该把普通变量名也涂上色 —— 高亮要克制。"""
    text = "myCounter = other + 1;"
    assert pieces(text, KIND_TYPE) == []
    assert pieces(text, KIND_KEYWORD) == []
    assert pieces(text, KIND_NUMBER) == ["1"]


# --- 走真实 QSyntaxHighlighter ---------------------------------------------


def test_highlighter_paints_keyword_and_comment_on_the_document(qapp):
    from PySide6.QtGui import QTextDocument

    from ui import theme
    from ui.highlighter import CppHighlighter

    # 文本里必须真的含一个关键词（`int` 是类型、`main` 是函数名、`{` 不是关键词），
    # 否则这条断言会因为没有关键词而失败——那不是高亮的问题。
    document = QTextDocument()
    document.setPlainText("int main() { return 0; }  // 注释")
    highlighter = CppHighlighter(document)
    highlighter.rehighlight()

    colours = {
        item.format.foreground().color().name()
        for item in document.firstBlock().layout().formats()
    }
    assert theme.CODE_COLORS["keyword"]["color"] in colours  # return
    assert theme.CODE_COLORS["comment"]["color"] in colours
    assert theme.CODE_COLORS["type"]["color"] in colours  # int
    assert theme.CODE_COLORS["function"]["color"] in colours  # main


def test_highlighter_carries_block_comment_state_to_the_next_line(qapp):
    from PySide6.QtGui import QTextDocument

    from ui import theme
    from ui.highlighter import CppHighlighter

    document = QTextDocument()
    document.setPlainText("/* 开始\n仍在注释里 int y;\n*/\nint x;")
    highlighter = CppHighlighter(document)
    highlighter.rehighlight()

    comment = theme.CODE_COLORS["comment"]["color"]
    middle = document.findBlockByNumber(1)
    assert {
        item.format.foreground().color().name() for item in middle.layout().formats()
    } == {comment}

    last = document.findBlockByNumber(3)
    assert theme.CODE_COLORS["type"]["color"] in {
        item.format.foreground().color().name() for item in last.layout().formats()
    }
