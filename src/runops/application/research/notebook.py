"""Application service for the append-only research notebook."""

from __future__ import annotations

import ctypes
import errno
import fcntl
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
_FileIdentity = tuple[int, int]

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
    source_identity: _FileIdentity | None = None


@dataclass(frozen=True)
class NoteArchivePlan:
    """Immutable, non-mutating plan for archiving old notebooks."""

    notes_dir: Path
    cutoff: date
    entries: tuple[NoteArchiveEntry, ...]
    root_identity: _FileIdentity | None = None


@dataclass(frozen=True)
class NoteArchiveResult:
    """Archive entries applied and skipped at execution time."""

    archived: tuple[NoteArchiveEntry, ...]
    skipped: tuple[NoteArchiveEntry, ...]


class NoteArchiveApplyError(NoteValidationError):
    """A runtime archive failure with an explicit partial-completion record."""

    def __init__(
        self,
        message: str,
        *,
        completed: NoteArchiveResult,
        failed_entry: NoteArchiveEntry,
        recovery_path: Path | None,
        cause: Exception,
    ) -> None:
        self.completed = completed
        self.failed_entry = failed_entry
        self.recovery_path = recovery_path
        self.cause = cause
        recovery = (
            f"; preserved recovery file: {recovery_path}"
            if recovery_path is not None
            else ""
        )
        super().__init__(f"{message}{recovery}")


class _ArchiveEntryError(Exception):
    """Internal per-entry failure before partial-result context is attached."""

    def __init__(
        self,
        message: str,
        *,
        cause: Exception,
        recovery_path: Path | None = None,
    ) -> None:
        self.message = message
        self.cause = cause
        self.recovery_path = recovery_path
        super().__init__(message)


@dataclass(frozen=True)
class _LoadedNote:
    """A regular daily note read through an anchored directory descriptor."""

    note_date: date
    path: Path
    text: str


def resolve_notes_dir(
    explicit: Path | None = None,
    *,
    cwd: Path | None = None,
) -> Path:
    """Resolve the notes directory from an override or project context."""
    if explicit is not None:
        return Path(os.path.abspath(explicit))
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
    notes_dir, root_fd = _open_notes_root(request.notes_dir, create=True)
    daily_name = f"{note_date.isoformat()}.md"
    path = notes_dir / daily_name
    entry_time = local_now.strftime("%H:%M")
    daily_flags = (
        os.O_WRONLY
        | os.O_APPEND
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )

    with ExitStack() as stack:
        stack.callback(os.close, root_fd)
        try:
            daily_fd = os.open(daily_name, daily_flags, 0o644, dir_fd=root_fd)
        except OSError as exc:
            raise NoteValidationError(f"unsafe daily notebook: {path}") from exc
        stack.callback(os.close, daily_fd)
        try:
            fcntl.flock(daily_fd, fcntl.LOCK_EX)
            daily_stat = os.fstat(daily_fd)
        except OSError as exc:
            raise NoteValidationError(f"could not lock daily notebook: {path}") from exc
        if not stat.S_ISREG(daily_stat.st_mode):
            raise NoteValidationError(f"daily notebook is not a regular file: {path}")
        if daily_stat.st_nlink != 1:
            raise NoteValidationError(
                f"daily notebook is not a regular single-link file: {path}"
            )

        created = daily_stat.st_size == 0
        header = f"# {note_date.isoformat()} — lab notebook\n\n" if created else ""
        entry = f"## {entry_time} {title}\n\n{body.rstrip()}\n\n"
        payload = (header + entry).encode("utf-8")
        try:
            _write_all(daily_fd, payload)
        except OSError as exc:
            raise NoteValidationError(
                f"could not append daily notebook: {path}: {exc}"
            ) from exc

    return NoteAppendResult(
        path=path,
        note_date=note_date,
        entry_time=entry_time,
        created=created,
    )


