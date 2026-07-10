"""Lab-notebook command-group composition."""

from __future__ import annotations

import typer

from runops.cli.notes import append, archive, list_notes, show

notes_app = typer.Typer(
    name="notes",
    help="Lab notebook commands (notes/YYYY-MM-DD.md).",
)
notes_app.command("append")(append)
notes_app.command("list")(list_notes)
notes_app.command("show")(show)
notes_app.command("archive")(archive)

__all__ = ["notes_app"]
