"""持久化层：`index.json` 与 `notes/{id}.md` 读写、原子写、快照、备份轮转。

关键约束（见项目文档 3.2、6）：
- **原子写**：同目录临时文件 → flush+fsync → `os.replace`，失败时原文件不动；
- **id 校验**：id 直接用作文件名，不校验就会允许 `../../evil` 之类的路径穿越；
- **快照内联正文**：不含正文的备份恢复出来只有索引，正文（错因、AC 代码）才是
  本工具的全部价值；
- **单一写入者**：`notes/` 下的 md 由本模块整体重写，外部编辑会被覆盖。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from models import MistakeEntry, Note, now_iso
from paths import DataLayout

SCHEMA_VERSION = 1
SNAPSHOT_KIND = "AlgorithmNoteHelper-snapshot"
APP_VERSION = "0.1.1"

# 自动备份各保留的份数。用户手动导出的 snapshot-* **不参与轮转**，不会被自动删除。
BACKUP_KEEP = 10
_ROTATED_PREFIXES = ("index-", "auto-")

_MD_TITLE_HEADING = "题目信息"
_SECTION_WRONG = "我的错误思路与错误代码"
_SECTION_CAUSE = "错因"
_SECTION_CORRECT = "正确思路"
_SECTION_AC = "AC 代码"
_SECTION_SUMMARY = "复盘总结"


# --------------------------------------------------------------------------
# 异常
# --------------------------------------------------------------------------


class StorageError(Exception):
    """持久化层错误基类。"""


class InvalidIdError(StorageError):
    """id 不是合法的 uuid4。"""


class IndexFormatError(StorageError):
    """`index.json` 结构损坏。"""


class SnapshotFormatError(StorageError):
    """快照文件结构损坏或不是快照。"""


# --------------------------------------------------------------------------
# id 校验与生成
# --------------------------------------------------------------------------


def new_id() -> str:
    return str(uuid.uuid4())


def validate_id(value) -> str:
    """校验并规范化 id，要求是**规范写法的 uuid4**。

    这是安全边界，不只是格式检查：`id` 会被拼进 `notes/{id}.md`，若不校验，
    一份被构造过的快照就能借 `id` 写到数据目录之外。
    """
    if not isinstance(value, str):
        raise InvalidIdError(f"id 必须是字符串，实际为 {type(value).__name__}")
    text = value.strip()
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidIdError(f"id 不是合法的 UUID：{value!r}") from exc
    if parsed.version != 4:
        raise InvalidIdError(f"id 必须是 uuid4，实际为 uuid{parsed.version}：{value!r}")
    if str(parsed) != text.lower():
        raise InvalidIdError(f"id 不是规范的 uuid4 写法：{value!r}")
    return text.lower()


# --------------------------------------------------------------------------
# 原子写
# --------------------------------------------------------------------------


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """原子地把文本写入 `path`。

    临时文件必须与目标**同目录**，否则 `os.replace` 可能跨卷失败。任何异常都会
    清掉临时文件并保持原文件不变。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _unique_path(directory: Path, stem: str, suffix: str = ".json") -> Path:
    """同一秒内多次导出时避免互相覆盖。"""
    candidate = directory / f"{stem}{suffix}"
    index = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{index}{suffix}"
        index += 1
    return candidate


# --------------------------------------------------------------------------
# 备份与轮转
# --------------------------------------------------------------------------


def rotate_backups(backups_dir: Path, keep: int = BACKUP_KEEP) -> list[Path]:
    """轮转**自动**备份，每个前缀各保留最近 `keep` 份。

    用户手动导出的 `snapshot-*.json` 不在此列 —— 那是交付物，不该被程序删掉。
    按修改时间排序（而非文件名），避免同一秒内的命名后缀影响顺序。
    """
    backups_dir = Path(backups_dir)
    if not backups_dir.is_dir():
        return []
    removed: list[Path] = []
    for prefix in _ROTATED_PREFIXES:
        files = sorted(
            (p for p in backups_dir.glob(f"{prefix}*.json") if p.is_file()),
            key=lambda p: (p.stat().st_mtime, p.name),
        )
        for stale in files[: max(0, len(files) - keep)]:
            try:
                stale.unlink()
                removed.append(stale)
            except OSError:
                pass
    return removed


def backup_index(layout: DataLayout, stamp: str | None = None) -> Path | None:
    """把当前 `index.json` 复制到 `backups/`，然后轮转。"""
    if not layout.index.exists():
        return None
    layout.backups.mkdir(parents=True, exist_ok=True)
    target = _unique_path(layout.backups, f"index-{stamp or _stamp()}")
    shutil.copyfile(layout.index, target)
    rotate_backups(layout.backups)
    return target


# --------------------------------------------------------------------------
# 索引读写
# --------------------------------------------------------------------------