def list_note_days(notes_dir: Path, *, count: int = 14) -> tuple[NoteDaySummary, ...]:
    """Load recent daily-note metadata from active and history directories."""
    root, root_fd = _open_notes_root(notes_dir)
    with ExitStack() as stack:
        stack.callback(os.close, root_fd)
        loaded = _load_note_documents(root, root_fd)
    summaries = tuple(
        NoteDaySummary(
            note_date=document.note_date,
            entry_count=sum(
                1 for line in document.text.splitlines() if line.startswith("## ")
            ),
            path=document.path,
        )
        for document in loaded
    )
    return summaries[:count] if count > 0 else summaries


def read_note(
    notes_dir: Path,
    selector: str | None = None,
    *,
    today: date,
) -> NoteDocument:
    """Read today's, the latest, or an explicitly dated notebook."""
    root, root_fd = _open_notes_root(notes_dir)
    with ExitStack() as stack:
        stack.callback(os.close, root_fd)
        loaded = _load_note_documents(root, root_fd)
    if selector is None or selector == "today":
        note_date = today
    elif selector == "latest":
        if not loaded:
            raise NoteNotFoundError()
        latest = loaded[0]
        return NoteDocument(
            note_date=latest.note_date,
            path=latest.path,
            text=latest.text,
        )
    else:
        note_date = _parse_required_note_date(selector)

    for document in loaded:
        if document.note_date == note_date:
            return NoteDocument(
                note_date=document.note_date,
                path=document.path,
                text=document.text,
            )
    raise NoteNotFoundError(note_date)


def plan_note_archive(
    notes_dir: Path,
    *,
    older_than: str,
    today: date,
) -> NoteArchivePlan:
    """Plan moves for root-level daily notes older than a positive duration."""
    days = _parse_older_than(older_than)
    try:
        cutoff = today - timedelta(days=days)
    except OverflowError as exc:
        raise NoteValidationError(
            "duration is out of range for notebook dates"
        ) from exc
    root, root_fd = _open_notes_root(notes_dir)

    entries: list[NoteArchiveEntry] = []
    with ExitStack() as stack:
        stack.callback(os.close, root_fd)
        root_identity = _identity(os.fstat(root_fd))
        try:
            names = sorted(os.listdir(root_fd))
        except OSError as exc:
            raise NoteValidationError(
                f"could not inspect notes directory: {root}"
            ) from exc
        for name in names:
            path = root / name
            parsed = _parse_note_date(path.stem)
            if path.suffix != ".md" or parsed is None or parsed >= cutoff:
                continue
            try:
                source_stat = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise NoteValidationError(
                    f"could not inspect archive source: {path}"
                ) from exc
            if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_nlink != 1:
                continue
            destination = _history_path_for(root, path)
            entries.append(
                NoteArchiveEntry(
                    source=path,
                    destination=destination,
                    destination_exists=os.path.lexists(destination),
                    source_identity=_identity(source_stat),
                )
            )
    return NoteArchivePlan(
        notes_dir=root,
        cutoff=cutoff,
        entries=tuple(entries),
        root_identity=root_identity,
    )


def apply_note_archive(plan: NoteArchivePlan) -> NoteArchiveResult:
    """Apply a plan through fixed directory handles without clobbering files."""
    archived: list[NoteArchiveEntry] = []
    skipped: list[NoteArchiveEntry] = []
    root = plan.notes_dir
    directory_flags = _directory_open_flags()
    try:
        root_fd = os.open(root, directory_flags)
    except OSError as exc:
        raise NoteValidationError(f"unsafe notes directory: {plan.notes_dir}") from exc

    with ExitStack() as stack:
        stack.callback(os.close, root_fd)
        _preflight_archive_plan(
            plan,
            root_fd,
            directory_flags=directory_flags,
        )
        for entry in plan.entries:
            try:
                archived_entry = _apply_archive_entry(
                    plan,
                    root_fd,
                    entry,
                    directory_flags=directory_flags,
                )
            except _ArchiveEntryError as failure:
                completed = NoteArchiveResult(
                    archived=tuple(archived),
                    skipped=tuple(skipped),
                )
                raise NoteArchiveApplyError(
                    failure.message,
                    completed=completed,
                    failed_entry=entry,
                    recovery_path=failure.recovery_path,
                    cause=failure.cause,
                ) from failure.cause
            if archived_entry:
                archived.append(entry)
            else:
                skipped.append(entry)
    return NoteArchiveResult(archived=tuple(archived), skipped=tuple(skipped))


