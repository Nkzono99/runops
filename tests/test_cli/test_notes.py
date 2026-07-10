"""Tests for the ``runops notes`` lab-notebook commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from runops.application.research.notebook import (
    NoteArchiveApplyError,
    NoteArchiveResult,
    plan_note_archive,
)
from runops.cli import notes as notes_module
from runops.cli.main import app

runner = CliRunner()


def _make_project(tmp_path: Path) -> Path:
    """Create the minimum project skeleton ``runops notes`` cares about."""
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "test"\n', encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# notes append
# ---------------------------------------------------------------------------


def test_append_creates_dated_file_with_header(tmp_path: Path) -> None:
    """First append of a day creates the file and writes a top-level header."""
    project = _make_project(tmp_path)
    fixed_now = datetime(2026, 4, 8, 14, 32, 0, tzinfo=notes_module.JST)

    with (
        patch("runops.cli.notes.Path.cwd", return_value=project),
        patch("runops.cli.notes.datetime") as dt_mock,
    ):
        dt_mock.now.return_value = fixed_now
        # Real strptime / date for show() helpers
        dt_mock.strptime.side_effect = lambda *a, **k: datetime.strptime(*a, **k)
        result = runner.invoke(
            app,
            ["notes", "append", "first entry", "hello", "world"],
        )

    assert result.exit_code == 0, result.output
    notes_file = project / "notes" / "2026-04-08.md"
    assert notes_file.is_file()
    text = notes_file.read_text(encoding="utf-8")
    assert text.startswith("# 2026-04-08 — lab notebook\n\n")
    assert "## 14:32 first entry" in text
    assert "hello world" in text


def test_append_second_entry_appends_without_duplicate_header(tmp_path: Path) -> None:
    """A second entry on the same day appends without re-writing the header."""
    project = _make_project(tmp_path)
    notes_file = project / "notes" / "2026-04-08.md"
    notes_file.parent.mkdir(parents=True)
    notes_file.write_text(
        "# 2026-04-08 — lab notebook\n\n## 09:00 morning\n\nbody\n\n",
        encoding="utf-8",
    )
    fixed_now = datetime(2026, 4, 8, 18, 5, 0, tzinfo=notes_module.JST)

    with (
        patch("runops.cli.notes.Path.cwd", return_value=project),
        patch("runops.cli.notes.datetime") as dt_mock,
    ):
        dt_mock.now.return_value = fixed_now
        dt_mock.strptime.side_effect = lambda *a, **k: datetime.strptime(*a, **k)
        result = runner.invoke(app, ["notes", "append", "evening", "later body"])

    assert result.exit_code == 0, result.output
    text = notes_file.read_text(encoding="utf-8")
    # Header appears exactly once.
    assert text.count("# 2026-04-08 — lab notebook") == 1
    assert "## 09:00 morning" in text
    assert "## 18:05 evening" in text
    assert "later body" in text


def test_append_date_option_writes_to_specified_day(tmp_path: Path) -> None:
    """--date YYYY-MM-DD writes to that day's notebook file."""
    project = _make_project(tmp_path)
    fixed_now = datetime(2026, 4, 12, 1, 30, 0, tzinfo=notes_module.JST)

    with (
        patch("runops.cli.notes.Path.cwd", return_value=project),
        patch("runops.cli.notes.datetime") as dt_mock,
    ):
        dt_mock.now.return_value = fixed_now
        dt_mock.strptime.side_effect = lambda *a, **k: datetime.strptime(*a, **k)
        result = runner.invoke(
            app,
            [
                "notes",
                "append",
                "--date",
                "2026-04-11",
                "late-night continuation",
                "still wrapping up yesterday",
            ],
        )

    assert result.exit_code == 0, result.output
    # Entry lands in the requested day, not today (2026-04-12)
    target = project / "notes" / "2026-04-11.md"
    today_file = project / "notes" / "2026-04-12.md"
    assert target.is_file()
    assert not today_file.exists()
    text = target.read_text(encoding="utf-8")
    assert "# 2026-04-11 — lab notebook" in text
    assert "## 01:30 late-night continuation" in text
    assert "still wrapping up yesterday" in text


