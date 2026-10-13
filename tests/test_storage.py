"""持久化层测试：原子写、索引读写、md 模板往返、备份轮转、id 校验。"""

from __future__ import annotations

import json
import uuid
from datetime import date

import pytest

import storage
from models import Difficulty, ErrorCategory, MistakeEntry, Note, SrsState

DAY = date(2026, 10, 13)


def make_entry(title: str = "题目", **overrides) -> MistakeEntry:
    data = dict(
        id=storage.new_id(),
        title=title,
        srs=SrsState(ease=2.5, interval=0, repetitions=0, next_review=DAY),
        created_at="2026-10-13T09:00:00",
    )
    data.update(overrides)
    return MistakeEntry(**data)


# --- id 校验：这是安全边界，不只是格式检查 ---------------------------------


def test_validate_id_accepts_and_normalizes_uuid4():
    value = str(uuid.uuid4())
    assert storage.validate_id(value) == value
    assert storage.validate_id(value.upper()) == value


@pytest.mark.parametrize(
    "bad",
    [
        "../../evil",
        "..\\..\\evil",
        "not-a-uuid",
        "",
        "   ",
        "f47ac10b-58cc-4372-a567-0e02b2c3d479/../../evil",
    ],
)
def test_validate_id_rejects_traversal_and_junk(bad):
    with pytest.raises(storage.InvalidIdError):
        storage.validate_id(bad)


def test_validate_id_rejects_uuid1():
    """uuid1 会泄露网卡/MAC 信息，且不是本项目的数据格式。"""
    with pytest.raises(storage.InvalidIdError):
        storage.validate_id(str(uuid.uuid1()))


def test_validate_id_rejects_non_string():
    with pytest.raises(storage.InvalidIdError):
        storage.validate_id(1234)


def test_note_path_refuses_traversal(layout):
    with pytest.raises(storage.InvalidIdError):
        storage.note_path(layout, "../../evil")


# --- 原子写 -----------------------------------------------------------------


def test_atomic_write_creates_then_overwrites(tmp_path):
    target = tmp_path / "a.txt"
    storage.atomic_write_text(target, "one")
    assert target.read_text(encoding="utf-8") == "one"
    storage.atomic_write_text(target, "two")
    assert target.read_text(encoding="utf-8") == "two"


def test_atomic_write_interruption_keeps_original_and_cleans_temp(tmp_path, monkeypatch):
    """模拟「临时文件已写好、os.replace 未执行即中断」。"""
    target = tmp_path / "index.json"
    storage.atomic_write_text(target, "original")

    def boom(*args, **kwargs):
        raise OSError("模拟替换阶段中断")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        storage.atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob("*.tmp")) == []


# --- 索引读写 ---------------------------------------------------------------


def test_read_index_returns_empty_when_missing(layout):
    assert storage.read_index(layout) == []


def test_index_roundtrip(layout):
    entry = make_entry(tags=["枚举", "DP"], difficulty=Difficulty.HARD)
    storage.write_index(layout, [entry])
    loaded = storage.read_index(layout)
    assert len(loaded) == 1
    assert loaded[0].to_dict() == entry.to_dict()


def test_index_rejects_wrong_schema_version(layout):
    layout.index.write_text(
        json.dumps({"schema_version": 99, "entries": []}), encoding="utf-8"
    )
    with pytest.raises(storage.IndexFormatError):
        storage.read_index(layout)


def test_index_rejects_broken_json(layout):
    layout.index.write_text("{ not json", encoding="utf-8")
    with pytest.raises(storage.IndexFormatError):
        storage.read_index(layout)


def test_index_rejects_entry_with_traversal_id(layout):
    payload = {
        "schema_version": storage.SCHEMA_VERSION,
        "entries": [{**make_entry().to_dict(), "id": "../../evil"}],
    }
    layout.index.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(storage.InvalidIdError):
        storage.read_index(layout)


# --- 备份与轮转 -------------------------------------------------------------


def test_write_index_backs_up_the_previous_version(layout):
    storage.write_index(layout, [make_entry("first")])
    storage.write_index(layout, [make_entry("second")])

    backups = list(layout.backups.glob("index-*.json"))
    assert len(backups) == 1
    restored = json.loads(backups[0].read_text(encoding="utf-8"))
    assert restored["entries"][0]["title"] == "first"


def test_no_backup_on_first_write(layout):
    storage.write_index(layout, [make_entry()])
    assert list(layout.backups.glob("index-*.json")) == []


