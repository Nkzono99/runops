"""Tests for the research notebook application service."""

from __future__ import annotations

import errno
import os
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from runops.application.research import notebook as notebook_module
from runops.application.research.notebook import (
    NoteAppendRequest,
    NoteArchiveApplyError,
    NoteArchiveEntry,
    NoteArchivePlan,
    NoteNotFoundError,
    NoteValidationError,
    append_note,
    apply_note_archive,
    list_note_days,
    plan_note_archive,
    read_note,
    resolve_notes_dir,
)


def _write_note(path: Path, *entries: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"## 09:00 {entry}\n\nbody\n\n" for entry in entries)
    path.write_text(f"# {path.stem} — lab notebook\n\n{body}", encoding="utf-8")


def _assert_archive_apply_error(
    error: BaseException,
    *,
    archived: tuple[NoteArchiveEntry, ...] = (),
    skipped: tuple[NoteArchiveEntry, ...] = (),
    failed_entry: NoteArchiveEntry,
    recovery_path: Path | None,
) -> NoteArchiveApplyError:
    assert isinstance(error, NoteArchiveApplyError)
    assert error.completed.archived == archived
    assert error.completed.skipped == skipped
    assert error.failed_entry == failed_entry
    assert error.recovery_path == recovery_path
    assert isinstance(error.cause, Exception)
    return error


def test_resolve_notes_dir_preserves_explicit_symlink_for_root_validation(
    tmp_path: Path,
) -> None:
    actual_notes = tmp_path / "actual-notes"
    actual_notes.mkdir()
    notes_link = tmp_path / "notes"
    notes_link.symlink_to(actual_notes, target_is_directory=True)

    resolved = resolve_notes_dir(notes_link)

    assert resolved == notes_link.absolute()


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