def test_append_date_option_rejects_invalid_date(tmp_path: Path) -> None:
    """Invalid --date argument exits with a clear error."""
    project = _make_project(tmp_path)

    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(
            app,
            [
                "notes",
                "append",
                "--date",
                "not-a-date",
                "title",
                "body",
            ],
        )

    assert result.exit_code == 2
    assert "invalid --date" in result.output


def test_append_body_from_stdin(tmp_path: Path) -> None:
    """Omitting body args reads from stdin."""
    project = _make_project(tmp_path)
    fixed_now = datetime(2026, 4, 8, 10, 0, 0, tzinfo=notes_module.JST)

    with (
        patch("runops.cli.notes.Path.cwd", return_value=project),
        patch("runops.cli.notes.datetime") as dt_mock,
    ):
        dt_mock.now.return_value = fixed_now
        dt_mock.strptime.side_effect = lambda *a, **k: datetime.strptime(*a, **k)
        result = runner.invoke(
            app,
            ["notes", "append", "stdin entry"],
            input="line1\nline2\n",
        )

    assert result.exit_code == 0, result.output
    text = (project / "notes" / "2026-04-08.md").read_text(encoding="utf-8")
    assert "## 10:00 stdin entry" in text
    assert "line1\nline2" in text


def test_append_dash_body_reads_stdin(tmp_path: Path) -> None:
    """Passing ``-`` as body sentinel reads stdin."""
    project = _make_project(tmp_path)
    fixed_now = datetime(2026, 4, 8, 12, 0, 0, tzinfo=notes_module.JST)

    with (
        patch("runops.cli.notes.Path.cwd", return_value=project),
        patch("runops.cli.notes.datetime") as dt_mock,
    ):
        dt_mock.now.return_value = fixed_now
        dt_mock.strptime.side_effect = lambda *a, **k: datetime.strptime(*a, **k)
        result = runner.invoke(
            app,
            ["notes", "append", "stdin via dash", "-"],
            input="dash body\n",
        )

    assert result.exit_code == 0, result.output
    text = (project / "notes" / "2026-04-08.md").read_text(encoding="utf-8")
    assert "## 12:00 stdin via dash" in text
    assert "dash body" in text


def test_append_empty_body_errors(tmp_path: Path) -> None:
    """An empty body (no args, empty stdin) is an error."""
    project = _make_project(tmp_path)
    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "append", "title"], input="")
    assert result.exit_code == 2
    assert "body is empty" in result.output


def test_append_empty_title_errors(tmp_path: Path) -> None:
    """A whitespace-only title is rejected."""
    project = _make_project(tmp_path)
    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "append", "   ", "body"])
    assert result.exit_code == 2
    assert "title must be non-empty" in result.output


