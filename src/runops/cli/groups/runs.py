"""Run lifecycle command-group composition."""

from __future__ import annotations

import typer

from runops.cli.clone import clone
from runops.cli.create import create, sweep
from runops.cli.dashboard import dashboard
from runops.cli.extend import extend
from runops.cli.history import history
from runops.cli.jobs import jobs
from runops.cli.list import list_runs
from runops.cli.log import log
from runops.cli.manage import archive, cancel, delete, purge_work, restore
from runops.cli.regenerate import regenerate
from runops.cli.relabel import relabel
from runops.cli.retry import retry
from runops.cli.status import status, sync
from runops.cli.submit import run_cmd

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
runs_app.command("restore")(restore)
runs_app.command("purge-work")(purge_work)
runs_app.command("cancel")(cancel)
runs_app.command("delete")(delete)
runs_app.command("retry")(retry)
runs_app.command("regenerate")(regenerate)
runs_app.command("relabel")(relabel)

__all__ = ["runs_app"]
