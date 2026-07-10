"""Application service for the append-only research notebook."""

from __future__ import annotations

import ctypes
import errno
import os
import secrets
import stat
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root

JST = timezone(timedelta(hours=9))
_HISTORY_DIR = "history"
_NOTE_DATE_FORMAT = "%Y-%m-%d"
_RENAME_NOREPLACE = 1

_LIBC = ctypes.CDLL(None, use_errno=True)
_RENAMEAT2 = getattr(_LIBC, "renameat2", None)
if _RENAMEAT2 is not None:
    _RENAMEAT2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    _RENAMEAT2.restype = ctypes.c_int


class NoteError(Exception):
    """Base error for notebook operations."""


class NoteValidationError(NoteError, ValueError):
    """A notebook request contains an invalid value or unsafe path."""


class NoteDirectoryNotFoundError(NoteError):
    """The selected notes directory does not exist."""


class NoteNotFoundError(NoteError):
    """A requested daily notebook does not exist."""

    def __init__(self, note_date: date | None = None) -> None:
        self.note_date = note_date
        super().__init__(
            "no notes yet"
            if note_date is None
            else f"no notes for {note_date.isoformat()}"
        )


@dataclass(frozen=True)
class NoteAppendRequest:
    """Values needed to append one notebook entry."""

    notes_dir: Path
    title: str
    body: str
    note_date: date | str | None = None


@dataclass(frozen=True)
class NoteAppendResult:
    """Description of an appended notebook entry."""

    path: Path
    note_date: date
    entry_time: str
    created: bool


@dataclass(frozen=True)
class NoteDaySummary:
    """One notebook day shown by the list operation."""

    note_date: date
    entry_count: int
    path: Path


@dataclass(frozen=True)
class NoteDocument:
    """One loaded daily notebook."""

    note_date: date
    path: Path
    text: str


@dataclass(frozen=True)
class NoteArchiveEntry:
    """One source/destination pair in an archive plan."""

    source: Path
    destination: Path
    destination_exists: bool


@dataclass(frozen=True)
class NoteArchivePlan:
    """Immutable, non-mutating plan for archiving old notebooks."""

    notes_dir: Path
    cutoff: date
    entries: tuple[NoteArchiveEntry, ...]


@dataclass(frozen=True)
class NoteArchiveResult:
    """Archive entries applied and skipped at execution time."""

    archived: tuple[NoteArchiveEntry, ...]
    skipped: tuple[NoteArchiveEntry, ...]


def resolve_notes_dir(
    explicit: Path | None = None,
    *,
    cwd: Path | None = None,
) -> Path:
    """Resolve the notes directory from an override or project context."""
    if explicit is not None:
        return explicit.resolve()
    start = (cwd or Path.cwd()).resolve()
    try:
        root = find_project_root(start)
    except SimctlError:
        root = start
    return root / "notes"


def append_note(request: NoteAppendRequest, *, now: datetime) -> NoteAppendResult:
    """Append one timestamped entry, creating the daily header when needed."""
    title = request.title.strip()
    if not title:
        raise NoteValidationError("title must be non-empty")
    body = request.body.strip()
    if not body:
        raise NoteValidationError("body must be non-empty")

    local_now = _in_jst(now)
    if isinstance(request.note_date, str):
        note_date = _parse_required_note_date(request.note_date)
    else:
        note_date = request.note_date or local_now.date()
    notes_dir = request.notes_dir
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = notes_dir / f"{note_date.isoformat()}.md"
    created = not path.exists()

    with path.open("a", encoding="utf-8") as stream:
        if created:
            stream.write(f"# {note_date.isoformat()} — lab notebook\n\n")
        stream.write(f"## {local_now.strftime('%H:%M')} {title}\n\n")
        stream.write(body.rstrip() + "\n\n")

    return NoteAppendResult(
        path=path,
        note_date=note_date,
        entry_time=local_now.strftime("%H:%M"),
        created=created,
    )