def test_append_outside_project_uses_cwd(tmp_path: Path) -> None:
    """Without runops.toml the command falls back to ``<cwd>/notes``."""
    fixed_now = datetime(2026, 4, 8, 8, 30, 0, tzinfo=notes_module.JST)
    with (
        patch("runops.cli.notes.Path.cwd", return_value=tmp_path),
        patch("runops.cli.notes.datetime") as dt_mock,
    ):
        dt_mock.now.return_value = fixed_now
        dt_mock.strptime.side_effect = lambda *a, **k: datetime.strptime(*a, **k)
        result = runner.invoke(app, ["notes", "append", "no project", "body"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "notes" / "2026-04-08.md").is_file()


def test_append_explicit_notes_dir(tmp_path: Path) -> None:
    """``--notes-dir`` overrides project resolution."""
    project = _make_project(tmp_path)
    custom = tmp_path / "alt-notes"
    fixed_now = datetime(2026, 4, 8, 9, 0, 0, tzinfo=notes_module.JST)
    with (
        patch("runops.cli.notes.Path.cwd", return_value=project),
        patch("runops.cli.notes.datetime") as dt_mock,
    ):
        dt_mock.now.return_value = fixed_now
        dt_mock.strptime.side_effect = lambda *a, **k: datetime.strptime(*a, **k)
        result = runner.invoke(
            app,
            ["notes", "append", "custom dir", "body", "--notes-dir", str(custom)],
        )

    assert result.exit_code == 0, result.output
    assert (custom / "2026-04-08.md").is_file()
    # The default notes/ directory should NOT have been touched.
    assert not (project / "notes" / "2026-04-08.md").exists()


# ---------------------------------------------------------------------------
# notes list
# ---------------------------------------------------------------------------


def test_list_empty(tmp_path: Path) -> None:
    """List with no notes/ directory is graceful."""
    project = _make_project(tmp_path)
    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "list"])
    assert result.exit_code == 0
    assert "No notes" in result.output


def test_list_shows_recent_days_with_entry_count(tmp_path: Path) -> None:
    """List shows files newest first with the number of ## entries."""
    project = _make_project(tmp_path)
    notes_dir = project / "notes"
    notes_dir.mkdir()
    (notes_dir / "README.md").write_text(
        "readme — should be filtered\n",
        encoding="utf-8",
    )
    (notes_dir / "2026-04-06.md").write_text(
        "# 2026-04-06 — lab notebook\n\n## 10:00 a\n\nx\n\n## 11:00 b\n\ny\n\n",
        encoding="utf-8",
    )
    (notes_dir / "2026-04-08.md").write_text(
        "# 2026-04-08 — lab notebook\n\n## 09:00 a\n\nx\n\n",
        encoding="utf-8",
    )

    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "list"])

    assert result.exit_code == 0, result.output
    # Newest day first.
    pos_08 = result.output.find("2026-04-08")
    pos_06 = result.output.find("2026-04-06")
    assert 0 <= pos_08 < pos_06
    # Entry counts are present.
    assert "1" in result.output
    assert "2" in result.output
    # README is excluded.
    assert "README" not in result.output
    assert "2 day(s)" in result.output


def test_list_includes_history_days(tmp_path: Path) -> None:
    """List searches both active notes and notes/history/."""
    project = _make_project(tmp_path)
    notes_dir = project / "notes"
    history_dir = notes_dir / "history" / "2026"
    history_dir.mkdir(parents=True)
    notes_dir.mkdir(exist_ok=True)
    (notes_dir / "2026-04-08.md").write_text(
        "# 2026-04-08 — lab notebook\n\n## 09:00 active\n\nx\n\n",
        encoding="utf-8",
    )
    (history_dir / "2026-03-30.md").write_text(
        "# 2026-03-30 — lab notebook\n\n## 10:00 archived\n\nx\n\n",
        encoding="utf-8",
    )

    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "list", "-n", "0"])

    assert result.exit_code == 0, result.output
    assert "2026-04-08" in result.output
    assert "2026-03-30" in result.output
    assert "notes/history/2026/2026-03-30.md" in result.output
    assert "2 day(s)" in result.output


# ---------------------------------------------------------------------------
# notes show
# ---------------------------------------------------------------------------


def test_show_today(tmp_path: Path) -> None:
    """``notes show`` with no argument prints today's file."""
    project = _make_project(tmp_path)
    notes_dir = project / "notes"
    notes_dir.mkdir()
    (notes_dir / "2026-04-08.md").write_text("today body\n", encoding="utf-8")
    fixed_now = datetime(2026, 4, 8, 12, 0, 0, tzinfo=notes_module.JST)

    with (
        patch("runops.cli.notes.Path.cwd", return_value=project),
        patch("runops.cli.notes.datetime") as dt_mock,
    ):
        dt_mock.now.return_value = fixed_now
        dt_mock.strptime.side_effect = lambda *a, **k: datetime.strptime(*a, **k)
        result = runner.invoke(app, ["notes", "show"])

    assert result.exit_code == 0
    assert "today body" in result.output


