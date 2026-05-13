"""Main CLI application entry point."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from runops import __version__
from runops.cli.analyze import collect, export, new_comparison, plot, summarize
from runops.cli.clone import clone
from runops.cli.config import config_app
from runops.cli.context import context
from runops.cli.create import create, sweep
from runops.cli.dashboard import dashboard
from runops.cli.demo import demo_app
from runops.cli.extend import extend
from runops.cli.history import history
from runops.cli.init import doctor, init
from runops.cli.jobs import jobs
from runops.cli.knowledge import knowledge_app
from runops.cli.lint import lint
from runops.cli.list import list_runs
from runops.cli.log import log
from runops.cli.manage import archive, cancel, delete, purge_work
from runops.cli.mcp import mcp_app
from runops.cli.migrate import migrate_app
from runops.cli.new import new
from runops.cli.notes import append as notes_append
from runops.cli.notes import archive as notes_archive
from runops.cli.notes import list_notes as notes_list
from runops.cli.notes import show as notes_show
from runops.cli.regenerate import regenerate
from runops.cli.retry import retry
from runops.cli.setup import setup
from runops.cli.status import status, sync
from runops.cli.submit import run_cmd
from runops.cli.update import update
from runops.cli.update_harness import update_harness
from runops.cli.update_notice import maybe_emit_update_notice
from runops.cli.update_refs import update_refs
from runops.core.event_log import (
    EVENT_LOG_ENV_VAR,
    configure_event_logging,
    emit_event,
)

case_app = typer.Typer(
    name="case",
    help="Case template commands.",
)
case_app.command("new")(new)

runs_app = typer.Typer(
    name="runs",
    help="Run lifecycle, survey expansion, and run listing commands.",
)
runs_app.command("create")(create)
runs_app.command("sweep")(sweep)
runs_app.command("submit")(run_cmd)
runs_app.command("status")(status)
runs_app.command("sync")(sync)
runs_app.command("log")(log)
runs_app.command("list")(list_runs)
runs_app.command("jobs")(jobs)
runs_app.command("history")(history)
runs_app.command("dashboard")(dashboard)
runs_app.command("clone")(clone)
runs_app.command("extend")(extend)
runs_app.command("archive")(archive)
runs_app.command("purge-work")(purge_work)
runs_app.command("cancel")(cancel)
runs_app.command("delete")(delete)
runs_app.command("retry")(retry)
runs_app.command("regenerate")(regenerate)

analyze_app = typer.Typer(
    name="analyze",
    help="Analysis and reporting commands for runs and surveys.",
)
analyze_app.command("summarize")(summarize)
analyze_app.command("collect")(collect)
analyze_app.command("plot")(plot)
analyze_app.command("export")(export)
analyze_app.command("new-comparison")(new_comparison)

notes_app = typer.Typer(
    name="notes",
    help="Lab notebook commands (notes/YYYY-MM-DD.md).",
)
notes_app.command("append")(notes_append)
notes_app.command("list")(notes_list)
notes_app.command("show")(notes_show)
notes_app.command("archive")(notes_archive)


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
            summary=f"{name} {' '.join(sys.argv[1:])}".strip(),
            data={
                "program": name,
                "argv": sys.argv[1:],
            },
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
    cli_app.command("lint")(lint)
    cli_app.add_typer(case_app, name="case")
    cli_app.add_typer(runs_app, name="runs")
    cli_app.add_typer(analyze_app, name="analyze")
    cli_app.add_typer(demo_app, name="demo")
    cli_app.add_typer(notes_app, name="notes")
    cli_app.add_typer(migrate_app, name="migrate")
    cli_app.command("update")(update)
    cli_app.command("update-harness")(update_harness)
    cli_app.command("update-refs")(update_refs)
    return cli_app


app = _build_app("runo")
runops_app = _build_app("runops")

if __name__ == "__main__":
    app()
