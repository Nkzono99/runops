"""Daily notebook resolution, append, list, and read operations."""

from __future__ import annotations

import errno
import fcntl
import os
import stat
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root

from .models import (
    NoteAppendRequest,
    NoteAppendResult,
    NoteDaySummary,
    NoteDirectoryNotFoundError,
    NoteDocument,
    NoteNotFoundError,
    NoteValidationError,
    _LoadedNote,
)

JST = timezone(timedelta(hours=9))
_HISTORY_DIR = "history"
_NOTE_DATE_FORMAT = "%Y-%m-%d"


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


def _directory_open_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    return flags | getattr(os, "O_NOFOLLOW", 0)