def test_show_latest(tmp_path: Path) -> None:
    """``latest`` selects the newest file by name."""
    project = _make_project(tmp_path)
    notes_dir = project / "notes"
    notes_dir.mkdir()
    (notes_dir / "2026-04-06.md").write_text("old\n", encoding="utf-8")
    (notes_dir / "2026-04-07.md").write_text("newer\n", encoding="utf-8")

    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "show", "latest"])

    assert result.exit_code == 0
    assert "newer" in result.output
    assert "old" not in result.output


def test_show_explicit_date(tmp_path: Path) -> None:
    """An explicit YYYY-MM-DD selects that exact day."""
    project = _make_project(tmp_path)
    notes_dir = project / "notes"
    notes_dir.mkdir()
    (notes_dir / "2026-04-07.md").write_text("seven\n", encoding="utf-8")

    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "show", "2026-04-07"])

    assert result.exit_code == 0
    assert "seven" in result.output


def test_show_explicit_date_finds_history_file(tmp_path: Path) -> None:
    """An explicit date can be loaded from notes/history/."""
    project = _make_project(tmp_path)
    history_dir = project / "notes" / "history" / "2026"
    history_dir.mkdir(parents=True)
    (history_dir / "2026-03-30.md").write_text("archived body\n", encoding="utf-8")

    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "show", "2026-03-30"])

    assert result.exit_code == 0
    assert "archived body" in result.output


def test_show_latest_can_select_history_file(tmp_path: Path) -> None:
    """``latest`` searches history when no newer active note exists."""
    project = _make_project(tmp_path)
    history_dir = project / "notes" / "history" / "2026"
    history_dir.mkdir(parents=True)
    (history_dir / "2026-03-30.md").write_text("archived latest\n", encoding="utf-8")

    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "show", "latest"])

    assert result.exit_code == 0
    assert "archived latest" in result.output


def test_show_invalid_date(tmp_path: Path) -> None:
    """A malformed date errors out."""
    project = _make_project(tmp_path)
    (project / "notes").mkdir()
    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "show", "not-a-date"])
    assert result.exit_code == 2
    assert "invalid date" in result.output


def test_show_missing_file(tmp_path: Path) -> None:
    """Asking for a date with no file errors with a clear message."""
    project = _make_project(tmp_path)
    (project / "notes").mkdir()
    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "show", "2026-04-07"])
    assert result.exit_code == 1
    assert "No notes for 2026-04-07" in result.output


# ---------------------------------------------------------------------------
# notes archive
# ---------------------------------------------------------------------------


def test_archive_moves_old_active_notes_into_history(tmp_path: Path) -> None:
    """Archive moves old root-level daily files but keeps recent notes active."""
    project = _make_project(tmp_path)
    notes_dir = project / "notes"
    reports_dir = notes_dir / "reports"
    reports_dir.mkdir(parents=True)
    (notes_dir / "2026-04-30.md").write_text("old\n", encoding="utf-8")
    (notes_dir / "2026-05-02.md").write_text("recent\n", encoding="utf-8")
    (reports_dir / "2026-04-01.md").write_text("report\n", encoding="utf-8")
    fixed_now = datetime(2026, 5, 8, 12, 0, 0, tzinfo=notes_module.JST)

    with (
        patch("runops.cli.notes.Path.cwd", return_value=project),
        patch("runops.cli.notes.datetime") as dt_mock,
    ):
        dt_mock.now.return_value = fixed_now
        dt_mock.strptime.side_effect = lambda *a, **k: datetime.strptime(*a, **k)
        result = runner.invoke(app, ["notes", "archive", "--older-than", "7d"])

    assert result.exit_code == 0, result.output
    assert not (notes_dir / "2026-04-30.md").exists()
    assert (notes_dir / "history" / "2026" / "2026-04-30.md").read_text(
        encoding="utf-8"
    ) == "old\n"
    assert (notes_dir / "2026-05-02.md").is_file()
    assert (reports_dir / "2026-04-01.md").is_file()
    assert "1 note(s) archived" in result.output


