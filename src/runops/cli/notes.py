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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root

JST = timezone(timedelta(hours=9))
_HISTORY_DIR = "history"
_NOTE_DATE_FORMAT = "%Y-%m-%d"


def _resolve_notes_dir(explicit: Optional[Path] = None) -> Path:
    """Locate the project's ``notes/`` directory.

    Falls back to ``<cwd>/notes`` if no ``runops.toml`` is found, so the
    command remains usable in lightweight contexts.
    """
    if explicit is not None:
        return explicit.resolve()
    try:
        root = find_project_root(Path.cwd())
        return root / "notes"
    except SimctlError:
        return Path.cwd() / "notes"


def _today_path(notes_dir: Path, *, now: Optional[datetime] = None) -> Path:
    today = (now or datetime.now(JST)).date().isoformat()
    return notes_dir / f"{today}.md"


def _parse_note_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, _NOTE_DATE_FORMAT)
    except ValueError:
        return None


def _is_daily_note(path: Path) -> bool:
    return path.suffix == ".md" and _parse_note_date(path.stem) is not None


def _iter_note_files(notes_dir: Path) -> list[Path]:
    """Return daily notebook files from active notes and history.

    Active files in ``notes/YYYY-MM-DD.md`` win if the same date also exists
    under ``notes/history/``.
    """
    by_date: dict[str, Path] = {}
    for path in sorted(
        notes_dir.glob("*.md"),
        key=lambda item: item.stem,
        reverse=True,
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


def _find_note_file(notes_dir: Path, date_str: str) -> Path | None:
    active = notes_dir / f"{date_str}.md"
    if active.is_file():
        return active
    for path in _iter_note_files(notes_dir):
        if path.stem == date_str:
            return path
    return None


def _parse_older_than(value: str) -> int:
    raw = value.strip().lower()
    if raw.endswith("d"):
        raw = raw[:-1]
    try:
        days = int(raw)
    except ValueError as exc:
        msg = "expected a duration like '7d' or a positive day count"
        raise ValueError(msg) from exc
    if days <= 0:
        raise ValueError("duration must be positive")
    return days


def _history_path_for(notes_dir: Path, note_path: Path) -> Path:
    year = note_path.stem[:4]
    return notes_dir / _HISTORY_DIR / year / note_path.name


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
    title = title.strip()
    if not title:
        typer.echo("Error: title must be non-empty.", err=True)
        raise typer.Exit(code=2)

    text = _read_body(body or [])
    if not text:
        typer.echo(
            "Error: body is empty (pass body inline or via stdin).",
            err=True,
        )
        raise typer.Exit(code=2)

    target_dir = _resolve_notes_dir(notes_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(JST)
    if date is not None:
        try:
            entry_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError as exc:
            typer.echo(f"Error: invalid --date '{date}': {exc}", err=True)
            raise typer.Exit(code=2) from None
        path = target_dir / f"{entry_date.isoformat()}.md"
        header_date = entry_date.isoformat()
    else:
        path = _today_path(target_dir, now=now)
        header_date = now.date().isoformat()
    needs_header = not path.exists()

    with open(path, "a", encoding="utf-8") as f:
        if needs_header:
            f.write(f"# {header_date} — lab notebook\n\n")
        f.write(f"## {now.strftime('%H:%M')} {title}\n\n")
        f.write(text.rstrip() + "\n\n")

    try:
        display = path.relative_to(Path.cwd())
    except ValueError:
        display = path
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
    target_dir = _resolve_notes_dir(notes_dir)
    if not target_dir.is_dir():
        typer.echo("No notes/ directory found.")
        return

    files = _iter_note_files(target_dir)
    if not files:
        typer.echo("No notes yet.")
        return

    if count > 0:
        files = files[:count]

    headers = ("DATE", "ENTRIES", "PATH")
    rows: list[tuple[str, str, str]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        n_entries = sum(1 for line in text.splitlines() if line.startswith("## "))
        try:
            rel = path.relative_to(Path.cwd()).as_posix()
        except ValueError:
            rel = path.as_posix()
        rows.append((path.stem, str(n_entries), rel))

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
    target_dir = _resolve_notes_dir(notes_dir)
    if not target_dir.is_dir():
        typer.echo("No notes/ directory found.")
        raise typer.Exit(code=1)

    if date is None or date == "today":
        path = _today_path(target_dir)
    elif date == "latest":
        files = _iter_note_files(target_dir)
        if not files:
            typer.echo("No notes yet.")
            raise typer.Exit(code=1)
        path = files[0]
    else:
        date_str: str = date
        try:
            datetime.strptime(date_str, _NOTE_DATE_FORMAT)
        except ValueError as exc:
            typer.echo(f"Error: invalid date '{date_str}': {exc}", err=True)
            raise typer.Exit(code=2) from None
        path = _find_note_file(target_dir, date_str) or target_dir / f"{date_str}.md"

    if not path.is_file():
        typer.echo(f"No notes for {path.stem}.")
        raise typer.Exit(code=1)

    typer.echo(path.read_text(encoding="utf-8"), nl=False)


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
    try:
        days = _parse_older_than(older_than)
    except ValueError as exc:
        typer.echo(f"Error: invalid --older-than '{older_than}': {exc}", err=True)
        raise typer.Exit(code=2) from None

    target_dir = _resolve_notes_dir(notes_dir)
    if not target_dir.is_dir():
        typer.echo("No notes/ directory found.")
        return

    cutoff = datetime.now(JST).date() - timedelta(days=days)
    candidates: list[tuple[Path, Path]] = []
    for path in sorted(target_dir.glob("*.md"), key=lambda item: item.stem):
        parsed = _parse_note_date(path.stem)
        if parsed is None or parsed.date() >= cutoff:
            continue
        candidates.append((path, _history_path_for(target_dir, path)))

    if not candidates:
        typer.echo("No active daily notebooks to archive.")
        return

    moved = 0
    skipped = 0
    for source, dest in candidates:
        try:
            source_display = source.relative_to(Path.cwd())
        except ValueError:
            source_display = source
        try:
            dest_display = dest.relative_to(Path.cwd())
        except ValueError:
            dest_display = dest
        source_text = source_display.as_posix()
        dest_text = dest_display.as_posix()

        if dest.exists():
            skipped += 1
            typer.echo(f"Skipped {source_text}: destination exists ({dest_text})")
            continue

        if dry_run:
            typer.echo(f"Would archive {source_text} -> {dest_text}")
            moved += 1
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        source.rename(dest)
        typer.echo(f"Archived {source_text} -> {dest_text}")
        moved += 1

    action = "would be archived" if dry_run else "archived"
    typer.echo(f"\n{moved} note(s) {action}; {skipped} skipped.")
