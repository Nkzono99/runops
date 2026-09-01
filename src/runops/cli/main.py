"""Main CLI application entry point."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from runops import __version__
from runops.cli.config import config_app
from runops.cli.context import context
from runops.cli.demo import demo_app
from runops.cli.groups import (
    analyze_app,
    case_app,
    experiments_app,
    research_app,
    runs_app,
    tests_app,
)
from runops.cli.init import doctor, init
from runops.cli.knowledge import knowledge_app
from runops.cli.lint import lint
from runops.cli.mcp import mcp_app
from runops.cli.migrate import migrate_app
from runops.cli.plugins import plugins
from runops.cli.setup import setup
from runops.cli.triage import triage
from runops.cli.update import update
from runops.cli.update_harness import update_harness
from runops.cli.update_notice import maybe_emit_update_notice
from runops.cli.update_refs import update_refs
from runops.core.event_log import (
    EVENT_LOG_ENV_VAR,
    configure_event_logging,
    emit_event,
)


def _build_app(name: str) -> typer.Typer:
    """Build a top-level CLI app with the given executable name."""
    cli_app = typer.Typer(
        name=name,
        help=(
            "RunOps HPC simulation run management CLI. "
            "Preferred command: runo. Stable alias: runops."
        ),
        no_args_is_help=True,
        invoke_without_command=True,
    )

    @cli_app.callback()
    def _configure_logging(
        event_log: Annotated[
            Path | None,
            typer.Option(
                "--event-log",
                help=(
                    "Write structured JSONL events for this CLI invocation. "
                    f"Can also be set via {EVENT_LOG_ENV_VAR}."
                ),
            ),
        ] = None,
        event_log_mode: Annotated[
            str | None,
            typer.Option(
                "--event-log-mode",
                help=(
                    "Event log verbosity: off, summary-only, or verbose. "
                    "Defaults to summary-only when event logging is enabled."
                ),
                case_sensitive=False,
            ),
        ] = None,
        version: Annotated[
            bool,
            typer.Option(
                "--version",
                help="Show the runops package version and exit.",
                is_eager=True,
            ),
        ] = False,
    ) -> None:
        """Configure optional structured event logging for the current command."""
        if version:
            typer.echo(f"{name} {__version__}")
            raise typer.Exit()

        try:
            configure_event_logging(event_log, mode=event_log_mode, actor=name)
        except ValueError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint="--event-log-mode",
            ) from exc

        emit_event(
            "cli_invocation",
            summary=f"{name} CLI invocation",
            data={"program": name},
        )
        maybe_emit_update_notice(
            program=name,
            argv=sys.argv[1:],
            current_version=__version__,
        )

    cli_app.command("init")(init)
    cli_app.command("setup")(setup)
    cli_app.command("doctor")(doctor)
    cli_app.add_typer(config_app, name="config")
    cli_app.add_typer(knowledge_app, name="knowledge")
    cli_app.add_typer(mcp_app, name="mcp")
    cli_app.command("context")(context)
    cli_app.command("plugins")(plugins)
    cli_app.command("lint")(lint)
    cli_app.command("triage")(triage)
    cli_app.add_typer(case_app, name="case")
    cli_app.add_typer(experiments_app, name="experiments")
    cli_app.add_typer(runs_app, name="runs")
    cli_app.add_typer(tests_app, name="test")
    cli_app.add_typer(analyze_app, name="analyze")
    cli_app.add_typer(demo_app, name="demo")
    cli_app.add_typer(research_app, name="research")
    cli_app.add_typer(migrate_app, name="migrate")
    cli_app.command("update")(update)
    cli_app.command("update-harness")(update_harness)
    cli_app.command("update-refs")(update_refs)
    return cli_app


app = _build_app("runo")
runops_app = _build_app("runops")

if __name__ == "__main__":
    app()