def test_archive_dry_run_does_not_move_files(tmp_path: Path) -> None:
    """--dry-run previews eligible moves without touching files."""
    project = _make_project(tmp_path)
    notes_dir = project / "notes"
    notes_dir.mkdir()
    old_note = notes_dir / "2026-04-30.md"
    old_note.write_text("old\n", encoding="utf-8")
    fixed_now = datetime(2026, 5, 8, 12, 0, 0, tzinfo=notes_module.JST)

    with (
        patch("runops.cli.notes.Path.cwd", return_value=project),
        patch("runops.cli.notes.datetime") as dt_mock,
    ):
        dt_mock.now.return_value = fixed_now
        dt_mock.strptime.side_effect = lambda *a, **k: datetime.strptime(*a, **k)
        result = runner.invoke(
            app,
            ["notes", "archive", "--older-than", "7d", "--dry-run"],
        )

    assert result.exit_code == 0, result.output
    assert old_note.is_file()
    assert not (notes_dir / "history").exists()
    assert "Would archive" in result.output
    assert "1 note(s) would be archived" in result.output


def test_archive_rejects_invalid_older_than(tmp_path: Path) -> None:
    """Invalid --older-than value exits with a clear error."""
    project = _make_project(tmp_path)
    (project / "notes").mkdir()

    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "archive", "--older-than", "soon"])

    assert result.exit_code == 2
    assert "invalid --older-than" in result.output


def test_archive_rejects_invalid_older_than_before_missing_notes_dir(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path)

    with patch("runops.cli.notes.Path.cwd", return_value=project):
        result = runner.invoke(app, ["notes", "archive", "--older-than", "soon"])

    assert result.exit_code == 2
    assert "invalid --older-than" in result.output


def test_archive_renders_partial_result_and_recovery_path_without_traceback(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path)
    notes_dir = project / "notes"
    notes_dir.mkdir()
    (notes_dir / "2026-04-01.md").write_text("first\n", encoding="utf-8")
    (notes_dir / "2026-04-02.md").write_text("second\n", encoding="utf-8")
    plan = plan_note_archive(
        notes_dir,
        older_than="7d",
        today=datetime(2026, 4, 10).date(),
    )
    first, second = plan.entries
    recovery_path = notes_dir / f".{second.source.name}.archive-recovery.tmp"
    apply_error = NoteArchiveApplyError(
        "notebook archive failed after staging",
        completed=NoteArchiveResult(archived=(first,), skipped=()),
        failed_entry=second,
        recovery_path=recovery_path,
        cause=RuntimeError("injected archive invariant failure"),
    )

    with (
        patch("runops.cli.notes.Path.cwd", return_value=project),
        patch("runops.cli.notes.plan_note_archive", return_value=plan),
        patch("runops.cli.notes.apply_note_archive", side_effect=apply_error),
    ):
        result = runner.invoke(app, ["notes", "archive", "--older-than", "7d"])

    assert result.exit_code == 1
    assert "Error: notebook archive failed after staging" in result.output
    assert "Completed before failure: 1 archived; 0 skipped." in result.output
    assert f"Failed entry: {second.source.as_posix()}" in result.output
    assert f"Recovery file: {recovery_path.as_posix()}" in result.output
    assert "Cause: RuntimeError: injected archive invariant failure" in result.output
    assert "Traceback" not in result.output
    assert not isinstance(result.exception, NoteArchiveApplyError)