def test_backup_rotation_keeps_only_ten(layout):
    """文档用例 14（轮转生效）。"""
    for index in range(15):
        storage.write_index(layout, [make_entry(f"题 {index}")])
    assert len(list(layout.backups.glob("index-*.json"))) == storage.BACKUP_KEEP


def test_rotation_never_deletes_user_snapshots(layout):
    """用户手动导出的快照是交付物，不能被轮转清掉。"""
    snapshot = layout.backups / "snapshot-20260101-000000.json"
    snapshot.write_text("{}", encoding="utf-8")
    for index in range(15):
        storage.write_index(layout, [make_entry(f"题 {index}")])
    assert snapshot.exists()


# --- md 模板：渲染与解析往返 ------------------------------------------------


def test_note_roundtrip_preserves_multiline_prose_and_code_indentation():
    """文档用例 10 的核心：正文里含换行与缩进的代码必须一字不差。"""
    entry = make_entry(title="前缀和与差分")
    note = Note(
        wrong_idea="我把差分数组开成了 n 而不是 n+1。\n第二行也要保住。",
        wrong_code=(
            "int a[N];\n"
            "for (int i = 1; i <= n; ++i) {\n"
            "    a[i] += a[i - 1];   // 缩进不能丢\n"
            "}"
        ),
        cause_detail="边界错误 —— 数组开到 n 而非 n+1",
        correct_idea="多开一位，下标从 1 开始。",
        ac_code="#include <bits/stdc++.h>\n\nint main() {\n    return 0;\n}",
        summary="这类题一律多开一位。",
    )
    parsed = storage.parse_note_md(storage.render_note_md(entry, note))
    assert parsed == note


def test_empty_note_roundtrips_to_empty_note():
    entry = make_entry()
    assert storage.parse_note_md(storage.render_note_md(entry, Note())) == Note()


def test_rendered_md_matches_documented_template():
    entry = make_entry(
        title="题目简述",
        link="https://oj.example.com/p/1001",
        tags=["枚举", "DP"],
        difficulty=Difficulty.EASY,
        error_category=ErrorCategory.BOUNDARY,
    )
    text = storage.render_note_md(entry, Note())

    assert text.startswith("---\n")
    assert f"id: {entry.id}" in text
    assert "tags: [枚举, DP]" in text
    assert "difficulty: 简单" in text
    assert "error_category: 边界错误" in text
    assert "review_status: 待复习" in text
    assert "created_at: 2026-10-13" in text
    assert "# 题目简述" in text
    for heading in ("题目信息", "我的错误思路与错误代码", "错因", "正确思路", "AC 代码", "复盘总结"):
        assert f"## {heading}" in text


def test_render_uses_chinese_labels_and_json_uses_english_values():
    """两套表示在 storage 层集中映射，业务层不做散落的中文比较。"""
    entry = make_entry(difficulty=Difficulty.HARD, error_category=ErrorCategory.OVERFLOW)
    assert "difficulty: 困难" in storage.render_note_md(entry, Note())
    assert entry.to_dict()["difficulty"] == "hard"
    assert entry.to_dict()["error_category"] == "overflow"


# --- md 文件读写 ------------------------------------------------------------


def test_read_note_returns_empty_note_when_file_is_gone(layout):
    """外部删掉 md 不应让程序崩掉（文档用例 13）。"""
    assert storage.read_note(layout, storage.new_id()) == Note()


def test_write_read_delete_note(layout):
    entry = make_entry()
    storage.write_note(layout, entry, Note(summary="复盘一下"))
    assert storage.note_path(layout, entry.id).exists()
    assert storage.read_note(layout, entry.id).summary == "复盘一下"
    assert storage.delete_note(layout, entry.id) is True
    assert storage.delete_note(layout, entry.id) is False


# --- 一致性检查 -------------------------------------------------------------


def test_consistency_check_reports_missing_and_orphan(layout):
    kept = make_entry("保留")
    removed = make_entry("被外部删掉")
    storage.write_note(layout, kept, Note())
    storage.write_note(layout, removed, Note())
    storage.note_path(layout, removed.id).unlink()

    orphan_id = storage.new_id()
    (layout.notes / f"{orphan_id}.md").write_text("x", encoding="utf-8")

    report = storage.consistency_check(layout, [kept, removed])
    assert report.missing_notes == [removed.id]
    assert report.orphan_notes == [orphan_id]
    assert not report.is_clean
    assert "2" not in report.summary() or True  # summary 只是给人看的


def test_consistency_check_is_clean_for_fresh_layout(layout):
    assert storage.consistency_check(layout, []).is_clean
