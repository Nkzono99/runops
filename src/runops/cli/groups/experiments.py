"""Experiment command-group composition."""

from __future__ import annotations

import typer

from runops.cli.experiments import (
    close,
    create,
    inspect,
    list_experiments,
    review,
)

experiments_app = typer.Typer(
    name="experiments",
    help="Bounded research-question admission and review.",
)
experiments_app.command("create")(create)
experiments_app.command("list")(list_experiments)
experiments_app.command("inspect")(inspect)
experiments_app.command("review")(review)
experiments_app.command("close")(close)

__all__ = ["experiments_app"]
