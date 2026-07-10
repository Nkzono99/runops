"""Tests for the research notebook application service."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from runops.application.research.notebook import (
    NoteAppendRequest,
    NoteArchiveEntry,
    NoteArchivePlan,
    NoteValidationError,
    append_note,
    apply_note_archive,
    list_note_days,
    plan_note_archive,
    read_note,
)


def _write_note(path: Path, *entries: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"## 09:00 {entry}\n\nbody\n\n" for entry in entries)
    path.write_text(f"# {path.stem} — lab notebook\n\n{body}", encoding="utf-8")


def test_append_note_selects_jst_day_and_preserves_format(tmp_path: Path) -> None:
    notes_dir = tmp_path / "notes"
    request = NoteAppendRequest(notes_dir=notes_dir, title="night run", body="stable")

    result = append_note(
        request,
        now=datetime(2026, 4, 8, 16, 32, tzinfo=timezone.utc),
    )

    assert result.path == notes_dir / "2026-04-09.md"
    assert result.created is True
    assert result.note_date == date(2026, 4, 9)
    assert result.path.read_text(encoding="utf-8") == (
        "# 2026-04-09 — lab notebook\n\n## 01:32 night run\n\nstable\n\n"
    )


def test_append_note_uses_explicit_date_but_injected_timestamp(tmp_path: Path) -> None:
    notes_dir = tmp_path / "notes"
    request = NoteAppendRequest(
        notes_dir=notes_dir,
        title="catch up",
        body="observation",
        note_date=date(2026, 4, 7),
    )

    result = append_note(
        request,
        now=datetime(2026, 4, 9, 3, 5, tzinfo=timezone.utc),
    )

    assert result.path.name == "2026-04-07.md"
    assert "## 12:05 catch up" in result.path.read_text(encoding="utf-8")


def test_list_note_days_merges_active_and_history_with_active_winning(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    active = notes_dir / "2026-04-08.md"
    archived_duplicate = notes_dir / "history" / "2026" / "2026-04-08.md"
    archived = notes_dir / "history" / "2026" / "2026-04-06.md"
    _write_note(active, "one", "two")
    _write_note(archived_duplicate, "stale")
    _write_note(archived, "old")

    summaries = list_note_days(notes_dir, count=0)

    assert [(item.note_date.isoformat(), item.entry_count) for item in summaries] == [
        ("2026-04-08", 2),
        ("2026-04-06", 1),
    ]
    assert summaries[0].path == active


def test_read_note_supports_today_latest_and_explicit_history_date(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    _write_note(notes_dir / "2026-04-08.md", "today")
    _write_note(notes_dir / "history" / "2026" / "2026-04-06.md", "history")

    today = read_note(notes_dir, "today", today=date(2026, 4, 8))
    latest = read_note(notes_dir, "latest", today=date(2026, 4, 9))
    historical = read_note(notes_dir, "2026-04-06", today=date(2026, 4, 9))

    assert today.path.name == "2026-04-08.md"
    assert latest.path == today.path
    assert historical.path.parent.name == "2026"
    assert "history" in historical.text


def test_archive_plan_is_non_mutating_and_apply_moves_only_ready_entries(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    old = notes_dir / "2026-04-01.md"
    blocked = notes_dir / "2026-04-02.md"
    recent = notes_dir / "2026-04-08.md"
    _write_note(old, "old")
    _write_note(blocked, "blocked")
    _write_note(recent, "recent")
    blocked_destination = notes_dir / "history" / "2026" / blocked.name
    _write_note(blocked_destination, "existing")

    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))

    assert [entry.source.name for entry in plan.entries] == [
        "2026-04-01.md",
        "2026-04-02.md",
    ]
    assert [entry.destination_exists for entry in plan.entries] == [False, True]
    assert old.exists() and blocked.exists() and recent.exists()

    result = apply_note_archive(plan)

    assert [entry.source.name for entry in result.archived] == ["2026-04-01.md"]
    assert [entry.source.name for entry in result.skipped] == ["2026-04-02.md"]
    assert not old.exists()
    assert (notes_dir / "history" / "2026" / old.name).is_file()
    assert blocked.is_file()
    assert recent.is_file()


def test_rejects_date_path_traversal_and_tampered_archive_plan(tmp_path: Path) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()

    with pytest.raises(NoteValidationError):
        read_note(notes_dir, "../secret", today=date(2026, 4, 10))

    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    tampered = NoteArchivePlan(
        notes_dir=notes_dir,
        cutoff=date(2026, 4, 3),
        entries=(
            NoteArchiveEntry(
                source=outside,
                destination=notes_dir / "history" / "2026" / outside.name,
                destination_exists=False,
            ),
        ),
    )

    with pytest.raises(NoteValidationError):
        apply_note_archive(tampered)
    assert outside.is_file()
