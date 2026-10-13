"""数据目录解析与回落策略的测试（项目文档 3.3）。"""

from __future__ import annotations

from pathlib import Path

import pytest

import paths


def make_blocker(tmp_path: Path) -> Path:
    """造一个「是文件不是目录」的路径，用来让 mkdir 必然失败。"""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    return blocker


def test_env_override_wins(tmp_path):
    target = tmp_path / "custom"
    resolved = paths.resolve_data_dir(
        program_directory=tmp_path / "prog",
        environ={paths.ENV_DATA_DIR: str(target)},
    )
    assert resolved == target
    assert target.is_dir()


def test_env_override_that_is_unwritable_raises(tmp_path):
    with pytest.raises(paths.DataDirUnavailable):
        paths.resolve_data_dir(
            environ={paths.ENV_DATA_DIR: str(make_blocker(tmp_path))}
        )


def test_prefers_portable_data_dir_next_to_program(tmp_path):
    prog = tmp_path / "prog"
    prog.mkdir()
    resolved = paths.resolve_data_dir(
        program_directory=prog,
        environ={"APPDATA": str(tmp_path / "appdata")},
    )
    assert resolved == prog / "data"


def test_falls_back_to_appdata_when_program_dir_unwritable(tmp_path):
    appdata = tmp_path / "appdata"
    resolved = paths.resolve_data_dir(
        program_directory=make_blocker(tmp_path),
        environ={"APPDATA": str(appdata)},
    )
    assert resolved == appdata / paths.APP_NAME


def test_raises_when_no_candidate_is_writable(tmp_path):
    blocker = make_blocker(tmp_path)
    with pytest.raises(paths.DataDirUnavailable):
        paths.resolve_data_dir(
            program_directory=blocker,
            environ={"APPDATA": str(blocker)},
        )


def test_ensure_layout_builds_expected_structure(tmp_path):
    layout = paths.ensure_layout(tmp_path / "data")
    assert layout.root.is_dir()
    assert layout.notes.is_dir()
    assert layout.backups.is_dir()
    assert layout.index == tmp_path / "data" / "index.json"
    assert layout.lock.name == ".lock"


def test_is_writable_is_false_for_a_file(tmp_path):
    assert paths.is_writable(make_blocker(tmp_path)) is False
