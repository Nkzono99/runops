"""Case command-group composition."""

from __future__ import annotations

import typer

from runops.cli.new import new

case_app = typer.Typer(name="case", help="Case template commands.")
case_app.command("new")(new)

__all__ = ["case_app"]