def list_note_days(notes_dir: Path, *, count: int = 14) -> tuple[NoteDaySummary, ...]:
    """Load recent daily-note metadata from active and history directories."""
    _require_notes_dir(notes_dir)
    summaries: list[NoteDaySummary] = []
    for path in _iter_note_files(notes_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parsed = _parse_note_date(path.stem)
        if parsed is None:  # Defensive: _iter_note_files already filters this.
            continue
        summaries.append(
            NoteDaySummary(
                note_date=parsed,
                entry_count=sum(
                    1 for line in text.splitlines() if line.startswith("## ")
                ),
                path=path,
            )
        )
        if count > 0 and len(summaries) >= count:
            break
    return tuple(summaries)


def read_note(
    notes_dir: Path,
    selector: str | None = None,
    *,
    today: date,
) -> NoteDocument:
    """Read today's, the latest, or an explicitly dated notebook."""
    _require_notes_dir(notes_dir)
    if selector is None or selector == "today":
        note_date = today
        path = _find_note_file(notes_dir, note_date)
    elif selector == "latest":
        files = _iter_note_files(notes_dir)
        if not files:
            raise NoteNotFoundError()
        path = files[0]
        parsed = _parse_note_date(path.stem)
        if parsed is None:  # Defensive: _iter_note_files already filters this.
            raise NoteValidationError(f"invalid notebook path: {path}")
        note_date = parsed
    else:
        note_date = _parse_required_note_date(selector)
        path = _find_note_file(notes_dir, note_date)

    if path is None or not path.is_file():
        raise NoteNotFoundError(note_date)
    return NoteDocument(
        note_date=note_date,
        path=path,
        text=path.read_text(encoding="utf-8"),
    )


def plan_note_archive(
    notes_dir: Path,
    *,
    older_than: str,
    today: date,
) -> NoteArchivePlan:
    """Plan moves for root-level daily notes older than a positive duration."""
    days = _parse_older_than(older_than)
    _require_notes_dir(notes_dir)
    cutoff = today - timedelta(days=days)
    entries: list[NoteArchiveEntry] = []
    for path in sorted(notes_dir.glob("*.md"), key=lambda item: item.stem):
        parsed = _parse_note_date(path.stem)
        if parsed is None or parsed >= cutoff:
            continue
        destination = _history_path_for(notes_dir, path)
        entries.append(
            NoteArchiveEntry(
                source=path,
                destination=destination,
                destination_exists=destination.exists(),
            )
        )
    return NoteArchivePlan(
        notes_dir=notes_dir,
        cutoff=cutoff,
        entries=tuple(entries),
    )


def apply_note_archive(plan: NoteArchivePlan) -> NoteArchiveResult:
    """Apply a plan through fixed directory handles without clobbering files."""
    archived: list[NoteArchiveEntry] = []
    skipped: list[NoteArchiveEntry] = []
    root = plan.notes_dir.resolve()
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(root, directory_flags)
    except OSError as exc:
        raise NoteValidationError(f"unsafe notes directory: {plan.notes_dir}") from exc

    with ExitStack() as stack:
        stack.callback(os.close, root_fd)
        for entry in plan.entries:
            _validate_archive_entry(plan.notes_dir, entry)
            source_stat = _stat_regular_source(root_fd, entry)
            staging_name = f".{entry.source.name}.archive-{secrets.token_hex(8)}.tmp"
            try:
                _rename_noreplace(
                    root_fd,
                    entry.source.name,
                    root_fd,
                    staging_name,
                )
            except OSError as exc:
                raise NoteValidationError(
                    f"could not stage notebook archive: {entry.source}"
                ) from exc

            staged_stat = os.stat(
                staging_name,
                dir_fd=root_fd,
                follow_symlinks=False,
            )
            if (
                staged_stat.st_dev != source_stat.st_dev
                or staged_stat.st_ino != source_stat.st_ino
            ):
                _restore_staged_source(
                    root_fd,
                    staging_name=staging_name,
                    source_name=entry.source.name,
                    entry=entry,
                )
                raise NoteValidationError(
                    f"archive source changed while staging: {entry.source}"
                )

            year = entry.source.stem[:4]
            staged = True
            try:
                with ExitStack() as entry_stack:
                    history_fd = _open_or_create_directory(
                        root_fd,
                        _HISTORY_DIR,
                        directory_flags=directory_flags,
                    )
                    entry_stack.callback(os.close, history_fd)
                    year_fd = _open_or_create_directory(
                        history_fd,
                        year,
                        directory_flags=directory_flags,
                    )
                    entry_stack.callback(os.close, year_fd)
                    try:
                        _rename_noreplace(
                            root_fd,
                            staging_name,
                            year_fd,
                            entry.destination.name,
                        )
                    except FileExistsError:
                        _restore_staged_source(
                            root_fd,
                            staging_name=staging_name,
                            source_name=entry.source.name,
                            entry=entry,
                        )
                        staged = False
                        skipped.append(entry)
                        continue
                    staged = False
                    archived_stat = os.stat(
                        entry.destination.name,
                        dir_fd=year_fd,
                        follow_symlinks=False,
                    )
                    if (
                        archived_stat.st_dev != source_stat.st_dev
                        or archived_stat.st_ino != source_stat.st_ino
                    ):
                        raise NoteValidationError(
                            "archive destination changed unexpectedly: "
                            f"{entry.destination}"
                        )
            except Exception as exc:
                if staged:
                    try:
                        _restore_staged_source(
                            root_fd,
                            staging_name=staging_name,
                            source_name=entry.source.name,
                            entry=entry,
                        )
                    except NoteValidationError as restore_exc:
                        raise restore_exc from exc
                raise
            archived.append(entry)
    return NoteArchiveResult(archived=tuple(archived), skipped=tuple(skipped))


def _in_jst(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=JST)
    return value.astimezone(JST)


def _require_notes_dir(notes_dir: Path) -> None:
    if not notes_dir.is_dir():
        raise NoteDirectoryNotFoundError(f"notes directory not found: {notes_dir}")


def _parse_note_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, _NOTE_DATE_FORMAT).date()
    except ValueError:
        return None


