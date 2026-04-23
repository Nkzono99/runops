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
    typer.echo(f"Appended to {display}")


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

    files = sorted(
        (p for p in target_dir.glob("*.md") if p.stem != "README"),
        key=lambda p: p.stem,
        reverse=True,
    )
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
            rel = str(path.relative_to(Path.cwd()))
        except ValueError:
            rel = str(path)
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
        files = sorted(
            (p for p in target_dir.glob("*.md") if p.stem != "README"),
            key=lambda p: p.stem,
            reverse=True,
        )
        if not files:
            typer.echo("No notes yet.")
            raise typer.Exit(code=1)
        path = files[0]
    else:
        date_str: str = date
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError as exc:
            typer.echo(f"Error: invalid date '{date_str}': {exc}", err=True)
            raise typer.Exit(code=2) from None
        path = target_dir / f"{date_str}.md"

    if not path.is_file():
        typer.echo(f"No notes for {path.stem}.")
        raise typer.Exit(code=1)

    typer.echo(path.read_text(encoding="utf-8"), nl=False)
