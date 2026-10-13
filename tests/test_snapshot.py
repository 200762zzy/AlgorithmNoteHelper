"""快照导出/恢复/导入测试（文档用例 10、11、12）。"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

import paths
import storage
from models import Difficulty, Note, ReviewStatus
from services import (
    CONFLICT_COPY,
    CONFLICT_OVERWRITE,
    CONFLICT_SKIP,
    Library,
    ValidationError,
)

DAY = date(2026, 10, 13)


def full_note(**overrides) -> Note:
    data = dict(
        wrong_idea="错在没考虑 n == 0",
        wrong_code="for (int i = 0; i < n; ++i) {\n    sum += a[i];\n}",
        cause_detail="边界错误 —— 空输入没有特判",
        correct_idea="先特判 n == 0。",
        ac_code="int main() {\n    // ac\n    return 0;\n}",
        summary="以后先想空输入。",
    )
    data.update(overrides)
    return Note(**data)


def fresh_library(tmp_path, name: str, day: date = DAY) -> Library:
    return Library(paths.ensure_layout(tmp_path / name), today_fn=lambda: day)


# --- 导出 -------------------------------------------------------------------


def test_snapshot_carries_kind_version_and_inline_note(library):
    library.create("快照", note=full_note())
    path = library.export_snapshot()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == storage.SNAPSHOT_KIND
    assert payload["schema_version"] == storage.SCHEMA_VERSION
    assert payload["app_version"] == storage.APP_VERSION
    assert payload["exported_at"]
    # 正文必须内联，否则恢复出来只有索引
    assert payload["entries"][0]["note"]["ac_code"] == full_note().ac_code
    assert payload["entries"][0]["note"]["summary"] == "以后先想空输入。"


def test_snapshot_can_be_exported_to_an_external_directory(library, tmp_path):
    library.create("分享用")
    target = library.export_snapshot(dest_dir=tmp_path / "share")
    assert target.parent == tmp_path / "share"
    assert target.name.startswith("snapshot-")


def test_exporting_twice_in_the_same_second_does_not_overwrite(library, tmp_path):
    library.create("两次导出")
    first = library.export_snapshot(dest_dir=tmp_path / "share")
    second = library.export_snapshot(dest_dir=tmp_path / "share")
    assert first != second
    assert first.exists() and second.exists()


# --- 往返（文档用例 10） ----------------------------------------------------


def test_roundtrip_into_a_blank_data_dir_keeps_everything(library, tmp_path):
    entry = library.create(
        "往返",
        link="https://oj.example.com/p/2",
        tags=["DP", "枚举"],
        difficulty=Difficulty.HARD,
        note=full_note(),
    )
    snapshot = library.export_snapshot(dest_dir=tmp_path / "share")

    target = fresh_library(tmp_path, "fresh")
    result = target.import_snapshot(snapshot)

    assert result.added == 1
    restored = target.get(entry.id)
    assert restored.title == "往返"
    assert restored.link == "https://oj.example.com/p/2"
    assert restored.tags == ["DP", "枚举"]
    assert restored.difficulty is Difficulty.HARD
    # 正文一字不差，且 md 文件确实被写出来了
    assert target.read_note(entry.id) == full_note()
    assert storage.note_path(target.layout, entry.id).exists()
    assert target.consistency().is_clean


def test_roundtrip_preserves_srs_schedule_and_status(library, tmp_path):
    entry = library.create("已掌握")
    for _ in range(4):
        library.review(entry.id, 5)
    assert entry.review_status is ReviewStatus.MASTERED
    snapshot = library.export_snapshot(dest_dir=tmp_path / "share")

    target = fresh_library(tmp_path, "fresh")
    target.import_snapshot(snapshot)

    restored = target.get(entry.id)
    assert restored.review_status is ReviewStatus.MASTERED
    assert restored.srs.interval == entry.srs.interval
    assert restored.srs.repetitions == entry.srs.repetitions
    assert restored.srs.next_review == entry.srs.next_review
    # ease 落盘时保留 4 位小数，比较用容差
    assert restored.srs.ease == pytest.approx(entry.srs.ease, abs=1e-3)


def test_empty_snapshot_is_a_noop(library, tmp_path):
    snapshot = library.export_snapshot(dest_dir=tmp_path / "share")
    result = library.import_snapshot(snapshot)
    assert result.total == 0
    assert result.skipped == 0
    assert result.conflicts == []
    assert library.entries == []


# --- 拒绝非法输入（文档用例 12） --------------------------------------------


def test_import_rejects_traversal_id_and_writes_nothing(library, tmp_path):
    payload = {
        "schema_version": storage.SCHEMA_VERSION,
        "kind": storage.SNAPSHOT_KIND,
        "entries": [{**library.create("诱饵").to_dict(), "id": "../../evil"}],
    }
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    notes_before = {p.name for p in library.layout.notes.iterdir()}
    backups_before = {p.name for p in library.layout.backups.iterdir()}

    with pytest.raises(storage.InvalidIdError):
        library.import_snapshot(bad)

    assert {p.name for p in library.layout.notes.iterdir()} == notes_before
    # 整份拒绝：连自动备份都不该发生，说明校验在任何写入之前
    assert {p.name for p in library.layout.backups.iterdir()} == backups_before
    assert not (tmp_path / "evil.md").exists()


def test_import_rejects_a_plain_index_file(library, layout):
    """把 index.json 当快照导入必须被识破，而不是导入半个库。"""
    library.create("随便一条")
    with pytest.raises(storage.SnapshotFormatError):
        library.import_snapshot(layout.index)


def test_import_rejects_wrong_schema_version(library, tmp_path):
    bad = tmp_path / "old.json"
    bad.write_text(
        json.dumps({"kind": storage.SNAPSHOT_KIND, "schema_version": 0, "entries": []}),
        encoding="utf-8",
    )
    with pytest.raises(storage.SnapshotFormatError):
        library.import_snapshot(bad)


def test_import_rejects_broken_json(library, tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{ nope", encoding="utf-8")
    with pytest.raises(storage.SnapshotFormatError):
        library.import_snapshot(bad)


def test_unknown_conflict_mode_is_rejected_before_touching_disk(library, tmp_path):
    with pytest.raises(ValidationError):
        library.import_snapshot(tmp_path / "missing.json", conflict="explode")


# --- 冲突处理（文档用例 11） ------------------------------------------------


def incoming_snapshot(library, tmp_path, title: str, summary: str):
    """导出一份快照，并把其中那一条改成「对方」的版本。"""
    path = library.export_snapshot(dest_dir=tmp_path / "share")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["entries"][0]["title"] = title
    payload["entries"][0]["note"]["summary"] = summary
    target = tmp_path / "incoming.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


def test_conflict_skip_keeps_local_version(library, tmp_path):
    entry = library.create("本地标题", note=full_note(summary="本地的"))
    incoming = incoming_snapshot(library, tmp_path, "对方的标题", "对方的")

    result = library.import_snapshot(incoming, conflict=CONFLICT_SKIP)

    assert result.skipped == 1
    assert result.conflicts == [entry.id]
    assert library.get(entry.id).title == "本地标题"
    assert library.read_note(entry.id).summary == "本地的"


def test_conflict_overwrite_replaces_local_version(library, tmp_path):
    entry = library.create("本地标题", note=full_note(summary="本地的"))
    incoming = incoming_snapshot(library, tmp_path, "对方的标题", "对方的")

    result = library.import_snapshot(incoming, conflict=CONFLICT_OVERWRITE)

    assert result.overwritten == 1
    assert library.get(entry.id).title == "对方的标题"
    assert library.read_note(entry.id).summary == "对方的"
    assert len(library.entries) == 1


def test_conflict_copy_keeps_both_versions(library, tmp_path):
    """「把同学的题解收进来」的主要场景：两边都要留住。"""
    entry = library.create("本地标题", note=full_note(summary="本地的"))
    incoming = incoming_snapshot(library, tmp_path, "对方的标题", "对方的")

    result = library.import_snapshot(incoming, conflict=CONFLICT_COPY)

    assert result.copied == 1
    ids = {item.id for item in library.entries}
    assert len(ids) == 2
    assert entry.id in ids
    assert library.read_note(entry.id).summary == "本地的"

    copied_id = next(i for i in ids if i != entry.id)
    assert library.get(copied_id).title == "对方的标题"
    assert library.read_note(copied_id).summary == "对方的"
    assert library.consistency().is_clean


# --- 导入前的自动备份 -------------------------------------------------------


def test_import_backs_up_the_current_state_first(library, layout, tmp_path):
    library.create("原有内容")
    source = fresh_library(tmp_path, "other")
    source.create("别人的题", note=full_note())
    snapshot = source.export_snapshot(dest_dir=tmp_path / "share")

    library.import_snapshot(snapshot)

    preimport = list(layout.backups.glob("auto-preimport-*.json"))
    assert preimport
    entries, _ = storage.read_snapshot(preimport[0])
    assert [e.title for e in entries] == ["原有内容"]
    assert list(layout.backups.glob("index-*.json"))


def test_importing_many_entries_from_a_classmate(library, tmp_path):
    source = fresh_library(tmp_path, "classmate")
    for index in range(5):
        source.create(f"同学的第 {index} 题", tags=["DP"], note=full_note())
    snapshot = source.export_snapshot(dest_dir=tmp_path / "share")

    result = library.import_snapshot(snapshot)

    assert result.added == 5
    assert len(library.entries) == 5
    assert library.consistency().is_clean
    assert all(item.tags == ["DP"] for item in library.entries)
