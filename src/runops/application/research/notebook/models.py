"""Notebook value objects and errors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

_FileIdentity = tuple[int, int]


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