def read_index(layout: DataLayout) -> list[MistakeEntry]:
    """读取 `index.json`。文件不存在时返回空列表。

    结构损坏（JSON 语法、schema_version 不符、条目字段非法）会抛
    `IndexFormatError` / `InvalidIdError`，绝不静默丢弃数据。
    """
    if not layout.index.exists():
        return []
    try:
        payload = json.loads(layout.index.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IndexFormatError(f"index.json 不是合法 JSON：{exc}") from exc

    if not isinstance(payload, dict):
        raise IndexFormatError("index.json 顶层应为对象")

    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise IndexFormatError(
            f"index.json 的 schema_version={version!r}，本程序只支持 {SCHEMA_VERSION}"
        )

    raw_entries = payload.get("entries")
    if raw_entries is None:
        raw_entries = []
    if not isinstance(raw_entries, list):
        raise IndexFormatError("index.json 的 entries 应为数组")

    entries: list[MistakeEntry] = []
    for position, raw in enumerate(raw_entries):
        try:
            entry = MistakeEntry.from_dict(raw)
        except (ValueError, KeyError, TypeError) as exc:
            raise IndexFormatError(f"index.json 第 {position} 条非法：{exc}") from exc
        validate_id(entry.id)
        entries.append(entry)
    return entries


def write_index(layout: DataLayout, entries: list[MistakeEntry]) -> None:
    """原子写入索引；写入前先备份当前索引并轮转。"""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "entries": [entry.to_dict() for entry in entries],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if layout.index.exists():
        backup_index(layout)
    atomic_write_text(layout.index, text)


# --------------------------------------------------------------------------
# 正文 md：渲染与解析
# --------------------------------------------------------------------------


def _date_part(value: str) -> str:
    return (value or "")[:10]


def render_note_md(entry: MistakeEntry, note: Note) -> str:
    """按项目文档 3.2.1 的模板渲染 md。"""
    tags = ", ".join(entry.tags)
    lines: list[str] = [
        "---",
        f"id: {entry.id}",
        f"title: {entry.title}",
        f"link: {entry.link}",
        f"tags: [{tags}]",
        f"difficulty: {entry.difficulty.zh}",
        f"error_category: {entry.error_category.zh}",
        f"review_status: {entry.review_status.zh}",
        f"created_at: {_date_part(entry.created_at)}",
        f"last_review_time: {entry.last_review_time or ''}".rstrip(),
        "---",
        "",
        f"# {entry.title}",
        "",
        f"## {_MD_TITLE_HEADING}",
        "",
        entry.link,
        "",
        f"## {_SECTION_WRONG}",
        "",
    ]
    if note.wrong_idea.strip():
        lines += [note.wrong_idea.strip("\n"), ""]
    lines += ["```cpp", note.wrong_code.strip("\n"), "```", ""]
    lines += [f"## {_SECTION_CAUSE}", "", note.cause_detail.strip("\n"), ""]
    lines += [f"## {_SECTION_CORRECT}", "", note.correct_idea.strip("\n"), ""]
    lines += [f"## {_SECTION_AC}", "", "```cpp", note.ac_code.strip("\n"), "```", ""]
    lines += [f"## {_SECTION_SUMMARY}", "", note.summary.strip("\n"), ""]
    return "\n".join(lines)


_FRONT_MATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---[ \t]*\r?\n", re.S)
_SECTION_RE = re.compile(r"^##[ \t]*(.+?)[ \t]*$", re.M)
_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def _split_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(body))
    for position, match in enumerate(matches):
        start = match.end()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(body)
        sections[match.group(1).strip()] = body[start:end]
    return sections


def _split_prose_and_code(text: str) -> tuple[str, str]:
    codes = [m.group(1).strip("\n") for m in _FENCE_RE.finditer(text)]
    prose = _FENCE_RE.sub("", text).strip("\n").strip()
    return prose, (codes[0] if codes else "")


def _prose_only(text: str) -> str:
    return _FENCE_RE.sub("", text).strip("\n").strip()


def _code_preferred(text: str) -> str:
    codes = [m.group(1).strip("\n") for m in _FENCE_RE.finditer(text)]
    if codes:
        return codes[0]
    return text.strip("\n").strip()


def parse_note_md(text: str) -> Note:
    """把 md 正文解析回 `Note`。

    规范化说明：各小节首尾的空行会被去掉（渲染时也如此），因此往返是稳定的，
    但正文首尾的空白不具保留意义。
    """
    body = _FRONT_MATTER_RE.sub("", text, count=1)
    sections = _split_sections(body)
    wrong_idea, wrong_code = _split_prose_and_code(sections.get(_SECTION_WRONG, ""))
    return Note(
        wrong_idea=wrong_idea,
        wrong_code=wrong_code,
        cause_detail=_prose_only(sections.get(_SECTION_CAUSE, "")),
        correct_idea=_prose_only(sections.get(_SECTION_CORRECT, "")),
        ac_code=_code_preferred(sections.get(_SECTION_AC, "")),
        summary=_prose_only(sections.get(_SECTION_SUMMARY, "")),
    )