def _parse_required_note_date(value: str) -> date:
    parsed = _parse_note_date(value)
    if parsed is None:
        raise NoteValidationError(f"invalid date '{value}'")
    return parsed


def _parse_older_than(value: str) -> int:
    raw = value.strip().lower()
    if raw.endswith("d"):
        raw = raw[:-1]
    try:
        days = int(raw)
    except ValueError as exc:
        raise NoteValidationError(
            "expected a duration like '7d' or a positive day count"
        ) from exc
    if days <= 0:
        raise NoteValidationError("duration must be positive")
    return days


def _is_daily_note(path: Path) -> bool:
    return path.suffix == ".md" and _parse_note_date(path.stem) is not None


def _iter_note_files(notes_dir: Path) -> list[Path]:
    by_date: dict[str, Path] = {}
    for path in sorted(
        notes_dir.glob("*.md"), key=lambda item: item.stem, reverse=True
    ):
        if _is_daily_note(path):
            by_date[path.stem] = path

    history_dir = notes_dir / _HISTORY_DIR
    if history_dir.is_dir():
        for path in sorted(
            history_dir.rglob("*.md"),
            key=lambda item: item.stem,
            reverse=True,
        ):
            if _is_daily_note(path):
                by_date.setdefault(path.stem, path)

    return sorted(by_date.values(), key=lambda item: item.stem, reverse=True)


def _find_note_file(notes_dir: Path, note_date: date) -> Path | None:
    active = notes_dir / f"{note_date.isoformat()}.md"
    if active.is_file():
        return active
    for path in _iter_note_files(notes_dir):
        if path.stem == note_date.isoformat():
            return path
    return None


def _history_path_for(notes_dir: Path, note_path: Path) -> Path:
    return notes_dir / _HISTORY_DIR / note_path.stem[:4] / note_path.name


def _validate_archive_entry(notes_dir: Path, entry: NoteArchiveEntry) -> None:
    root = notes_dir.resolve()
    source = entry.source.resolve()
    destination = entry.destination.resolve()
    parsed = _parse_note_date(entry.source.stem)
    if parsed is None or source.parent != root:
        raise NoteValidationError(f"unsafe archive source: {entry.source}")
    expected = _history_path_for(notes_dir, entry.source).resolve()
    if destination != expected or not destination.is_relative_to(root):
        raise NoteValidationError(f"unsafe archive destination: {entry.destination}")


def _stat_regular_source(root_fd: int, entry: NoteArchiveEntry) -> os.stat_result:
    try:
        source_stat = os.stat(
            entry.source.name,
            dir_fd=root_fd,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise NoteValidationError(f"unsafe archive source: {entry.source}") from exc
    if not stat.S_ISREG(source_stat.st_mode):
        raise NoteValidationError(f"unsafe archive source: {entry.source}")
    return source_stat


def _open_or_create_directory(
    parent_fd: int,
    name: str,
    *,
    directory_flags: int,
) -> int:
    try:
        os.mkdir(name, dir_fd=parent_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise NoteValidationError(
            f"could not create archive directory: {name}"
        ) from exc
    try:
        return os.open(name, directory_flags, dir_fd=parent_fd)
    except OSError as exc:
        raise NoteValidationError(f"unsafe archive directory: {name}") from exc


def _rename_noreplace(
    source_fd: int,
    source_name: str,
    destination_fd: int,
    destination_name: str,
) -> None:
    if _RENAMEAT2 is None:
        raise OSError(errno.ENOSYS, "renameat2 is unavailable")
    result = _RENAMEAT2(
        source_fd,
        os.fsencode(source_name),
        destination_fd,
        os.fsencode(destination_name),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(
            error_number,
            os.strerror(error_number),
            destination_name,
        )
    raise OSError(error_number, os.strerror(error_number), destination_name)


def _restore_staged_source(
    root_fd: int,
    *,
    staging_name: str,
    source_name: str,
    entry: NoteArchiveEntry,
) -> None:
    try:
        _rename_noreplace(
            root_fd,
            staging_name,
            root_fd,
            source_name,
        )
    except FileExistsError as exc:
        raise NoteValidationError(
            "archive source changed; original preserved as recovery file "
            f"{entry.source.parent / staging_name}"
        ) from exc
    except OSError as exc:
        raise NoteValidationError(
            f"could not restore staged archive source: {entry.source}"
        ) from exc


__all__ = [
    "JST",
    "NoteAppendRequest",
    "NoteAppendResult",
    "NoteArchiveEntry",
    "NoteArchivePlan",
    "NoteArchiveResult",
    "NoteDaySummary",
    "NoteDirectoryNotFoundError",
    "NoteDocument",
    "NoteNotFoundError",
    "NoteValidationError",
    "append_note",
    "apply_note_archive",
    "list_note_days",
    "plan_note_archive",
    "read_note",
    "resolve_notes_dir",
]