def _apply_archive_entry(
    plan: NoteArchivePlan,
    root_fd: int,
    entry: NoteArchiveEntry,
    *,
    directory_flags: int,
) -> bool:
    """Apply one preflighted entry; return true when archived, false when skipped."""
    try:
        _verify_root_identity(plan, root_fd)
        source_stat = _stat_regular_source(root_fd, entry)
        _verify_source_identity(entry, source_stat)
    except (OSError, NoteValidationError) as exc:
        raise _ArchiveEntryError(
            f"archive entry became stale before staging: {entry.source}",
            cause=exc,
        ) from exc

    year = entry.source.stem[:4]
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

            if _name_exists(year_fd, entry.destination.name):
                return False

            staging_name = f".{entry.source.name}.archive-{secrets.token_hex(8)}.tmp"
            staging_path = plan.notes_dir / staging_name
            try:
                _rename_noreplace(
                    root_fd,
                    entry.source.name,
                    root_fd,
                    staging_name,
                )
            except (OSError, NoteValidationError) as exc:
                staging_presence = _name_presence(root_fd, staging_name)
                if staging_presence is not False:
                    raise _failure_after_restore(
                        root_fd,
                        recovery_fd=root_fd,
                        recovery_name=staging_name,
                        recovery_path=staging_path,
                        entry=entry,
                        cause=exc,
                    ) from exc
                if not _source_matches_planned_identity(root_fd, entry):
                    raise _ArchiveEntryError(
                        "notebook archive staging failed with an ambiguous source "
                        f"state: {entry.source}",
                        cause=exc,
                        recovery_path=staging_path,
                    ) from exc
                raise _ArchiveEntryError(
                    f"could not stage notebook archive: {entry.source}",
                    cause=exc,
                ) from exc

            # From this point until destination verification, every failure is
            # recovered from the known staging/destination location.
            recovery_fd = root_fd
            recovery_name = staging_name
            recovery_path = staging_path
            try:
                staged_stat = os.stat(
                    staging_name,
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
                _verify_source_identity(entry, staged_stat)
                try:
                    _rename_noreplace(
                        root_fd,
                        staging_name,
                        year_fd,
                        entry.destination.name,
                    )
                except FileExistsError as exc:
                    failure = _restore_recovery_file(
                        root_fd,
                        recovery_fd=root_fd,
                        recovery_name=staging_name,
                        recovery_path=staging_path,
                        entry=entry,
                        cause=exc,
                    )
                    if failure is not None:
                        raise failure from exc
                    return False

                recovery_fd = year_fd
                recovery_name = entry.destination.name
                recovery_path = entry.destination
                archived_stat = os.stat(
                    entry.destination.name,
                    dir_fd=year_fd,
                    follow_symlinks=False,
                )
                _verify_source_identity(entry, archived_stat)
            except _ArchiveEntryError:
                raise
            except (OSError, NoteValidationError) as exc:
                raise _failure_after_restore(
                    root_fd,
                    recovery_fd=recovery_fd,
                    recovery_name=recovery_name,
                    recovery_path=recovery_path,
                    entry=entry,
                    cause=exc,
                ) from exc
            except Exception as exc:
                raise _failure_after_restore(
                    root_fd,
                    recovery_fd=recovery_fd,
                    recovery_name=recovery_name,
                    recovery_path=recovery_path,
                    entry=entry,
                    cause=exc,
                ) from exc
    except _ArchiveEntryError:
        raise
    except (OSError, NoteValidationError) as exc:
        raise _ArchiveEntryError(
            f"could not prepare notebook archive destination: {entry.destination}",
            cause=exc,
        ) from exc
    return True


def _in_jst(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=JST)
    return value.astimezone(JST)


def _open_notes_root(notes_dir: Path, *, create: bool = False) -> tuple[Path, int]:
    """Open the notes root itself without following a final symlink."""
    root = Path(os.path.abspath(notes_dir))
    if create:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise NoteValidationError(f"unsafe notes directory: {notes_dir}") from exc
    try:
        root_fd = os.open(root, _directory_open_flags())
    except FileNotFoundError as exc:
        if not create:
            raise NoteDirectoryNotFoundError(
                f"notes directory not found: {notes_dir}"
            ) from exc
        raise NoteValidationError(f"unsafe notes directory: {notes_dir}") from exc
    except OSError as exc:
        raise NoteValidationError(f"unsafe notes directory: {notes_dir}") from exc
    return root, root_fd


def _load_note_documents(root: Path, root_fd: int) -> tuple[_LoadedNote, ...]:
    """Load active/history daily notes without traversing symlink components."""
    by_date: dict[date, _LoadedNote] = {}
    try:
        active_names = os.listdir(root_fd)
    except OSError as exc:
        raise NoteValidationError(f"could not inspect notes directory: {root}") from exc
    for name in active_names:
        note_date = _daily_note_date(name)
        if note_date is None:
            continue
        text = _read_regular_text_at(root_fd, name, root / name)
        if text is None:
            continue
        by_date[note_date] = _LoadedNote(
            note_date=note_date,
            path=root / name,
            text=text,
        )

    history_path = root / _HISTORY_DIR
    history_fd = _open_directory_at(root_fd, _HISTORY_DIR, history_path)
    if history_fd is not None:
        with ExitStack() as history_stack:
            history_stack.callback(os.close, history_fd)
            try:
                year_names = os.listdir(history_fd)
            except OSError as exc:
                raise NoteValidationError(
                    f"could not inspect notebook history: {history_path}: {exc}"
                ) from exc
            for year_name in year_names:
                year_path = history_path / year_name
                year_fd = _open_directory_at(history_fd, year_name, year_path)
                if year_fd is None:
                    continue
                with ExitStack() as year_stack:
                    year_stack.callback(os.close, year_fd)
                    try:
                        daily_names = os.listdir(year_fd)
                    except OSError as exc:
                        raise NoteValidationError(
                            f"could not inspect notebook history: {year_path}: {exc}"
                        ) from exc
                    for name in daily_names:
                        note_date = _daily_note_date(name)
                        if note_date is None or note_date in by_date:
                            continue
                        path = year_path / name
                        text = _read_regular_text_at(year_fd, name, path)
                        if text is None:
                            continue
                        by_date[note_date] = _LoadedNote(
                            note_date=note_date,
                            path=path,
                            text=text,
                        )

    return tuple(
        sorted(by_date.values(), key=lambda document: document.note_date, reverse=True)
    )


def _open_directory_at(parent_fd: int, name: str, path: Path) -> int | None:
    try:
        return os.open(name, _directory_open_flags(), dir_fd=parent_fd)
    except OSError as exc:
        if _is_skippable_notebook_node_error(exc):
            return None
        raise NoteValidationError(
            f"could not open notebook directory: {path}: {exc}"
        ) from exc


def _read_regular_text_at(directory_fd: int, name: str, path: Path) -> str | None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        daily_fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        if _is_skippable_notebook_node_error(exc):
            return None
        raise NoteValidationError(
            f"could not open daily notebook: {path}: {exc}"
        ) from exc
    with ExitStack() as stack:
        stack.callback(os.close, daily_fd)
        try:
            fcntl.flock(daily_fd, fcntl.LOCK_SH)
            daily_stat = os.fstat(daily_fd)
        except OSError as exc:
            raise NoteValidationError(
                f"could not inspect daily notebook: {path}: {exc}"
            ) from exc
        if not stat.S_ISREG(daily_stat.st_mode) or daily_stat.st_nlink != 1:
            return None
        chunks: list[bytes] = []
        try:
            while chunk := os.read(daily_fd, 64 * 1024):
                chunks.append(chunk)
        except OSError as exc:
            raise NoteValidationError(
                f"could not read daily notebook: {path}: {exc}"
            ) from exc
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NoteValidationError(
            f"daily notebook is not valid UTF-8: {path}: {exc}"
        ) from exc


def _is_skippable_notebook_node_error(exc: OSError) -> bool:
    return exc.errno in {
        errno.ENOENT,
        errno.ELOOP,
        errno.ENOTDIR,
        errno.ENXIO,
    }


def _write_all(descriptor: int, payload: bytes) -> None:
    written = 0
    while written < len(payload):
        try:
            count = os.write(descriptor, payload[written:])
        except InterruptedError:
            continue
        if count == 0:
            raise OSError(errno.EIO, "zero-byte write while appending notebook")
        written += count


def _daily_note_date(name: str) -> date | None:
    path = Path(name)
    if path.name != name or path.suffix != ".md":
        return None
    return _parse_note_date(path.stem)


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


def _history_path_for(notes_dir: Path, note_path: Path) -> Path:
    return notes_dir / _HISTORY_DIR / note_path.stem[:4] / note_path.name


def _validate_archive_entry(notes_dir: Path, entry: NoteArchiveEntry) -> None:
    root = Path(os.path.abspath(notes_dir))
    source = Path(os.path.abspath(entry.source))
    destination = Path(os.path.abspath(entry.destination))
    parsed = _parse_note_date(entry.source.stem)
    if parsed is None or source.parent != root:
        raise NoteValidationError(f"unsafe archive source: {entry.source}")
    expected = _history_path_for(root, source)
    if destination != expected or not destination.is_relative_to(root):
        raise NoteValidationError(f"unsafe archive destination: {entry.destination}")


def _directory_open_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    return flags | getattr(os, "O_NOFOLLOW", 0)


def _identity(value: os.stat_result) -> _FileIdentity:
    return (value.st_dev, value.st_ino)


def _verify_root_identity(plan: NoteArchivePlan, root_fd: int) -> None:
    if plan.root_identity is None:
        raise NoteValidationError("archive plan has no notes directory identity")
    try:
        opened_identity = _identity(os.fstat(root_fd))
        path_identity = _identity(os.stat(plan.notes_dir, follow_symlinks=False))
    except OSError as exc:
        raise NoteValidationError(f"stale notes directory: {plan.notes_dir}") from exc
    if opened_identity != plan.root_identity or path_identity != plan.root_identity:
        raise NoteValidationError(f"stale notes directory: {plan.notes_dir}")


def _verify_source_identity(
    entry: NoteArchiveEntry,
    source_stat: os.stat_result,
) -> None:
    if entry.source_identity is None:
        raise NoteValidationError(
            f"archive plan has no source identity: {entry.source}"
        )
    if _identity(source_stat) != entry.source_identity:
        raise NoteValidationError(f"stale archive source: {entry.source}")


def _preflight_archive_plan(
    plan: NoteArchivePlan,
    root_fd: int,
    *,
    directory_flags: int,
) -> None:
    """Validate the complete plan before the first filesystem mutation."""
    _verify_root_identity(plan, root_fd)
    seen_sources: set[str] = set()
    seen_destinations: set[Path] = set()
    years: set[str] = set()
    for entry in plan.entries:
        _validate_archive_entry(plan.notes_dir, entry)
        parsed = _parse_note_date(entry.source.stem)
        if parsed is None or parsed >= plan.cutoff:
            raise NoteValidationError(f"unsafe archive source: {entry.source}")
        if entry.source.name in seen_sources or entry.destination in seen_destinations:
            raise NoteValidationError(f"duplicate archive entry: {entry.source}")
        seen_sources.add(entry.source.name)
        seen_destinations.add(entry.destination)
        source_stat = _stat_regular_source(root_fd, entry)
        _verify_source_identity(entry, source_stat)
        years.add(entry.source.stem[:4])

    _preflight_archive_directories(
        root_fd,
        years,
        directory_flags=directory_flags,
    )


def _preflight_archive_directories(
    root_fd: int,
    years: set[str],
    *,
    directory_flags: int,
) -> None:
    try:
        history_fd = os.open(_HISTORY_DIR, directory_flags, dir_fd=root_fd)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise NoteValidationError(f"unsafe archive directory: {_HISTORY_DIR}") from exc

    with ExitStack() as stack:
        stack.callback(os.close, history_fd)
        for year in sorted(years):
            try:
                year_fd = os.open(year, directory_flags, dir_fd=history_fd)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise NoteValidationError(f"unsafe archive directory: {year}") from exc
            os.close(year_fd)


def _stat_regular_source(root_fd: int, entry: NoteArchiveEntry) -> os.stat_result:
    try:
        source_stat = os.stat(
            entry.source.name,
            dir_fd=root_fd,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise NoteValidationError(f"unsafe archive source: {entry.source}") from exc
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_nlink != 1:
        raise NoteValidationError(f"unsafe archive source: {entry.source}")
    return source_stat


def _name_exists(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _name_presence(directory_fd: int, name: str) -> bool | None:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError:
        return None
    return True


def _source_matches_planned_identity(
    root_fd: int,
    entry: NoteArchiveEntry,
) -> bool:
    try:
        source_stat = _stat_regular_source(root_fd, entry)
        _verify_source_identity(entry, source_stat)
    except NoteValidationError:
        return False
    return True


def _failure_after_restore(
    root_fd: int,
    *,
    recovery_fd: int,
    recovery_name: str,
    recovery_path: Path,
    entry: NoteArchiveEntry,
    cause: Exception,
) -> _ArchiveEntryError:
    failure = _restore_recovery_file(
        root_fd,
        recovery_fd=recovery_fd,
        recovery_name=recovery_name,
        recovery_path=recovery_path,
        entry=entry,
        cause=cause,
    )
    if failure is not None:
        return failure
    return _ArchiveEntryError(
        f"notebook archive failed after staging; source restored: {entry.source}",
        cause=cause,
    )


def _restore_recovery_file(
    root_fd: int,
    *,
    recovery_fd: int,
    recovery_name: str,
    recovery_path: Path,
    entry: NoteArchiveEntry,
    cause: Exception,
) -> _ArchiveEntryError | None:
    try:
        _renameat2_noreplace(
            recovery_fd,
            recovery_name,
            root_fd,
            entry.source.name,
        )
    except FileNotFoundError as restore_exc:
        if _source_matches_planned_identity(root_fd, entry):
            return None
        return _ArchiveEntryError(
            "notebook archive failed and no verified recovery file was found: "
            f"{entry.source} ({restore_exc})",
            cause=cause,
        )
    except OSError as restore_exc:
        if _is_rename_noreplace_unsupported(restore_exc):
            return _fallback_restore_retaining_recovery(
                root_fd,
                recovery_fd=recovery_fd,
                recovery_name=recovery_name,
                recovery_path=recovery_path,
                entry=entry,
                cause=cause,
            )
        return _ArchiveEntryError(
            "notebook archive failed and the original could not be restored: "
            f"{entry.source} ({restore_exc})",
            cause=cause,
            recovery_path=recovery_path,
        )
    return None


def _fallback_restore_retaining_recovery(
    root_fd: int,
    *,
    recovery_fd: int,
    recovery_name: str,
    recovery_path: Path,
    entry: NoteArchiveEntry,
    cause: Exception,
) -> _ArchiveEntryError:
    try:
        os.link(
            recovery_name,
            entry.source.name,
            src_dir_fd=recovery_fd,
            dst_dir_fd=root_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError as restore_exc:
        if _source_matches_planned_identity(root_fd, entry):
            return _ArchiveEntryError(
                f"notebook archive failed; source remained intact: {entry.source}",
                cause=cause,
            )
        return _ArchiveEntryError(
            "notebook archive failed and no verified recovery file was found: "
            f"{entry.source} ({restore_exc})",
            cause=cause,
        )
    except OSError as restore_exc:
        return _ArchiveEntryError(
            "notebook archive failed; candidate retained as a recovery file: "
            f"{recovery_path} ({restore_exc})",
            cause=cause,
            recovery_path=recovery_path,
        )
    return _ArchiveEntryError(
        "notebook archive failed; source was relinked while the recovery "
        f"file was retained: {recovery_path}",
        cause=cause,
        recovery_path=recovery_path,
    )


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
    try:
        _renameat2_noreplace(
            source_fd,
            source_name,
            destination_fd,
            destination_name,
        )
        return
    except OSError as exc:
        if not _is_rename_noreplace_unsupported(exc):
            raise

    _fallback_move_noreplace(
        source_fd,
        source_name,
        destination_fd,
        destination_name,
    )


def _is_rename_noreplace_unsupported(exc: OSError) -> bool:
    unsupported = {
        errno.EINVAL,
        errno.ENOSYS,
        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
        errno.EOPNOTSUPP,
    }
    return exc.errno in unsupported


def _renameat2_noreplace(
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


def _fallback_move_noreplace(
    source_fd: int,
    source_name: str,
    destination_fd: int,
    destination_name: str,
) -> None:
    private_prefix = f".{source_name}.archive-"
    private_staging = (
        source_fd == destination_fd
        and destination_name.startswith(private_prefix)
        and destination_name.endswith(".tmp")
    )
    if private_staging:
        _fallback_private_stage_noreplace(
            source_fd,
            source_name,
            destination_fd,
            destination_name,
        )
        return

    os.link(
        source_name,
        destination_name,
        src_dir_fd=source_fd,
        dst_dir_fd=destination_fd,
        follow_symlinks=False,
    )
    try:
        os.unlink(source_name, dir_fd=source_fd)
    except OSError as exc:
        try:
            os.unlink(destination_name, dir_fd=destination_fd)
        except OSError as rollback_exc:
            raise NoteValidationError(
                "archive fallback linked its destination but could not roll back "
                f"after preserving source {source_name}: {destination_name}"
            ) from rollback_exc
        raise exc


def _fallback_private_stage_noreplace(
    source_fd: int,
    source_name: str,
    destination_fd: int,
    destination_name: str,
) -> None:
    """Stage atomically after proving hardlinks work without unlinking source."""
    os.link(
        source_name,
        destination_name,
        src_dir_fd=source_fd,
        dst_dir_fd=destination_fd,
        follow_symlinks=False,
    )
    try:
        os.unlink(destination_name, dir_fd=destination_fd)
    except OSError as exc:
        raise NoteValidationError(
            "archive hardlink capability probe could not be removed: "
            f"{destination_name}"
        ) from exc

    placeholder_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    placeholder_flags |= getattr(os, "O_NOFOLLOW", 0)
    placeholder_fd = os.open(
        destination_name,
        placeholder_flags,
        0o600,
        dir_fd=destination_fd,
    )
    try:
        try:
            placeholder_identity = _identity(os.fstat(placeholder_fd))
        finally:
            os.close(placeholder_fd)
    except OSError:
        try:
            os.unlink(destination_name, dir_fd=destination_fd)
        except FileNotFoundError:
            pass
        except OSError as cleanup_exc:
            raise NoteValidationError(
                "archive private placeholder could not be cleaned up: "
                f"{destination_name}"
            ) from cleanup_exc
        raise

    try:
        os.rename(
            source_name,
            destination_name,
            src_dir_fd=source_fd,
            dst_dir_fd=destination_fd,
        )
    except OSError:
        try:
            destination_stat = os.stat(
                destination_name,
                dir_fd=destination_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        except OSError:
            # The rename result is ambiguous; preserve the candidate path so
            # the outer recovery state machine can inspect or restore it.
            pass
        else:
            if _identity(destination_stat) == placeholder_identity:
                os.unlink(destination_name, dir_fd=destination_fd)
        raise


__all__ = [
    "JST",
    "NoteAppendRequest",
    "NoteAppendResult",
    "NoteArchiveApplyError",
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