def note_path(layout: DataLayout, entry_id: str) -> Path:
    """正文路径由 id 推导，id 必须先过校验。"""
    return layout.notes / f"{validate_id(entry_id)}.md"


def read_note(layout: DataLayout, entry_id: str) -> Note:
    """读取正文。文件缺失时返回空 `Note`，不抛异常。

    「索引有、md 没有」属于需要在界面上报告的不一致，由
    `consistency_check()` 统一呈现，不应让程序直接崩掉。
    """
    path = note_path(layout, entry_id)
    if not path.exists():
        return Note()
    return parse_note_md(path.read_text(encoding="utf-8"))


def write_note(layout: DataLayout, entry: MistakeEntry, note: Note) -> Path:
    path = note_path(layout, entry.id)
    atomic_write_text(path, render_note_md(entry, note))
    return path


def delete_note(layout: DataLayout, entry_id: str) -> bool:
    path = note_path(layout, entry_id)
    if path.exists():
        path.unlink()
        return True
    return False


# --------------------------------------------------------------------------
# 快照
# --------------------------------------------------------------------------


def build_snapshot(
    entries: list[MistakeEntry],
    notes: dict[str, Note],
    exported_at: str | None = None,
) -> dict:
    """构造快照内容：索引字段 + 内联正文。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": SNAPSHOT_KIND,
        "app_version": APP_VERSION,
        "exported_at": exported_at or now_iso(),
        "entries": [
            {**entry.to_dict(), "note": notes.get(entry.id, Note()).to_dict()}
            for entry in entries
        ],
    }


def write_snapshot(
    layout: DataLayout,
    entries: list[MistakeEntry],
    notes: dict[str, Note],
    prefix: str = "snapshot",
    dest_dir: Path | None = None,
    stamp: str | None = None,
) -> Path:
    """写出快照。`dest_dir` 为空时写入 `backups/`，可指定外部目录用于分享。"""
    target_dir = Path(dest_dir) if dest_dir is not None else layout.backups
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_path(target_dir, f"{prefix}-{stamp or _stamp()}")
    payload = build_snapshot(entries, notes)
    atomic_write_text(
        target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    rotate_backups(layout.backups)
    return target


def read_snapshot(path: Path) -> tuple[list[MistakeEntry], dict[str, Note]]:
    """读取并严格校验快照。

    任何一条 id 非法都会让**整份快照**被拒绝：宁可拒绝，也不要写进半个数据目录。
    """
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnapshotFormatError(f"{path.name} 不是合法 JSON：{exc}") from exc

    if not isinstance(payload, dict):
        raise SnapshotFormatError("快照顶层应为对象")
    if payload.get("kind") != SNAPSHOT_KIND:
        raise SnapshotFormatError(
            "这不像是本程序导出的快照（kind 字段不符）。"
            "如果你选的是 index.json，请改用「导出快照」生成的文件。"
        )
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SnapshotFormatError(
            f"快照的 schema_version={version!r}，本程序只支持 {SCHEMA_VERSION}"
        )

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise SnapshotFormatError("快照的 entries 应为数组")

    entries: list[MistakeEntry] = []
    notes: dict[str, Note] = {}
    for position, raw in enumerate(raw_entries):
        try:
            entry = MistakeEntry.from_dict(raw)
        except (ValueError, KeyError, TypeError) as exc:
            raise SnapshotFormatError(f"快照第 {position} 条非法：{exc}") from exc
        validate_id(entry.id)
        entries.append(entry)
        notes[entry.id] = Note.from_dict(raw.get("note"))
    return entries, notes


# --------------------------------------------------------------------------
# 一致性检查
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsistencyReport:
    """索引与 `notes/` 的差异。只报告，不自动删任何东西。"""

    missing_notes: list[str]
    orphan_notes: list[str]

    @property
    def is_clean(self) -> bool:
        return not self.missing_notes and not self.orphan_notes

    def summary(self) -> str:
        if self.is_clean:
            return "索引与 notes/ 一致"
        parts = []
        if self.missing_notes:
            parts.append(f"{len(self.missing_notes)} 条索引缺少 md 文件")
        if self.orphan_notes:
            parts.append(f"{len(self.orphan_notes)} 个 md 文件没有对应索引")
        return "；".join(parts)


def consistency_check(
    layout: DataLayout, entries: list[MistakeEntry]
) -> ConsistencyReport:
    """对比索引与 `notes/` 目录。"""
    expected = {entry.id for entry in entries}
    present = {
        path.stem
        for path in layout.notes.glob("*.md")
        if path.is_file() and _is_uuid4(path.stem)
    }
    return ConsistencyReport(
        missing_notes=sorted(expected - present),
        orphan_notes=sorted(present - expected),
    )


def _is_uuid4(text: str) -> bool:
    try:
        validate_id(text)
    except InvalidIdError:
        return False
    return True
