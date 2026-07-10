"""Analysis command-group composition."""

from __future__ import annotations

import typer

from runops.cli.analyze import (
    audit_story,
    collect,
    export,
    new_comparison,
    new_story,
    plot,
    summarize,
)

analyze_app = typer.Typer(
    name="analyze",
    help="Analysis and reporting commands for runs and surveys.",
)
analyze_app.command("summarize")(summarize)
analyze_app.command("collect")(collect)
analyze_app.command("plot")(plot)
analyze_app.command("export")(export)
analyze_app.command("new-comparison")(new_comparison)
analyze_app.command("new-story")(new_story)
analyze_app.command("audit-story")(audit_story)

__all__ = ["analyze_app"]
