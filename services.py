"""业务逻辑层：增删改查、搜索筛选、待复习队列、导出、快照恢复与导入。

本层是**唯一**把「复习状态」与「SM-2 排期」组合起来的地方（见项目文档 3.1 的
接口边界）。`srs.py` 保持纯净，不认识 `review_status`；组合判断落在
`in_review_queue()`。

所有写操作都会立即落盘（`save()`），避免界面上忘记保存导致丢数据。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

import paths
import storage
from models import (
    MASTERED_GRACE_DAYS,
    Difficulty,
    ErrorCategory,
    MistakeEntry,
    Note,
    ReviewStatus,
    StatusFilter,
    now_iso,
    today as default_today,
)
from srs import apply_review, is_due as srs_is_due, is_mastered, new_state

CONFLICT_SKIP = "skip"
CONFLICT_OVERWRITE = "overwrite"
CONFLICT_COPY = "copy"
CONFLICT_MODES = (CONFLICT_SKIP, CONFLICT_OVERWRITE, CONFLICT_COPY)

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class NotFoundError(LookupError):
    """指定的错题不存在。"""


class ValidationError(ValueError):
    """字段校验失败。"""


@dataclass
class ImportResult:
    """一次快照导入的结果。"""

    added: int = 0
    overwritten: int = 0
    skipped: int = 0
    copied: int = 0
    conflicts: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.added + self.overwritten + self.copied

    def summary(self) -> str:
        parts = [
            f"新增 {self.added}",
            f"覆盖 {self.overwritten}",
            f"跳过 {self.skipped}",
            f"导入为副本 {self.copied}",
        ]
        return "；".join(parts)


class Library:
    """一个数据目录上的错题库门面。"""

    def __init__(self, layout: paths.DataLayout, today_fn=default_today):
        self.layout = layout
        self._today_fn = today_fn
        self._entries: list[MistakeEntry] = []
        self.load()

    # -- 装配 ------------------------------------------------------------

    @classmethod
    def open(
        cls,
        data_dir: Path | None = None,
        today_fn=default_today,
    ) -> "Library":
        """解析数据目录并打开错题库。"""
        resolved = paths.resolve_data_dir() if data_dir is None else Path(data_dir)
        return cls(paths.ensure_layout(resolved), today_fn)

    def load(self) -> None:
        self._entries = storage.read_index(self.layout)

    def save(self) -> None:
        storage.write_index(self.layout, self._entries)

    # -- 查询 ------------------------------------------------------------

    @property
    def entries(self) -> list[MistakeEntry]:
        return list(self._entries)

    def find(self, entry_id: str) -> MistakeEntry | None:
        wanted = str(entry_id).strip().lower()
        for entry in self._entries:
            if entry.id == wanted:
                return entry
        return None

    def get(self, entry_id: str) -> MistakeEntry:
        entry = self.find(entry_id)
        if entry is None:
            raise NotFoundError(f"找不到错题：{entry_id}")
        return entry

    def in_review_queue(self, entry: MistakeEntry, day: date | None = None) -> bool:
        """是否应出现在「待复习」队列里。

        - `due`：排期到期即入队；
        - `mastered`：**不是终态**，逾期超过宽限期后重新入队，避免 SM-2 最有价值
          的长间隔段（30 → 90 → 180 天）被截断。
        """
        target = self._day(day)
        if entry.review_status is ReviewStatus.MASTERED:
            return entry.srs.next_review + timedelta(days=MASTERED_GRACE_DAYS) <= target
        return srs_is_due(entry.srs, target)

    def due_queue(self, day: date | None = None) -> list[MistakeEntry]:
        """待复习队列，按到期时间升序（每周复盘用）。"""
        result = [entry for entry in self._entries if self.in_review_queue(entry, day)]
        result.sort(key=lambda e: (e.srs.next_review, e.created_at, e.title))
        return result

    def search(
        self,
        keyword: str | None = None,
        tags: list[str] | None = None,
        difficulty: Difficulty | None = None,
        status: StatusFilter | str | None = None,
        day: date | None = None,
    ) -> list[MistakeEntry]:
        """关键词 / 标签 / 难度 / 复习状态筛选（全部基于索引字段，不读 md）。"""
        wanted_keyword = (keyword or "").strip().lower()
        wanted_tags = [t.strip().lower() for t in (tags or []) if t and t.strip()]
        wanted_difficulty = (
            None if difficulty is None else Difficulty(difficulty)
        )
        wanted_status = None if status is None else StatusFilter(status)

        result: list[MistakeEntry] = []
        for entry in self._entries:
            if wanted_difficulty is not None and entry.difficulty is not wanted_difficulty:
                continue
            if wanted_tags:
                own = {tag.lower() for tag in entry.tags}
                if not all(tag in own for tag in wanted_tags):
                    continue
            if wanted_status is not None and not self._match_status(
                entry, wanted_status, day
            ):
                continue
            if wanted_keyword and wanted_keyword not in self._haystack(entry):
                continue
            result.append(entry)
        return result

    def _match_status(
        self, entry: MistakeEntry, status: StatusFilter, day: date | None = None
    ) -> bool:
        if status is StatusFilter.ALL:
            return True
        if status is StatusFilter.UNREVIEWED:
            # 派生视图：从未评分过
            return entry.last_review_time is None
        if status is StatusFilter.DUE:
            return self.in_review_queue(entry, day)
        return entry.review_status is ReviewStatus.MASTERED

    @staticmethod
    def _haystack(entry: MistakeEntry) -> str:
        """搜索文本。包含中文标签，这样搜「边界」也能命中边界错误。"""
        parts = [
            entry.title,
            entry.link,
            entry.difficulty.value,
            entry.difficulty.zh,
            entry.error_category.value,
            entry.error_category.zh,
            entry.review_status.value,
            entry.review_status.zh,
            *entry.tags,
        ]
        return " ".join(parts).lower()

    def all_tags(self) -> list[str]:
        seen: dict[str, str] = {}
        for entry in self._entries:
            for tag in entry.tags:
                seen.setdefault(tag.lower(), tag)
        return sorted(seen.values(), key=str.lower)

    # -- 增删改 ----------------------------------------------------------

    def create(
        self,
        title: str,
        *,
        link: str = "",
        tags: list[str] | None = None,
        difficulty: Difficulty | str = Difficulty.MEDIUM,
        error_category: ErrorCategory | str = ErrorCategory.OTHER,
        note: Note | None = None,
        day: date | None = None,
    ) -> MistakeEntry:
        """新建错题。**唯一必填字段是题目简述**（见项目文档 2.1.1）。

        新建即为 `due` 且 `next_review = 今天`，因此保存后立刻进入待复习队列。
        """
        text = (title or "").strip()
        if not text:
            raise ValidationError("题目简述不能为空")

        target_day = self._day(day)
        entry = MistakeEntry(
            id=storage.new_id(),
            title=text,
            srs=new_state(target_day),
            link=link or "",
            tags=_normalize_tags(tags),
            difficulty=Difficulty(difficulty),
            error_category=ErrorCategory(error_category),
            review_status=ReviewStatus.DUE,
            created_at=now_iso(),
            last_review_time=None,
        )
        self._entries.append(entry)
        storage.write_note(self.layout, entry, note or Note())
        self.save()
        return entry

    def update(
        self,
        entry_id: str,
        *,
        title: str | None = None,
        link: str | None = None,
        tags: list[str] | None = None,
        difficulty: Difficulty | str | None = None,
        error_category: ErrorCategory | str | None = None,
        review_status: ReviewStatus | str | None = None,
        note: Note | None = None,
    ) -> MistakeEntry:
        """更新字段。md 会随条目一起重写（标题/链接写在 md 里）。"""
        entry = self.get(entry_id)

        if title is not None:
            text = title.strip()
            if not text:
                raise ValidationError("题目简述不能为空")
            entry.title = text
        if link is not None:
            entry.link = link
        if tags is not None:
            entry.tags = _normalize_tags(tags)
        if difficulty is not None:
            entry.difficulty = Difficulty(difficulty)
        if error_category is not None:
            entry.error_category = ErrorCategory(error_category)
        if review_status is not None:
            self._apply_manual_status(entry, review_status)

        body = note if note is not None else storage.read_note(self.layout, entry.id)
        storage.write_note(self.layout, entry, body)
        self.save()
        return entry

    def set_status(
        self, entry_id: str, status: ReviewStatus | str
    ) -> MistakeEntry:
        """手动覆盖复习状态（只改状态，不动 SM-2 参数）。"""
        entry = self.get(entry_id)
        self._apply_manual_status(entry, status)
        storage.write_note(
            self.layout, entry, storage.read_note(self.layout, entry.id)
        )
        self.save()
        return entry

    @staticmethod
    def _apply_manual_status(entry: MistakeEntry, status: ReviewStatus | str) -> None:
        entry.review_status = ReviewStatus(status)

    def delete(self, entry_id: str) -> MistakeEntry:
        """删除错题：索引与 md 同步删除。

        删除前先把这一条（含正文）单独存一份快照到 `backups/`，
        这样「误删」还有救（见项目文档 6）。
        """
        entry = self.get(entry_id)
        storage.backup_index(self.layout)
        storage.write_snapshot(
            self.layout,
            [entry],
            {entry.id: storage.read_note(self.layout, entry.id)},
            prefix="auto-deleted",
        )
        self._entries = [item for item in self._entries if item.id != entry.id]
        storage.delete_note(self.layout, entry.id)
        self.save()
        return entry

    # -- 正文 ------------------------------------------------------------

    def read_note(self, entry_id: str) -> Note:
        return storage.read_note(self.layout, self.get(entry_id).id)

    def save_note(self, entry_id: str, note: Note) -> Note:
        entry = self.get(entry_id)
        storage.write_note(self.layout, entry, note)
        return note

    # -- 复习 ------------------------------------------------------------

    def review(
        self, entry_id: str, quality: int, day: date | None = None
    ) -> MistakeEntry:
        """完成一次复习并重算状态。

        `mastered` 由间隔阈值自动判定；否则回到 `due`。
        """
        entry = self.get(entry_id)
        target_day = self._day(day)
        updated = apply_review(entry.srs, quality, target_day)
        entry.srs = updated
        entry.last_review_time = now_iso()
        entry.review_status = (
            ReviewStatus.MASTERED if is_mastered(updated) else ReviewStatus.DUE
        )
        storage.write_note(
            self.layout, entry, storage.read_note(self.layout, entry.id)
        )
        self.save()
        return entry

    # -- 导出 ------------------------------------------------------------

    def export_md(self, entry_id: str, dest_dir: Path) -> Path:
        """把一条错题导出为 md 到外部目录（给 Typora / Obsidian 用）。

        导出的是**副本**；应用自己的数据文件仍是 `notes/{id}.md`，
        不要去直接编辑那个（见项目文档 3.2 的单一写入者约定）。
        """
        entry = self.get(entry_id)
        note = storage.read_note(self.layout, entry.id)
        target_dir = Path(dest_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{_safe_filename(entry.title)}-{entry.id[:8]}.md"
        target = target_dir / filename
        storage.atomic_write_text(target, storage.render_note_md(entry, note))
        return target

    def export_snapshot(self, dest_dir: Path | None = None) -> Path:
        """导出全量快照（内联全部正文）。可指定外部目录用于分享给同学。"""
        notes = {
            entry.id: storage.read_note(self.layout, entry.id)
            for entry in self._entries
        }
        return storage.write_snapshot(
            self.layout, self._entries, notes, prefix="snapshot", dest_dir=dest_dir
        )

    # -- 导入 / 恢复 -----------------------------------------------------

    def preview_snapshot(self, snapshot_path: Path) -> tuple[list[MistakeEntry], list[str]]:
        """读取快照但不写入任何东西，返回（条目, 与本地 id 冲突的列表）。

        供界面在导入前做预览并让用户选冲突策略（见项目文档 2.1.4）。
        """
        entries, _notes = storage.read_snapshot(Path(snapshot_path))
        conflicts = [entry.id for entry in entries if self.find(entry.id) is not None]
        return entries, conflicts

    def import_snapshot(
        self, snapshot_path: Path, conflict: str = CONFLICT_SKIP
    ) -> ImportResult:
        """从快照恢复或导入他人分享的题解包。

        写入前会自动备份当前现场；任一条 id 非法则整份拒绝，不留下半个结果。
        """
        if conflict not in CONFLICT_MODES:
            raise ValidationError(
                f"未知的冲突处理方式：{conflict!r}，可选 {CONFLICT_MODES}"
            )

        entries, notes = storage.read_snapshot(Path(snapshot_path))
        if not entries:
            return ImportResult()

        conflicts = [
            entry.id for entry in entries if self.find(entry.id) is not None
        ]
        self._auto_backup_before_import()

        result = ImportResult(conflicts=conflicts)
        for entry, note in ((e, notes.get(e.id, Note())) for e in entries):
            existing = self.find(entry.id)
            if existing is not None:
                if conflict == CONFLICT_SKIP:
                    result.skipped += 1
                    continue
                if conflict == CONFLICT_OVERWRITE:
                    self._entries = [
                        item for item in self._entries if item.id != entry.id
                    ]
                    self._entries.append(entry)
                    storage.write_note(self.layout, entry, note)
                    result.overwritten += 1
                    continue
                # CONFLICT_COPY：保留自己的，把对方的收成新条目
                entry = replace(entry, id=storage.new_id())
                result.copied += 1
            else:
                result.added += 1

            self._entries.append(entry)
            storage.write_note(self.layout, entry, note)

        self.save()
        return result

    def _auto_backup_before_import(self) -> None:
        """导入前把现场整体存一份，并轮转索引备份。"""
        storage.backup_index(self.layout)
        notes = {
            entry.id: storage.read_note(self.layout, entry.id)
            for entry in self._entries
        }
        storage.write_snapshot(
            self.layout, self._entries, notes, prefix="auto-preimport"
        )

    # -- 一致性 ----------------------------------------------------------

    def consistency(self) -> storage.ConsistencyReport:
        return storage.consistency_check(self.layout, self._entries)

    # -- 内部 ------------------------------------------------------------

    def _day(self, day: date | None) -> date:
        return self._today_fn() if day is None else day


def _normalize_tags(tags: list[str] | None) -> list[str]:
    """去空白、去重（忽略大小写）、保持首次出现的顺序。"""
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags or []:
        text = str(tag).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _safe_filename(title: str) -> str:
    """把标题变成安全的文件名（Windows 不允许 < > : " / \\ | ? *）。"""
    text = _INVALID_FILENAME_CHARS.sub("_", title or "").strip().rstrip(". ")
    text = re.sub(r"\s+", " ", text)
    if not text:
        text = "untitled"
    return text[:60]
