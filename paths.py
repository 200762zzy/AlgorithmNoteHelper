"""数据目录解析与回落策略（纯标准库，无 Qt）。

设计依据见项目文档 3.3：程序目录只放资源，用户数据放在独立的数据目录。
解析顺序：

1. 环境变量 `ANH_DATA_DIR`（便于测试与高级用户自定义）
2. 程序目录下的 `data/`（便携模式：解压即用、数据跟着文件夹走）
3. `%APPDATA%\\AlgorithmNoteHelper\\`（程序目录不可写时）
4. 都不可写则抛 `DataDirUnavailable`

把用户数据写进程序安装目录会踩两个坑：装在 `C:\\Program Files\\` 时无写权限
导致保存失败；重装或升级时数据被覆盖。因此这里必须做真实的可写性探测。
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ENV_DATA_DIR = "ANH_DATA_DIR"
APP_NAME = "AlgorithmNoteHelper"
INDEX_FILENAME = "index.json"


class DataDirUnavailable(RuntimeError):
    """所有候选数据目录都不可写。"""


@dataclass(frozen=True)
class DataLayout:
    """数据目录内的固定路径集合。"""

    root: Path
    notes: Path
    backups: Path
    index: Path
    lock: Path


def program_dir() -> Path:
    """程序（资源）目录。打包后为 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def appdata_dir(environ: dict | None = None) -> Path:
    """用户数据目录。"""
    env = os.environ if environ is None else environ
    base = env.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ("." + APP_NAME.lower())


def is_writable(directory: Path) -> bool:
    """真实探测可写性：尝试在其中创建并删除一个临时文件。

    只判断 `os.access` 是不够的 —— 它在 Windows 上对 ACL 的判断常常不准，
    必须真的写一次。
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".write-probe-", suffix=".tmp", delete=True
        ):
            return True
    except OSError:
        return False


def resolve_data_dir(
    program_directory: Path | None = None,
    environ: dict | None = None,
) -> Path:
    """按上述顺序解析数据目录，并确保它存在且可写。"""
    env = os.environ if environ is None else environ
    prog = program_dir() if program_directory is None else Path(program_directory)

    override = str(env.get(ENV_DATA_DIR) or "").strip()
    if override:
        candidate = Path(override).expanduser()
        if is_writable(candidate):
            return candidate
        raise DataDirUnavailable(
            f"{ENV_DATA_DIR} 指定的数据目录不可写：{candidate}"
        )

    tried: list[Path] = []
    for candidate in (prog / "data", appdata_dir(env)):
        if is_writable(candidate):
            return candidate
        tried.append(candidate)

    raise DataDirUnavailable(
        "找不到可写的数据目录，已尝试：" + "、".join(str(p) for p in tried)
    )


def ensure_layout(data_dir: Path) -> DataLayout:
    """建立数据目录骨架并返回固定路径集合。"""
    root = Path(data_dir)
    notes = root / "notes"
    backups = root / "backups"
    for directory in (root, notes, backups):
        directory.mkdir(parents=True, exist_ok=True)
    return DataLayout(
        root=root,
        notes=notes,
        backups=backups,
        index=root / INDEX_FILENAME,
        lock=root / ".lock",
    )
