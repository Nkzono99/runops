"""Experiment command-group composition."""

from __future__ import annotations

import typer

from runops.cli.experiment import check_experiment, new_experiment, show_experiment

experiment_app = typer.Typer(
    name="experiment",
    help="Typed scientific experiment planning and readiness commands.",
)
experiment_app.command("new")(new_experiment)
experiment_app.command("show")(show_experiment)
experiment_app.command("check")(check_experiment)

__all__ = ["experiment_app"]
