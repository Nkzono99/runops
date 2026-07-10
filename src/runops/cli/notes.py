"""CLI commands for the project lab notebook (``notes/YYYY-MM-DD.md``).

The lab notebook is a chronological, append-only counterpart to the curated
knowledge layer (``.runops/insights/``, ``.runops/facts.toml``).  Use it for
sequential observations, hypotheses, scratch experiments, and TODOs that do
not yet warrant a named insight.

Conventions:

- One file per JST day, named ``notes/YYYY-MM-DD.md``.
- Each entry is a level-2 heading ``## HH:MM <title>`` followed by the body.
- The first entry of a day prepends a top-level header
  ``# YYYY-MM-DD — lab notebook``.
- Entries are append-only; do not rewrite past entries.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.application.research.notebook import (
    JST,
    NoteAppendRequest,
    NoteDirectoryNotFoundError,
    NoteNotFoundError,
    NoteValidationError,
    append_note,
    apply_note_archive,
    list_note_days,
    plan_note_archive,
    read_note,
    resolve_notes_dir,
)


def _read_body(body_args: list[str]) -> str:
    """Build the entry body from CLI args / stdin.

    - If ``body_args`` is non-empty and not ``["-"]``, join with spaces.
    - Otherwise read from stdin until EOF.
    """
    if body_args and body_args != ["-"]:
        return " ".join(body_args).strip()
    if sys.stdin.isatty():
        typer.echo(
            "Reading body from stdin; finish with Ctrl-D (Unix) / Ctrl-Z (Windows).",
            err=True,
        )
    return sys.stdin.read().strip()


def append(
    title: Annotated[
        str,
        typer.Argument(help="Short title for this entry (becomes the H2 heading)."),
    ],
    body: Annotated[
        Optional[list[str]],
        typer.Argument(
            help=(
                "Entry body.  Pass inline as positional words, or use ``-`` "
                "(or omit) to read from stdin."
            )
        ),
    ] = None,
    notes_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--notes-dir",
            help="Override the notes directory (defaults to <project>/notes).",
        ),
    ] = None,
    date: Annotated[
        Optional[str],
        typer.Option(
            "--date",
            help=(
                "Write to a specific day's notebook (YYYY-MM-DD) instead of "
                "today. Useful for catching up on past entries."
            ),
        ),
    ] = None,
) -> None:
    """Append a timestamped entry to today's lab notebook.

    The entry is written to ``notes/YYYY-MM-DD.md`` (JST today) under a new
    ``## HH:MM <title>`` heading.  The file is created on first use of the
    day with a top-level ``# YYYY-MM-DD — lab notebook`` header.

    Pass ``--date YYYY-MM-DD`` to append to a specific day's notebook
    (e.g. for catching up on past entries after midnight).

    Examples::

        runo notes append "cs scaling preview" "tan(alpha) = 0.79 cs/v + 0.02"
        echo "..." | runo notes append "today's TODO"
        runo notes append --date 2026-04-10 "yesterday's continuation" "..."
    """
    clean_title = title.strip()
    if not clean_title:
        typer.echo("Error: title must be non-empty.", err=True)
        raise typer.Exit(code=2)

    text = _read_body(body or [])
    if not text:
        typer.echo(
            "Error: body is empty (pass body inline or via stdin).",
            err=True,
        )
        raise typer.Exit(code=2)

    target_dir = resolve_notes_dir(notes_dir, cwd=Path.cwd())
    try:
        result = append_note(
            NoteAppendRequest(
                notes_dir=target_dir,
                title=clean_title,
                body=text,
                note_date=date,
            ),
            now=datetime.now(JST),
        )
    except NoteValidationError as exc:
        if date is not None:
            typer.echo(f"Error: invalid --date '{date}': {exc}", err=True)
        else:
            typer.echo(f"Error: {exc}.", err=True)
        raise typer.Exit(code=2) from None

    try:
        display = result.path.relative_to(Path.cwd())
    except ValueError:
        display = result.path
    typer.echo(f"Appended to {display.as_posix()}")


def list_notes(
    notes_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--notes-dir",
            help="Override the notes directory (defaults to <project>/notes).",
        ),
    ] = None,
    count: Annotated[
        int,
        typer.Option(
            "-n",
            "--count",
            help="Maximum number of days to list (0 = all).",
        ),
    ] = 14,
) -> None:
    """List recent lab-notebook days.

    Shows the most recent ``notes/YYYY-MM-DD.md`` files together with the
    number of entries (``## `` headings) inside each.
    """
    target_dir = resolve_notes_dir(notes_dir, cwd=Path.cwd())
    try:
        summaries = list_note_days(target_dir, count=count)
    except NoteDirectoryNotFoundError:
        typer.echo("No notes/ directory found.")
        return

    if not summaries:
        typer.echo("No notes yet.")
        return

    headers = ("DATE", "ENTRIES", "PATH")
    rows: list[tuple[str, str, str]] = []
    for summary in summaries:
        try:
            rel = summary.path.relative_to(Path.cwd()).as_posix()
        except ValueError:
            rel = summary.path.as_posix()
        rows.append((summary.note_date.isoformat(), str(summary.entry_count), rel))

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    typer.echo(fmt.format(*headers))
    typer.echo(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        typer.echo(fmt.format(*row))
    typer.echo(f"\n{len(rows)} day(s)")


def show(
    date: Annotated[
        Optional[str],
        typer.Argument(
            help=(
                "Date to display in YYYY-MM-DD form, or ``today`` / ``latest`` "
                "(default: today)."
            )
        ),
    ] = None,
    notes_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--notes-dir",
            help="Override the notes directory (defaults to <project>/notes).",
        ),
    ] = None,
) -> None:
    """Print the contents of a single lab-notebook day.

    With no argument, prints today's notes (JST).  ``latest`` selects the
    most recent day that has a file on disk; an explicit ``YYYY-MM-DD``
    selects that exact day.
    """
    target_dir = resolve_notes_dir(notes_dir, cwd=Path.cwd())
    try:
        document = read_note(
            target_dir,
            date,
            today=datetime.now(JST).date(),
        )
    except NoteDirectoryNotFoundError:
        typer.echo("No notes/ directory found.")
        raise typer.Exit(code=1) from None
    except NoteValidationError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from None
    except NoteNotFoundError as exc:
        if exc.note_date is None:
            typer.echo("No notes yet.")
        else:
            typer.echo(f"No notes for {exc.note_date.isoformat()}.")
        raise typer.Exit(code=1) from None

    typer.echo(document.text, nl=False)


def archive(
    notes_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--notes-dir",
            help="Override the notes directory (defaults to <project>/notes).",
        ),
    ] = None,
    older_than: Annotated[
        str,
        typer.Option(
            "--older-than",
            help="Archive active daily notebooks older than this duration, e.g. 7d.",
        ),
    ] = "7d",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show which files would move without modifying the filesystem.",
        ),
    ] = False,
) -> None:
    """Move old active daily notebooks under ``notes/history/YYYY/``.

    Only root-level daily notebooks (``notes/YYYY-MM-DD.md``) are moved.
    ``notes/reports/`` and existing history files are never touched.
    """
    target_dir = resolve_notes_dir(notes_dir, cwd=Path.cwd())
    try:
        plan = plan_note_archive(
            target_dir,
            older_than=older_than,
            today=datetime.now(JST).date(),
        )
    except NoteValidationError as exc:
        typer.echo(f"Error: invalid --older-than '{older_than}': {exc}", err=True)
        raise typer.Exit(code=2) from None
    except NoteDirectoryNotFoundError:
        typer.echo("No notes/ directory found.")
        return

    if not plan.entries:
        typer.echo("No active daily notebooks to archive.")
        return

    application_result = None if dry_run else apply_note_archive(plan)
    archived = set(application_result.archived) if application_result else set()
    skipped_entries = set(application_result.skipped) if application_result else set()
    moved = len(archived) if application_result else 0
    skipped = len(skipped_entries) if application_result else 0
    for entry in plan.entries:
        try:
            source_display = entry.source.relative_to(Path.cwd())
        except ValueError:
            source_display = entry.source
        try:
            dest_display = entry.destination.relative_to(Path.cwd())
        except ValueError:
            dest_display = entry.destination
        source_text = source_display.as_posix()
        dest_text = dest_display.as_posix()

        if (dry_run and entry.destination_exists) or entry in skipped_entries:
            if dry_run and entry.destination_exists:
                skipped += 1
            typer.echo(f"Skipped {source_text}: destination exists ({dest_text})")
            continue

        if dry_run:
            typer.echo(f"Would archive {source_text} -> {dest_text}")
            moved += 1
            continue

        if entry in archived:
            typer.echo(f"Archived {source_text} -> {dest_text}")

    action = "would be archived" if dry_run else "archived"
    typer.echo(f"\n{moved} note(s) {action}; {skipped} skipped.")