def test_append_note_rejects_daily_symlink_without_mutating_target(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    (notes_dir / "2026-04-08.md").symlink_to(outside)
    request = NoteAppendRequest(
        notes_dir=notes_dir,
        title="must stay local",
        body="entry",
        note_date=date(2026, 4, 8),
    )

    with pytest.raises(NoteValidationError, match="unsafe daily notebook"):
        append_note(request, now=datetime(2026, 4, 8, tzinfo=timezone.utc))

    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_append_note_rejects_non_regular_daily_file(tmp_path: Path) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    daily = notes_dir / "2026-04-08.md"
    os.mkfifo(daily)
    reader_fd = os.open(daily, os.O_RDONLY | os.O_NONBLOCK)
    request = NoteAppendRequest(
        notes_dir=notes_dir,
        title="not a pipe",
        body="entry",
        note_date=date(2026, 4, 8),
    )

    try:
        with pytest.raises(NoteValidationError, match="not a regular file"):
            append_note(request, now=datetime(2026, 4, 8, tzinfo=timezone.utc))
    finally:
        os.close(reader_fd)


def test_append_and_read_reject_hardlinked_daily_file_without_mutation(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    outside = tmp_path / "outside.md"
    _write_note(outside, "outside")
    before = outside.read_bytes()
    os.link(outside, notes_dir / "2026-04-08.md")
    request = NoteAppendRequest(
        notes_dir=notes_dir,
        title="must not update alias",
        body="entry",
        note_date=date(2026, 4, 8),
    )

    with pytest.raises(NoteValidationError, match="single-link"):
        append_note(request, now=datetime(2026, 4, 8, tzinfo=timezone.utc))

    assert outside.read_bytes() == before
    assert list_note_days(notes_dir, count=0) == ()
    with pytest.raises(NoteNotFoundError):
        read_note(notes_dir, "2026-04-08", today=date(2026, 4, 8))


def test_append_note_completes_short_write_while_holding_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    request = NoteAppendRequest(
        notes_dir=notes_dir,
        title="short write",
        body="complete entry",
        note_date=date(2026, 4, 8),
    )
    real_write = os.write
    calls = 0

    def short_first_write(descriptor: int, payload: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            partial = max(1, len(payload) // 3)
            return real_write(descriptor, payload[:partial])
        return real_write(descriptor, payload)

    monkeypatch.setattr(notebook_module.os, "write", short_first_write)

    result = append_note(request, now=datetime(2026, 4, 8, tzinfo=timezone.utc))

    assert calls >= 2
    assert result.path.read_text(encoding="utf-8") == (
        "# 2026-04-08 — lab notebook\n\n## 09:00 short write\n\ncomplete entry\n\n"
    )


def test_append_note_retries_interrupted_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = NoteAppendRequest(
        notes_dir=tmp_path / "notes",
        title="interrupted",
        body="complete entry",
        note_date=date(2026, 4, 8),
    )
    real_write = os.write
    interrupted = False

    def interrupt_once(descriptor: int, payload: bytes) -> int:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise InterruptedError()
        return real_write(descriptor, payload)

    monkeypatch.setattr(notebook_module.os, "write", interrupt_once)

    result = append_note(request, now=datetime(2026, 4, 8, tzinfo=timezone.utc))

    assert interrupted is True
    assert "## 09:00 interrupted" in result.path.read_text(encoding="utf-8")


def test_append_note_rejects_zero_byte_write_without_partial_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    request = NoteAppendRequest(
        notes_dir=notes_dir,
        title="zero write",
        body="entry",
        note_date=date(2026, 4, 8),
    )
    monkeypatch.setattr(notebook_module.os, "write", lambda fd, payload: 0)

    with pytest.raises(NoteValidationError, match="zero-byte write"):
        append_note(request, now=datetime(2026, 4, 8, tzinfo=timezone.utc))

    assert (notes_dir / "2026-04-08.md").read_bytes() == b""


def test_append_note_rejects_symlink_notes_root(tmp_path: Path) -> None:
    actual_notes = tmp_path / "actual-notes"
    actual_notes.mkdir()
    notes_link = tmp_path / "notes"
    notes_link.symlink_to(actual_notes, target_is_directory=True)
    request = NoteAppendRequest(
        notes_dir=notes_link,
        title="must stay anchored",
        body="entry",
        note_date=date(2026, 4, 8),
    )

    with pytest.raises(NoteValidationError, match="unsafe notes directory"):
        append_note(request, now=datetime(2026, 4, 8, tzinfo=timezone.utc))

    assert list(actual_notes.iterdir()) == []


def test_concurrent_initial_appends_write_one_header_and_whole_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    note_date = date(2026, 4, 8)
    daily_name = f"{note_date.isoformat()}.md"
    worker_count = 4
    parent_pid = os.getpid()
    real_exists = Path.exists

    def pretend_daily_file_is_absent(path: Path) -> bool:
        if os.getpid() != parent_pid and path.name == daily_name:
            return False
        return real_exists(path)

    # This makes the old path.exists()/open() race deterministic. The fixed
    # implementation derives ``created`` from fstat() while holding the lock.
    monkeypatch.setattr(Path, "exists", pretend_daily_file_is_absent)
    start_read, start_write = os.pipe()
    result_read, result_write = os.pipe()
    children: list[int] = []

    for index in range(worker_count):
        child_pid = os.fork()
        if child_pid == 0:
            exit_code = 0
            try:
                os.close(start_write)
                os.close(result_read)
                os.read(start_read, 1)
                result = append_note(
                    NoteAppendRequest(
                        notes_dir=notes_dir,
                        title=f"entry-{index}",
                        body=f"BEGIN-{index}\n{'x' * 32_000}\nEND-{index}",
                        note_date=note_date,
                    ),
                    now=datetime(2026, 4, 8, tzinfo=timezone.utc),
                )
                os.write(result_write, b"1" if result.created else b"0")
            except BaseException:
                exit_code = 1
            finally:
                os.close(start_read)
                os.close(result_write)
            os._exit(exit_code)
        children.append(child_pid)

    os.close(start_read)
    os.close(result_write)
    os.write(start_write, b"x" * worker_count)
    os.close(start_write)
    statuses = b""
    while chunk := os.read(result_read, worker_count):
        statuses += chunk
    os.close(result_read)
    exit_codes = [
        os.waitstatus_to_exitcode(os.waitpid(child_pid, 0)[1]) for child_pid in children
    ]

    assert exit_codes == [0] * worker_count
    assert statuses.count(b"1") == 1
    assert statuses.count(b"0") == worker_count - 1
    text = (notes_dir / daily_name).read_text(encoding="utf-8")
    assert text.count(f"# {note_date.isoformat()} — lab notebook") == 1
    for index in range(worker_count):
        expected_entry = (
            f"## 09:00 entry-{index}\n\nBEGIN-{index}\n{'x' * 32_000}\nEND-{index}\n\n"
        )
        assert text.count(expected_entry) == 1


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


def test_list_note_days_skips_daily_symlinks(tmp_path: Path) -> None:
    notes_dir = tmp_path / "notes"
    active = notes_dir / "2026-04-08.md"
    history = notes_dir / "history" / "2026" / "2026-04-06.md"
    outside_active = tmp_path / "outside-active.md"
    outside_history = tmp_path / "outside-history.md"
    _write_note(notes_dir / "2026-04-07.md", "safe")
    _write_note(outside_active, "outside active")
    _write_note(outside_history, "outside history")
    active.symlink_to(outside_active)
    history.parent.mkdir(parents=True)
    history.symlink_to(outside_history)

    summaries = list_note_days(notes_dir, count=0)

    assert [summary.note_date for summary in summaries] == [date(2026, 4, 7)]


def test_read_note_skips_active_symlink_and_uses_regular_history_file(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    outside = tmp_path / "outside.md"
    active = notes_dir / "2026-04-08.md"
    history = notes_dir / "history" / "2026" / active.name
    _write_note(outside, "outside")
    notes_dir.mkdir()
    active.symlink_to(outside)
    _write_note(history, "history")

    document = read_note(notes_dir, "2026-04-08", today=date(2026, 4, 9))

    assert document.path == history
    assert "history" in document.text
    assert "outside" not in document.text


def test_read_and_list_reject_symlink_notes_root(tmp_path: Path) -> None:
    actual_notes = tmp_path / "actual-notes"
    _write_note(actual_notes / "2026-04-08.md", "outside root")
    notes_link = tmp_path / "notes"
    notes_link.symlink_to(actual_notes, target_is_directory=True)

    with pytest.raises(NoteValidationError, match="unsafe notes directory"):
        read_note(notes_link, "2026-04-08", today=date(2026, 4, 8))
    with pytest.raises(NoteValidationError, match="unsafe notes directory"):
        list_note_days(notes_link, count=0)


def test_read_io_error_is_not_reported_as_missing_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    _write_note(notes_dir / "2026-04-08.md", "entry")

    def fail_read(descriptor: int, size: int) -> bytes:
        raise OSError(errno.EIO, "storage read failed")

    monkeypatch.setattr(notebook_module.os, "read", fail_read)

    with pytest.raises(NoteValidationError, match="storage read failed"):
        list_note_days(notes_dir, count=0)


def test_invalid_utf8_note_is_reported_as_validation_error(tmp_path: Path) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "2026-04-08.md").write_bytes(b"# invalid \xff\n")

    with pytest.raises(NoteValidationError, match="UTF-8"):
        read_note(notes_dir, "2026-04-08", today=date(2026, 4, 8))


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
    root_stat = notes_dir.stat()
    old_stat = old.stat()
    assert plan.root_identity == (root_stat.st_dev, root_stat.st_ino)
    assert plan.entries[0].source_identity == (old_stat.st_dev, old_stat.st_ino)
    assert old.exists() and blocked.exists() and recent.exists()

    result = apply_note_archive(plan)

    assert [entry.source.name for entry in result.archived] == ["2026-04-01.md"]
    assert [entry.source.name for entry in result.skipped] == ["2026-04-02.md"]
    assert not old.exists()
    assert (notes_dir / "history" / "2026" / old.name).is_file()
    assert blocked.is_file()
    assert recent.is_file()


def test_archive_plan_rejects_symlink_notes_root_without_moving_target(
    tmp_path: Path,
) -> None:
    actual_notes = tmp_path / "actual-notes"
    old = actual_notes / "2026-04-01.md"
    _write_note(old, "outside")
    notes_link = tmp_path / "notes"
    notes_link.symlink_to(actual_notes, target_is_directory=True)

    with pytest.raises(NoteValidationError, match="unsafe notes directory"):
        plan_note_archive(notes_link, older_than="7d", today=date(2026, 4, 10))

    assert old.is_file()
    assert not (actual_notes / "history").exists()


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


def test_archive_validates_duration_before_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(NoteValidationError, match="expected a duration"):
        plan_note_archive(
            tmp_path / "missing",
            older_than="soon",
            today=date(2026, 4, 10),
        )


def test_archive_rejects_duration_that_underflows_date_before_missing_directory(
    tmp_path: Path,
) -> None:
    with pytest.raises(NoteValidationError, match="out of range"):
        plan_note_archive(
            tmp_path / "missing",
            older_than="1000000d",
            today=date(2026, 4, 10),
        )


def test_archive_treats_dangling_destination_symlink_as_occupied(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    destination = notes_dir / "history" / "2026" / source.name
    _write_note(source, "old")
    destination.parent.mkdir(parents=True)
    destination.symlink_to(tmp_path / "missing-destination.md")

    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))

    assert plan.entries[0].destination_exists is True
    result = apply_note_archive(plan)
    assert result.archived == ()
    assert result.skipped == plan.entries
    assert source.is_file()
    assert destination.is_symlink()


def test_archive_rejects_source_replaced_after_planning_without_mutation(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "planned")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    planned_source = notes_dir / "planned-source.md"
    source.rename(planned_source)
    _write_note(source, "replacement")

    with pytest.raises(NoteValidationError, match="stale archive source"):
        apply_note_archive(plan)

    assert "replacement" in source.read_text(encoding="utf-8")
    assert "planned" in planned_source.read_text(encoding="utf-8")
    assert not plan.entries[0].destination.exists()


def test_archive_rejects_notes_root_replaced_after_planning_without_mutation(
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "planned root")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    original_root = tmp_path / "original-notes"
    notes_dir.rename(original_root)
    replacement = notes_dir / source.name
    _write_note(replacement, "replacement root")

    with pytest.raises(NoteValidationError, match="stale notes directory"):
        apply_note_archive(plan)

    assert "planned root" in (original_root / source.name).read_text(encoding="utf-8")
    assert "replacement root" in replacement.read_text(encoding="utf-8")
    assert not (notes_dir / "history").exists()


def test_archive_preflights_every_entry_before_mutating_any_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    first = notes_dir / "2026-04-01.md"
    second = notes_dir / "2026-04-02.md"
    outside = tmp_path / "outside.md"
    _write_note(first, "first")
    _write_note(second, "second")
    outside.write_text("outside\n", encoding="utf-8")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    unsafe = replace(
        plan.entries[1],
        source=outside,
        destination=notes_dir / "history" / "2026" / outside.name,
    )
    tampered = replace(plan, entries=(plan.entries[0], unsafe))
    moves: list[tuple[str, str]] = []

    def record_move(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        del source_fd, destination_fd
        moves.append((source_name, destination_name))

    monkeypatch.setattr(notebook_module, "_rename_noreplace", record_move)

    with pytest.raises(NoteValidationError, match="unsafe archive source"):
        apply_note_archive(tampered)

    assert first.is_file()
    assert second.is_file()
    assert outside.is_file()
    assert not (notes_dir / "history").exists()
    assert moves == []


def test_archive_restores_source_when_staged_stat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "staged stat")
    original = source.read_text(encoding="utf-8")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    entry = plan.entries[0]
    rename_noreplace = notebook_module._rename_noreplace
    real_stat = notebook_module.os.stat
    staged = False
    failed_stat = False
    moves: list[tuple[str, str]] = []

    def track_staging(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal staged
        rename_noreplace(source_fd, source_name, destination_fd, destination_name)
        moves.append((source_name, destination_name))
        if source_name == entry.source.name and destination_name.startswith("."):
            staged = True

    def fail_staged_stat(path: object, *args: object, **kwargs: object) -> object:
        nonlocal failed_stat
        if (
            staged
            and not failed_stat
            and str(path).startswith(f".{entry.source.name}.archive-")
        ):
            failed_stat = True
            raise OSError(errno.EIO, "transient staged stat failure")
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(notebook_module, "_rename_noreplace", track_staging)
    monkeypatch.setattr(notebook_module.os, "stat", fail_staged_stat)

    with pytest.raises(NoteValidationError) as caught:
        apply_note_archive(plan)

    error = _assert_archive_apply_error(
        caught.value,
        failed_entry=entry,
        recovery_path=None,
    )
    assert isinstance(error.cause, OSError)
    assert error.cause.errno == errno.EIO
    assert len(moves) == 1
    staging_name = moves[0][1]
    assert moves == [(source.name, staging_name)]
    assert source.read_text(encoding="utf-8") == original
    assert not entry.destination.exists()
    assert list(notes_dir.glob(f".{source.name}.archive-*.tmp")) == []


def test_archive_unexpected_failure_reports_recovery_when_restore_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "unexpected failure")
    original = source.read_text(encoding="utf-8")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    entry = plan.entries[0]
    real_stat = notebook_module.os.stat
    staging_name: str | None = None

    def fail_staged_stat(path: object, *args: object, **kwargs: object) -> object:
        nonlocal staging_name
        if str(path).startswith(f".{source.name}.archive-"):
            staging_name = str(path)
            source.write_text("concurrent replacement\n", encoding="utf-8")
            raise RuntimeError("unexpected staged verification failure")
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(notebook_module.os, "stat", fail_staged_stat)

    with pytest.raises(NoteValidationError) as caught:
        apply_note_archive(plan)

    assert staging_name is not None
    recovery_path = notes_dir / staging_name
    error = _assert_archive_apply_error(
        caught.value,
        failed_entry=entry,
        recovery_path=recovery_path,
    )
    assert isinstance(error.cause, RuntimeError)
    assert source.read_text(encoding="utf-8") == "concurrent replacement\n"
    assert recovery_path.read_text(encoding="utf-8") == original


def test_archive_restores_after_ambiguous_stage_and_presence_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "ambiguous stage")
    original = source.read_text(encoding="utf-8")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    entry = plan.entries[0]
    rename_noreplace = notebook_module._rename_noreplace
    real_stat = notebook_module.os.stat
    staging_name: str | None = None
    failed_presence_check = False

    def move_then_report_eio(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal staging_name
        rename_noreplace(source_fd, source_name, destination_fd, destination_name)
        if source_name == entry.source.name and destination_name.startswith("."):
            staging_name = destination_name
            raise OSError(errno.EIO, "ambiguous stage result")

    def fail_presence_once(path: object, *args: object, **kwargs: object) -> object:
        nonlocal failed_presence_check
        if staging_name == str(path) and not failed_presence_check:
            failed_presence_check = True
            raise OSError(errno.EIO, "ambiguous staging presence")
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(notebook_module, "_rename_noreplace", move_then_report_eio)
    monkeypatch.setattr(notebook_module.os, "stat", fail_presence_once)

    with pytest.raises(NoteValidationError) as caught:
        apply_note_archive(plan)

    error = _assert_archive_apply_error(
        caught.value,
        failed_entry=entry,
        recovery_path=None,
    )
    assert isinstance(error.cause, OSError)
    assert error.cause.errno == errno.EIO
    assert staging_name is not None
    assert failed_presence_check is True
    assert source.read_text(encoding="utf-8") == original
    assert not (notes_dir / staging_name).exists()


def test_archive_does_not_report_missing_recovery_file_after_ambiguous_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "ambiguous noop")
    original = source.read_text(encoding="utf-8")
    original_stat = source.stat()
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    entry = plan.entries[0]
    rename_noreplace = notebook_module._rename_noreplace
    real_stat = notebook_module.os.stat
    staging_name: str | None = None
    failed_presence_check = False

    def report_eio_without_moving(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal staging_name
        if source_name == entry.source.name and destination_name.startswith("."):
            staging_name = destination_name
            raise OSError(errno.EIO, "ambiguous stage without move")
        rename_noreplace(source_fd, source_name, destination_fd, destination_name)

    def fail_presence_once(path: object, *args: object, **kwargs: object) -> object:
        nonlocal failed_presence_check
        if staging_name == str(path) and not failed_presence_check:
            failed_presence_check = True
            raise OSError(errno.EIO, "ambiguous staging presence")
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(notebook_module, "_rename_noreplace", report_eio_without_moving)
    monkeypatch.setattr(notebook_module.os, "stat", fail_presence_once)

    with pytest.raises(NoteValidationError) as caught:
        apply_note_archive(plan)

    error = _assert_archive_apply_error(
        caught.value,
        failed_entry=entry,
        recovery_path=None,
    )
    assert isinstance(error.cause, OSError)
    assert error.cause.errno == errno.EIO
    assert staging_name is not None
    assert source.read_text(encoding="utf-8") == original
    current_stat = source.stat()
    assert (current_stat.st_dev, current_stat.st_ino) == (
        original_stat.st_dev,
        original_stat.st_ino,
    )
    assert not (notes_dir / staging_name).exists()


@pytest.mark.parametrize("link_error", [errno.EOPNOTSUPP, errno.EXDEV])
def test_archive_leaves_source_untouched_when_noreplace_and_hardlink_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    link_error: int,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "unsupported fallback")
    original = source.read_text(encoding="utf-8")
    original_stat = source.stat()
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    entry = plan.entries[0]
    real_rename = notebook_module.os.rename
    renames: list[tuple[object, object]] = []

    def reject_renameat2(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        del source_fd, source_name, destination_fd, destination_name
        raise OSError(errno.EINVAL, "unsupported filesystem flag")

    def reject_hardlink(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError(link_error, "hardlink unsupported")

    def record_rename(
        source_name: object, destination_name: object, **kwargs: object
    ) -> None:
        renames.append((source_name, destination_name))
        real_rename(source_name, destination_name, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(notebook_module, "_renameat2_noreplace", reject_renameat2)
    monkeypatch.setattr(notebook_module.os, "link", reject_hardlink)
    monkeypatch.setattr(notebook_module.os, "rename", record_rename)

    with pytest.raises(NoteValidationError) as caught:
        apply_note_archive(plan)

    error = _assert_archive_apply_error(
        caught.value,
        failed_entry=entry,
        recovery_path=None,
    )
    assert isinstance(error.cause, OSError)
    assert error.cause.errno == link_error
    assert source.read_text(encoding="utf-8") == original
    current_stat = source.stat()
    assert (current_stat.st_dev, current_stat.st_ino) == (
        original_stat.st_dev,
        original_stat.st_ino,
    )
    assert renames == []
    assert not entry.destination.exists()
    assert list(notes_dir.glob(f".{source.name}.archive-*.tmp")) == []


def test_archive_fallback_never_unlinks_concurrent_source_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    concurrent_original = notes_dir / "planned-source-held-by-concurrent-writer.md"
    _write_note(source, "planned source")
    planned_text = source.read_text(encoding="utf-8")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    entry = plan.entries[0]
    real_link = notebook_module.os.link
    real_unlink = notebook_module.os.unlink
    injected_replacement = False
    unlinked_names: list[object] = []
    staging_name: str | None = None

    def reject_renameat2(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        del source_fd, source_name, destination_fd, destination_name
        raise OSError(errno.EINVAL, "unsupported filesystem flag")

    def replace_source_after_probe(
        source_name: object,
        destination_name: object,
        **kwargs: object,
    ) -> None:
        nonlocal injected_replacement, staging_name
        real_link(source_name, destination_name, **kwargs)  # type: ignore[arg-type]
        if (
            not injected_replacement
            and source_name == source.name
            and str(destination_name).startswith(f".{source.name}.archive-")
        ):
            staging_name = str(destination_name)
            source.rename(concurrent_original)
            source.write_text("concurrent replacement\n", encoding="utf-8")
            injected_replacement = True

    def record_unlink(path: object, **kwargs: object) -> None:
        unlinked_names.append(path)
        real_unlink(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(notebook_module, "_renameat2_noreplace", reject_renameat2)
    monkeypatch.setattr(notebook_module.os, "link", replace_source_after_probe)
    monkeypatch.setattr(notebook_module.os, "unlink", record_unlink)

    with pytest.raises(NoteValidationError) as caught:
        apply_note_archive(plan)

    assert staging_name is not None
    recovery_path = notes_dir / staging_name
    _assert_archive_apply_error(
        caught.value,
        failed_entry=entry,
        recovery_path=recovery_path,
    )
    assert injected_replacement is True
    assert source.read_text(encoding="utf-8") == "concurrent replacement\n"
    assert concurrent_original.read_text(encoding="utf-8") == planned_text
    assert not entry.destination.exists()
    assert source.name not in unlinked_names
    assert recovery_path.read_text(encoding="utf-8") == "concurrent replacement\n"


def test_archive_cleans_private_placeholder_when_identity_probe_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "placeholder failure")
    original = source.read_text(encoding="utf-8")
    original_stat = source.stat()
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    entry = plan.entries[0]
    real_open = notebook_module.os.open
    real_fstat = notebook_module.os.fstat
    placeholder_fd: int | None = None

    def reject_renameat2(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        del source_fd, source_name, destination_fd, destination_name
        raise OSError(errno.EINVAL, "unsupported filesystem flag")

    def track_placeholder_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal placeholder_fd
        opened = real_open(path, flags, mode, dir_fd=dir_fd)
        if (
            str(path).startswith(f".{source.name}.archive-")
            and flags & notebook_module.os.O_EXCL
        ):
            placeholder_fd = opened
        return opened

    def fail_placeholder_fstat(fd: int) -> object:
        if fd == placeholder_fd:
            raise OSError(errno.EIO, "placeholder identity failed")
        return real_fstat(fd)

    monkeypatch.setattr(notebook_module, "_renameat2_noreplace", reject_renameat2)
    monkeypatch.setattr(notebook_module.os, "open", track_placeholder_open)
    monkeypatch.setattr(notebook_module.os, "fstat", fail_placeholder_fstat)

    with pytest.raises(NoteValidationError) as caught:
        apply_note_archive(plan)

    error = _assert_archive_apply_error(
        caught.value,
        failed_entry=entry,
        recovery_path=None,
    )
    assert isinstance(error.cause, OSError)
    assert error.cause.errno == errno.EIO
    assert source.read_text(encoding="utf-8") == original
    current_stat = source.stat()
    assert (current_stat.st_dev, current_stat.st_ino) == (
        original_stat.st_dev,
        original_stat.st_ino,
    )
    assert list(notes_dir.glob(f".{source.name}.archive-*.tmp")) == []
    assert not entry.destination.exists()


def test_archive_fallback_restore_retains_original_during_source_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "fallback recovery")
    original = source.read_text(encoding="utf-8")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    entry = plan.entries[0]
    real_link = notebook_module.os.link
    real_unlink = notebook_module.os.unlink
    real_stat = notebook_module.os.stat
    staging_name: str | None = None
    failed_staged_stat = False
    injected_replacement = False

    def reject_renameat2(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        del source_fd, source_name, destination_fd, destination_name
        raise OSError(errno.EINVAL, "unsupported filesystem flag")

    def replace_source_after_restore_link(
        source_name: object,
        destination_name: object,
        **kwargs: object,
    ) -> None:
        nonlocal staging_name, injected_replacement
        real_link(source_name, destination_name, **kwargs)  # type: ignore[arg-type]
        if source_name == source.name and str(destination_name).startswith(
            f".{source.name}.archive-"
        ):
            staging_name = str(destination_name)
        if (
            staging_name is not None
            and str(source_name) == staging_name
            and destination_name == source.name
        ):
            real_unlink(source.name, dir_fd=kwargs["dst_dir_fd"])
            source.write_text("concurrent replacement\n", encoding="utf-8")
            injected_replacement = True

    def fail_staged_stat_once(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal failed_staged_stat
        if staging_name == str(path) and not failed_staged_stat:
            failed_staged_stat = True
            raise OSError(errno.EIO, "trigger fallback restore")
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(notebook_module, "_renameat2_noreplace", reject_renameat2)
    monkeypatch.setattr(notebook_module.os, "link", replace_source_after_restore_link)
    monkeypatch.setattr(notebook_module.os, "stat", fail_staged_stat_once)

    with pytest.raises(NoteValidationError) as caught:
        apply_note_archive(plan)

    assert staging_name is not None
    recovery_path = notes_dir / staging_name
    error = _assert_archive_apply_error(
        caught.value,
        failed_entry=entry,
        recovery_path=recovery_path,
    )
    assert isinstance(error.cause, OSError)
    assert error.cause.errno == errno.EIO
    assert injected_replacement is True
    assert source.read_text(encoding="utf-8") == "concurrent replacement\n"
    assert recovery_path.read_text(encoding="utf-8") == original
    assert not entry.destination.exists()


def test_archive_runtime_failure_reports_completed_entries_and_restores_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    first = notes_dir / "2026-04-01.md"
    second = notes_dir / "2026-04-02.md"
    _write_note(first, "first")
    _write_note(second, "second")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    first_entry, second_entry = plan.entries
    rename_noreplace = notebook_module._rename_noreplace

    def fail_second_destination(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        if (
            source_name.startswith(f".{second.name}.archive-")
            and destination_name == second.name
            and source_fd != destination_fd
        ):
            raise OSError(errno.EIO, "second destination failed")
        rename_noreplace(source_fd, source_name, destination_fd, destination_name)

    monkeypatch.setattr(
        notebook_module,
        "_rename_noreplace",
        fail_second_destination,
    )

    with pytest.raises(NoteValidationError) as caught:
        apply_note_archive(plan)

    error = _assert_archive_apply_error(
        caught.value,
        archived=(first_entry,),
        failed_entry=second_entry,
        recovery_path=None,
    )
    assert isinstance(error.cause, OSError)
    assert error.cause.errno == errno.EIO
    assert not first.exists()
    assert first_entry.destination.is_file()
    assert second.is_file()
    assert not second_entry.destination.exists()
    assert list(notes_dir.glob(f".{second.name}.archive-*.tmp")) == []


def test_archive_restore_failure_reports_exact_recovery_path_and_partial_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    first = notes_dir / "2026-04-01.md"
    second = notes_dir / "2026-04-02.md"
    _write_note(first, "first")
    _write_note(second, "planned second")
    second_original = second.read_text(encoding="utf-8")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    first_entry, second_entry = plan.entries
    rename_noreplace = notebook_module._rename_noreplace
    staged_names: list[str] = []

    def replace_source_then_fail_destination(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        rename_noreplace(source_fd, source_name, destination_fd, destination_name)
        if source_name == second.name and destination_name.startswith("."):
            staged_names.append(destination_name)
            second.write_text("concurrent replacement\n", encoding="utf-8")
            raise OSError(errno.EIO, "fail after staging")

    monkeypatch.setattr(
        notebook_module,
        "_rename_noreplace",
        replace_source_then_fail_destination,
    )

    with pytest.raises(NoteValidationError) as caught:
        apply_note_archive(plan)

    assert len(staged_names) == 1
    recovery_path = notes_dir / staged_names[0]
    error = _assert_archive_apply_error(
        caught.value,
        archived=(first_entry,),
        failed_entry=second_entry,
        recovery_path=recovery_path,
    )
    assert isinstance(error.cause, OSError)
    assert error.cause.errno == errno.EIO
    assert recovery_path.parent == notes_dir
    assert recovery_path.name.startswith(f".{second.name}.archive-")
    assert recovery_path.read_text(encoding="utf-8") == second_original
    assert second.read_text(encoding="utf-8") == "concurrent replacement\n"


def test_archive_rejects_history_symlink_swapped_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "old")
    outside = tmp_path / "outside"
    outside.mkdir()
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    validate = notebook_module._validate_archive_entry

    def swap_history(notes: Path, entry: NoteArchiveEntry) -> None:
        validate(notes, entry)
        (notes / "history").symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(notebook_module, "_validate_archive_entry", swap_history)

    with pytest.raises(NoteValidationError, match="unsafe archive directory"):
        apply_note_archive(plan)

    assert source.is_file()
    assert not (outside / source.name).exists()


def test_archive_never_clobbers_destination_created_during_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "old")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    entry = plan.entries[0]
    rename_noreplace = notebook_module._rename_noreplace

    def create_destination_then_rename(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        if destination_name == entry.destination.name:
            entry.destination.write_text("concurrent\n", encoding="utf-8")
        rename_noreplace(
            source_fd,
            source_name,
            destination_fd,
            destination_name,
        )

    monkeypatch.setattr(
        notebook_module,
        "_rename_noreplace",
        create_destination_then_rename,
    )

    result = apply_note_archive(plan)

    assert result.archived == ()
    assert result.skipped == (entry,)
    assert source.is_file()
    assert entry.destination.read_text(encoding="utf-8") == "concurrent\n"


def test_archive_preserves_source_replacement_created_after_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "planned source")
    planned_text = source.read_text(encoding="utf-8")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))
    entry = plan.entries[0]
    rename_noreplace = notebook_module._rename_noreplace

    def replace_source_after_staging(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        rename_noreplace(
            source_fd,
            source_name,
            destination_fd,
            destination_name,
        )
        if source_name == entry.source.name and destination_name.startswith("."):
            source.write_text("concurrent replacement\n", encoding="utf-8")

    monkeypatch.setattr(
        notebook_module,
        "_rename_noreplace",
        replace_source_after_staging,
    )

    result = apply_note_archive(plan)

    assert result.archived == (entry,)
    assert source.read_text(encoding="utf-8") == "concurrent replacement\n"
    assert entry.destination.read_text(encoding="utf-8") == planned_text


def test_archive_falls_back_when_filesystem_rejects_rename_noreplace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "notes"
    source = notes_dir / "2026-04-01.md"
    _write_note(source, "lustre fallback")
    original = source.read_text(encoding="utf-8")
    plan = plan_note_archive(notes_dir, older_than="7d", today=date(2026, 4, 10))

    def reject_renameat2(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        del source_fd, source_name, destination_fd, destination_name
        raise OSError(notebook_module.errno.EINVAL, "unsupported filesystem flag")

    monkeypatch.setattr(
        notebook_module,
        "_renameat2_noreplace",
        reject_renameat2,
    )

    result = apply_note_archive(plan)

    assert result.archived == plan.entries
    assert not source.exists()
    assert plan.entries[0].destination.read_text(encoding="utf-8") == original
