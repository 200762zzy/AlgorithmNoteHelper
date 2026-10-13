"""业务逻辑层测试：CRUD、筛选、待复习队列、导出、一致性。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import storage
from models import Difficulty, ErrorCategory, Note, ReviewStatus, StatusFilter
from services import Library, NotFoundError, ValidationError

DAY = date(2026, 10, 13)


# --- 新建（文档用例 9） -----------------------------------------------------


def test_create_requires_title(library):
    with pytest.raises(ValidationError):
        library.create("   ")


def test_create_applies_documented_defaults(library):
    """只有标题必填；难度与错因取默认值，允许后补（文档 2.1.1）。"""
    entry = library.create("二分答案")
    assert entry.difficulty is Difficulty.MEDIUM
    assert entry.error_category is ErrorCategory.OTHER
    assert entry.review_status is ReviewStatus.DUE
    assert library.read_note(entry.id) == Note()


def test_create_strips_and_deduplicates_tags(library):
    entry = library.create("标签", tags=[" DP ", "dp", "", "枚举", "枚举"])
    assert entry.tags == ["DP", "枚举"]


def test_create_rejects_bad_enum(library):
    with pytest.raises(ValueError):
        library.create("难度非法", difficulty="impossible")


# --- 待复习队列（文档用例 2：2.1.3 漏洞的回归测试） ------------------------


def test_new_entry_is_immediately_in_the_due_queue(library):
    """新建即 due 且 next_review = 今天，所以当天就该出现在队列里。

    原设计有第三态 todo，导致「新建后再没打开过的错题永远不进队列」。
    """
    entry = library.create("新建就该复习")
    assert entry.srs.next_review == DAY
    assert [item.id for item in library.due_queue()] == [entry.id]


def test_review_takes_entry_out_of_the_queue_until_next_review(library):
    entry = library.create("复习一次")
    library.review(entry.id, 3)

    assert library.due_queue() == []
    assert [item.id for item in library.due_queue(DAY + timedelta(days=1))] == [entry.id]


def test_due_queue_is_sorted_by_next_review(library):
    later = library.create("晚一点")
    library.review(later.id, 5)  # next_review = 明天
    soon = library.create("今天就到期")

    assert [item.id for item in library.due_queue()] == [soon.id]
    assert [item.id for item in library.due_queue(DAY + timedelta(days=1))] == [
        soon.id,
        later.id,
    ]


def test_mastered_is_not_terminal(library):
    """文档用例 22：mastered 也要在逾期宽限期后回到队列，否则长间隔段被截断。"""
    entry = library.create("长间隔")
    for _ in range(4):
        library.review(entry.id, 5)
    assert entry.review_status is ReviewStatus.MASTERED

    due_day = entry.srs.next_review
    assert library.due_queue(due_day) == []  # 刚到期的当天在宽限期内，不打扰
    assert [item.id for item in library.due_queue(due_day + timedelta(days=7))] == [
        entry.id
    ]


def test_cross_day_boundary(library, day):
    """文档用例 17。"""
    entry = library.create("跨天")
    assert library.in_review_queue(entry, day)
    assert library.in_review_queue(entry, day + timedelta(days=1))  # 一直没复习

    library.review(entry.id, 3, day)
    assert not library.in_review_queue(entry, day)
    assert library.in_review_queue(entry, day + timedelta(days=1))


# --- 检索与筛选（文档用例 3、4、5、6） --------------------------------------


def test_search_by_keyword_covers_title_tag_and_chinese_label(library):
    a = library.create("前缀和与差分", tags=["DP"], error_category=ErrorCategory.BOUNDARY)
    library.create("二分答案", tags=["二分"])

    assert {e.id for e in library.search(keyword="前缀")} == {a.id}
    assert {e.id for e in library.search(keyword="dp")} == {a.id}  # 大小写不敏感
    assert {e.id for e in library.search(keyword="边界")} == {a.id}  # 中文错因分类
    assert library.search(keyword="完全不存在的关键词") == []


def test_filter_by_tags_requires_all_of_them(library):
    both = library.create("两条标签", tags=["枚举", "DP"])
    library.create("只有一条", tags=["枚举"])

    assert {e.id for e in library.search(tags=["枚举", "DP"])} == {both.id}
    assert len(library.search(tags=["枚举"])) == 2


def test_filter_by_difficulty(library):
    hard = library.create("难题", difficulty=Difficulty.HARD)
    library.create("简单题", difficulty=Difficulty.EASY)
    assert {e.id for e in library.search(difficulty=Difficulty.HARD)} == {hard.id}


def test_unreviewed_filter_is_derived_not_stored(library):
    """"未复习"由 last_review_time 派生，不落库（文档 2.1.2）。"""
    entry = library.create("还没复习过")
    assert [e.id for e in library.search(status=StatusFilter.UNREVIEWED)] == [entry.id]

    library.review(entry.id, 5)
    assert library.search(status=StatusFilter.UNREVIEWED) == []


def test_filters_combine(library):
    target = library.create(
        "目标", tags=["DP"], difficulty=Difficulty.HARD, error_category=ErrorCategory.OVERFLOW
    )
    library.create("同标签但简单", tags=["DP"], difficulty=Difficulty.EASY)

    found = library.search(tags=["DP"], difficulty=Difficulty.HARD)
    assert [e.id for e in found] == [target.id]


def test_manual_status_override_does_not_touch_srs(library):
    """文档用例 6。"""
    entry = library.create("手动覆盖")
    library.set_status(entry.id, ReviewStatus.MASTERED)

    assert entry.review_status is ReviewStatus.MASTERED
    assert entry.srs.interval == 0
    assert {e.id for e in library.search(status=StatusFilter.MASTERED)} == {entry.id}


def test_all_tags_is_deduplicated_case_insensitively(library):
    library.create("一", tags=["DP", "dp", "枚举"])
    library.create("二", tags=["枚举"])
    assert library.all_tags() == ["DP", "枚举"]


# --- 持久化（文档用例 1） ---------------------------------------------------


def test_data_survives_reopen(layout, day):
    first = Library(layout, today_fn=lambda: day)
    entry = first.create(
        "重启后还在", tags=["DP"], difficulty=Difficulty.HARD, note=Note(ac_code="int main(){}")
    )

    second = Library(layout, today_fn=lambda: day)
    loaded = second.get(entry.id)
    assert loaded.title == "重启后还在"
    assert loaded.tags == ["DP"]
    assert loaded.difficulty is Difficulty.HARD
    assert second.read_note(entry.id).ac_code == "int main(){}"


def test_update_rewrites_index_and_md(library, layout):
    entry = library.create("旧标题", note=Note(summary="总结"))
    library.update(entry.id, title="新标题", tags=["新"], note=Note(summary="总结"))

    assert library.get(entry.id).title == "新标题"
    text = storage.note_path(layout, entry.id).read_text(encoding="utf-8")
    assert "# 新标题" in text
    assert "tags: [新]" in text


def test_update_rejects_empty_title(library):
    entry = library.create("有标题")
    with pytest.raises(ValidationError):
        library.update(entry.id, title="  ")


def test_get_unknown_entry_raises(library):
    with pytest.raises(NotFoundError):
        library.get(storage.new_id())


# --- 删除（文档用例 8） -----------------------------------------------------


def test_delete_removes_both_index_entry_and_md(library, layout):
    entry = library.create("待删除")
    md = storage.note_path(layout, entry.id)
    assert md.exists()

    library.delete(entry.id)

    assert not md.exists()
    assert library.find(entry.id) is None
    assert library.consistency().is_clean


def test_delete_keeps_a_recoverable_backup(library, layout):
    """误删不可恢复是不可接受的，所以删除前必须留一份。"""
    entry = library.create("误删了", note=Note(summary="重要内容"))
    library.delete(entry.id)

    backups = list(layout.backups.glob("auto-deleted-*.json"))
    assert backups
    entries, notes = storage.read_snapshot(backups[0])
    assert entries[0].title == "误删了"
    assert notes[entry.id].summary == "重要内容"


# --- 导出（文档用例 7） -----------------------------------------------------


def test_export_md_produces_typora_ready_file(library, tmp_path):
    entry = library.create(
        "导出测试",
        link="https://oj.example.com/p/1",
        tags=["枚举"],
        difficulty=Difficulty.HARD,
        error_category=ErrorCategory.OVERFLOW,
        note=Note(ac_code="// ok"),
    )
    target = library.export_md(entry.id, tmp_path / "out")

    text = target.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "difficulty: 困难" in text
    assert "error_category: 溢出" in text
    assert "## AC 代码" in text
    assert "// ok" in text
    # 导出的是副本；应用自己的数据文件仍在 notes/ 下
    assert storage.note_path(library.layout, entry.id).exists()


def test_export_md_sanitizes_illegal_filename_characters(library, tmp_path):
    entry = library.create('a/b:c*d?e"f<g>h|i')
    target = library.export_md(entry.id, tmp_path / "out")
    assert target.exists()
    assert not set('<>:"/\\|?*') & set(target.name)
    assert target.name.endswith(".md")


# --- 一致性（文档用例 13） --------------------------------------------------


def test_external_md_removal_is_reported_not_fatal(library, layout):
    kept = library.create("保留")
    removed = library.create("被外部删除")
    storage.note_path(layout, removed.id).unlink()

    report = library.consistency()
    assert report.missing_notes == [removed.id]
    assert kept.id not in report.missing_notes
    # 索引条目仍在（只报告，不自动清理），读取也不抛异常
    assert library.find(removed.id) is not None
    assert library.read_note(removed.id) == Note()


def test_save_writes_index_file(library, layout):
    library.create("落盘")
    assert layout.index.exists()
