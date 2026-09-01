"""TestAttempt command-group composition."""

from __future__ import annotations

import typer

from runops.cli.test_attempts import clean, debug, list_attempts, record, smoke

tests_app = typer.Typer(
    name="test",
    help="Isolated smoke/debug attempts that never consume normal Run IDs.",
)
tests_app.command("smoke")(smoke)
tests_app.command("debug")(debug)
tests_app.command("list")(list_attempts)
tests_app.command("record")(record)
tests_app.command("clean")(clean)

__all__ = ["tests_app"]
