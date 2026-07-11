"""Application services for the append-only research notebook."""

import errno  # noqa: F401 - compatibility patch point
import os  # noqa: F401 - compatibility patch point

from . import archive as _archive
from .access import JST, append_note, list_note_days, read_note, resolve_notes_dir
from .archive import plan_note_archive
from .models import (
    NoteAppendRequest,
    NoteAppendResult,
    NoteArchiveApplyError,
    NoteArchiveEntry,
    NoteArchivePlan,
    NoteArchiveResult,
    NoteDaySummary,
    NoteDirectoryNotFoundError,
    NoteDocument,
    NoteNotFoundError,
    NoteValidationError,
)

# Compatibility patch points used by the archive failure-injection tests.  The
# facade wrapper copies them into the effectful capability immediately before
# execution, so the public import path remains stable after the split.
_rename_noreplace = _archive._rename_noreplace
_renameat2_noreplace = _archive._renameat2_noreplace
_validate_archive_entry = _archive._validate_archive_entry


def apply_note_archive(plan: NoteArchivePlan) -> NoteArchiveResult:
    """Apply an archive plan through the secure archive capability."""
    _archive._rename_noreplace = _rename_noreplace
    _archive._renameat2_noreplace = _renameat2_noreplace
    _archive._validate_archive_entry = _validate_archive_entry
    return _archive.apply_note_archive(plan)


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
