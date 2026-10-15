"""``runo`` command line (SPEC §7). Thin: parse, confirm, print; logic is in ``ops``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from runops import __version__, slurm
from runops.errors import RunopsError, UsageError
from runops.manifest import Manifest, RunState
from runops.project import Project
from runops.util import parse_age

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="runops: run ledger and Slurm submission for simulation projects.",
    pretty_exceptions_enable=False,
)
case_app = typer.Typer(no_args_is_help=True, help="Manage cases (input templates).")
app.add_typer(case_app, name="case")


def _version_callback(value: bool) -> None:
    if value:
        out.print(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print the version.",
    ),
) -> None:
    """runops: run ledger and Slurm submission for simulation projects."""


out = Console(highlight=False, soft_wrap=True)
err = Console(stderr=True, highlight=False, soft_wrap=True)


def _runner() -> slurm.CommandRunner:
    return slurm.default_runner


def _actor() -> str:
    if os.environ.get("RUNOPS_ACTOR"):
        return os.environ["RUNOPS_ACTOR"]
    if (
        os.environ.get("CLAUDECODE")
        or os.environ.get("CODEX_SANDBOX")
        or os.environ.get("CODEX_THREAD_ID")
    ):
        return "agent"
    return "human"


def _project() -> Project:
    project = Project.open()
    return project


def _print_json(data: Any) -> None:
    out.print_json(json.dumps(data, ensure_ascii=False, default=str))


def _warn(messages: list[str]) -> None:
    for message in messages:
        err.print(f"[yellow]warning:[/] {message}")


def _confirm(message: str, yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty():
        raise UsageError(f"{message} -- confirmation required; rerun with -y/--yes")
    if not typer.confirm(message, default=False):
        raise typer.Exit(1)


def _resolve(project: Project, refs: list[str]) -> list[Manifest]:
    if not refs:
        raise UsageError("give at least one RUN")
    return [project.resolve_run(ref) for ref in refs]


# ---------------------------------------------------------------------------
# project setup
# ---------------------------------------------------------------------------


@app.command()
def init(
    sims: Optional[list[str]] = typer.Argument(
        None, help="Simulators: NAME or NAME=package-spec (e.g. emses, beach, generic)."
    ),
    site: str = typer.Option("", "--site", help="Site preset: camphor | standard."),
    name: str = typer.Option("", "--name", help="Project name (default: directory name)."),
    no_install: bool = typer.Option(
        False, "--no-install", help="Do not create .venv or install packages."
    ),
    yes: bool = typer.Option(False, "-y", "--yes"),
) -> None:
    """Create a runops project in the current directory."""
    from runops.ops.setup import init_project

    sims = sims or []
    root = Path.cwd()
    if sims and not no_install and any(s.split("=")[0] != "generic" for s in sims):
        _confirm(f"Create .venv in {root} and install simulator packages?", yes)
    report = init_project(root, sims, site=site, name=name, install=not no_install)
    for item in report.created:
        out.print(f"created {item}")
    for spec in report.installed:
        out.print(f"installed {spec}")
    _warn(report.warnings)
    out.print(
        "next: start your agent (Codex / Claude Code) here and describe what to simulate; "
        "AGENTS.md and the runops skills tell it how to use runo."
    )


@app.command()
def doctor(as_json: bool = typer.Option(False, "--json")) -> None:
    """Check configuration, adapters, executables, Slurm and skills."""
    from runops.ops.setup import doctor as run_doctor

    checks = run_doctor(_project())
    if as_json:
        _print_json([c.__dict__ for c in checks])
    else:
        style = {"ok": "green", "warn": "yellow", "error": "red"}
        for c in checks:
            out.print(f"[{style[c.level]}]{c.level:5}[/] {c.topic}: {c.message}")
    if any(c.level == "error" for c in checks):
        raise typer.Exit(2)


@app.command()
def update(
    skills_only: bool = typer.Option(
        False, "--skills-only", help="Only redeploy skills and AGENTS.md block."
    ),
    yes: bool = typer.Option(False, "-y", "--yes"),
) -> None:
    """Upgrade simulator packages in .venv and redeploy skills."""
    from runops.ops.setup import update_project

    project = _project()
    if not skills_only:
        _confirm("Upgrade simulator packages in .venv?", yes)
    installed, warnings = update_project(project, skills_only=skills_only)
    for spec in installed:
        out.print(f"upgraded {spec}")
    _warn(warnings)
    out.print("skills and AGENTS.md block refreshed")


@app.command()
def build(
    sim: str = typer.Argument(..., help="Simulator name with resolver_mode = local_source."),
    force: bool = typer.Option(False, "--force", help="Rebuild even if the build exists."),
) -> None:
    """Build a local_source simulator into .runops/build/<sim>-<commit>."""
    from runops.runtime import build_simulator

    project = _project()
    target = build_simulator(project, project.config.simulator(sim), force=force)
    out.print(f"built {project.rel(target)}")


@app.command()
def context(as_json: bool = typer.Option(False, "--json")) -> None:
    """Where the project stands (for agents)."""
    from runops.ops.notes import project_context

    data = project_context(_project())
    if as_json:
        _print_json(data)
        return
    out.print(f"[bold]{data['project']}[/] ({data['root']}) runops {data['runops_version']}")
    sims = ", ".join(f"{k} ({v['adapter']})" for k, v in data["simulators"].items())
    out.print(f"simulators: {sims or '-'}")
    counts = ", ".join(f"{k}={v}" for k, v in sorted(data["status_counts"].items()))
    out.print(
        f"runs: {counts or 'none'}; active: {data['active_runs']}; "
        f"expired scratch: {data['expired_scratch']}"
    )
    for run in data["recent_runs"]:
        out.print(
            f"  {run['id']} {run['status']:9} {run['case']} {run['label']}  {run['why'][:60]}"
        )
    if data["notes_files"]:
        out.print("notes/: " + ", ".join(data["notes_files"]))
    if data["log_tail"]:
        out.print("--- LOG.md (tail) ---")
        out.print(data["log_tail"], markup=False)


# ---------------------------------------------------------------------------
# cases
# ---------------------------------------------------------------------------


@case_app.command("new")
def case_new(
    name: str = typer.Argument(...),
    simulator: str = typer.Option("", "--simulator", "-s"),
    from_case: str = typer.Option("", "--from", help="Copy an existing case."),
) -> None:
    """Scaffold cases/NAME from the adapter template (or copy --from CASE)."""
    from runops.ops.create import new_case

    project = _project()
    path = new_case(project, name, simulator, from_case)
    out.print(f"created {project.rel(path)}")


@case_app.command("list")
def case_list(as_json: bool = typer.Option(False, "--json")) -> None:
    """List cases."""
    from runops.ops.create import list_cases

    rows = list_cases(_project())
    if as_json:
        _print_json(rows)
        return
    table = Table("case", "simulator", "params", "description", box=None)
    for row in rows:
        table.add_row(
            row["name"],
            row["simulator"],
            str(row.get("params", "")),
            row["description"],
        )
    out.print(table)


# ---------------------------------------------------------------------------
# creating runs
# ---------------------------------------------------------------------------


def _print_created(project: Project, manifests: list[Manifest]) -> None:
    for m in manifests:
        out.print(f"created {m.id}  {project.rel(m.run_dir)}")


@app.command()
def new(
    case: Optional[str] = typer.Argument(None, help="Case name (omit with --from)."),
    from_run: str = typer.Option("", "--from", help="Derive from an existing run."),
    why: str = typer.Option("", "--why", help="The question this run answers."),
    label: str = typer.Option("", "--label"),
    sets: Optional[list[str]] = typer.Option(None, "--set", help="key=value parameter override."),
    tags: Optional[list[str]] = typer.Option(None, "--tag"),
    scratch: bool = typer.Option(False, "--scratch", help="Short-lived smoke/debug run."),
    dest: str = typer.Option("", "--dest", help="Parent directory under runs/."),
    continue_run: bool = typer.Option(
        False, "--continue", help="Continue from --from RUN (adapter support needed)."
    ),
    submit: bool = typer.Option(False, "--submit"),
    created_by: str = typer.Option("", "--created-by"),
) -> None:
    """Create one run."""
    from runops.ops.create import CreateRequest, create_run, parse_sets
    from runops.ops.submit import submit_run

    project = _project()
    if case and from_run:
        raise UsageError("give either CASE or --from RUN, not both")
    request = CreateRequest(
        case=case or "",
        sets=parse_sets(sets or []),
        why=why,
        label=label,
        tags=tags or [],
        scratch=scratch,
        dest=dest,
        created_by=created_by or _actor(),
        from_run=from_run,
        continue_run=continue_run,
    )
    result = create_run(project, request)
    _warn(result.warnings)
    if not why:
        _warn(["no --why given; consider `runo note RUN` to record the purpose"])
    _print_created(project, result.manifests)
    if submit:
        for m in result.manifests:
            job_id = submit_run(project, m, runner=_runner())
            out.print(f"submitted {m.id} as job {job_id}")


@app.command()
def sweep(
    case: str = typer.Argument(...),
    sets: Optional[list[str]] = typer.Option(
        None, "--set", help="key=v1,v2,... (product over all --set)."
    ),
    label: str = typer.Option("", "--label", help="Sweep label (directory under runs/<case>/)."),
    why: str = typer.Option("", "--why"),
    apply: bool = typer.Option(False, "--apply", help="Create the runs."),
    submit: bool = typer.Option(False, "--submit", help="Submit after --apply."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Only the first N points."),
    tags: Optional[list[str]] = typer.Option(None, "--tag"),
    created_by: str = typer.Option("", "--created-by"),
    as_json: bool = typer.Option(False, "--json"),
    yes: bool = typer.Option(False, "-y", "--yes"),
) -> None:
    """Preview (default) or create (--apply) a parameter product."""
    from runops.ops.create import (
        CreateRequest,
        apply_sweep,
        parse_sweep_sets,
        plan_sweep,
    )
    from runops.ops.submit import submit_run

    if submit and not apply:
        raise UsageError("--submit requires --apply")
    project = _project()
    plan = plan_sweep(project, case, parse_sweep_sets(sets or []), sweep_label=label, limit=limit)
    if as_json and not apply:
        _print_json(
            {
                "case": case,
                "sweep": plan.sweep_label,
                "parent": project.rel(plan.parent),
                "points": [
                    {"ref": p.ref, "label": p.label, "values": p.values} for p in plan.points
                ],
                "core_hours": plan.core_hours,
            }
        )
        return
    table = Table(
        "point",
        *(plan.points[0].values.keys() if plan.points else []),
        "label",
        box=None,
    )
    for p in plan.points:
        table.add_row(p.ref, *(str(v) for v in p.values.values()), p.label)
    out.print(table)
    out.print(
        f"{len(plan.points)} runs -> {project.rel(plan.parent)}/  "
        f"(~{plan.core_hours:.1f} core-hours)"
    )
    if not apply:
        out.print("preview only; add --apply to create")
        return
    if submit:
        _confirm(
            f"Create and submit {len(plan.points)} runs (~{plan.core_hours:.1f} core-hours)?",
            yes,
        )
    request = CreateRequest(case=case, why=why, tags=tags or [], created_by=created_by or _actor())
    result = apply_sweep(project, plan, request)
    _warn(result.warnings)
    _print_created(project, result.manifests)
    if submit:
        for m in result.manifests:
            job_id = submit_run(project, m, runner=_runner())
            out.print(f"submitted {m.id} as job {job_id}")


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


@app.command("submit")
def submit_cmd(
    runs: Optional[list[str]] = typer.Argument(None, help="Runs (or a directory with --all)."),
    all_runs: bool = typer.Option(
        False, "--all", help="Submit every created run under DIR (default runs/)."
    ),
    partition: str = typer.Option("", "--partition", "-p"),
    qos: str = typer.Option("", "--qos"),
    afterok: str = typer.Option("", "--afterok", help="Start after this job id succeeds."),
    yes: bool = typer.Option(False, "-y", "--yes"),
) -> None:
    """Generate job.sh and sbatch created runs."""
    from runops.ops.submit import SubmitOptions, estimate_core_hours, submit_run

    project = _project()
    if all_runs:
        if runs and len(runs) > 1:
            raise UsageError("--all takes at most one DIR")
        under = Path(runs[0]).resolve() if runs else project.runs_dir
        targets = [
            m
            for m in project.iter_runs(under)
            if m.status == RunState.CREATED and "_archive" not in m.run_dir.parts
        ]
        if not targets:
            out.print("no created runs")
            return
        hours = estimate_core_hours(project, targets)
        for m in targets:
            out.print(f"  {m.id}  {project.rel(m.run_dir)}")
        _confirm(f"Submit {len(targets)} runs (~{hours:.1f} core-hours)?", yes)
    else:
        targets = _resolve(project, runs or [])
        if len(targets) > 1:
            hours = estimate_core_hours(project, targets)
            _confirm(f"Submit {len(targets)} runs (~{hours:.1f} core-hours)?", yes)
    options = SubmitOptions(partition=partition, qos=qos, afterok=afterok)
    failures = 0
    for m in targets:
        try:
            job_id = submit_run(project, m, options, runner=_runner())
            out.print(f"submitted {m.id} as job {job_id}")
        except RunopsError as exc:
            failures += 1
            err.print(f"[red]error:[/] {exc}")
    if failures:
        raise typer.Exit(1)


@app.command()
def cancel(
    runs: list[str] = typer.Argument(...),
    yes: bool = typer.Option(False, "-y", "--yes"),
) -> None:
    """scancel submitted/running runs."""
    from runops.ops.submit import cancel_run

    project = _project()
    targets = _resolve(project, runs)
    _confirm("Cancel " + ", ".join(f"{m.id} (job {m.job_id})" for m in targets) + "?", yes)
    for m in targets:
        cancel_run(project, m, runner=_runner())
        out.print(f"cancelled {m.id}")


@app.command()
def retry(
    run: str = typer.Argument(...),
    submit: bool = typer.Option(False, "--submit"),
) -> None:
    """Reset a failed/cancelled run to created (work/ is kept)."""
    from runops.ops.submit import retry_run, submit_run

    project = _project()
    m = project.resolve_run(run)
    retry_run(project, m)
    out.print(f"{m.id} -> created")
    if submit:
        job_id = submit_run(project, m, runner=_runner())
        out.print(f"submitted {m.id} as job {job_id}")


def _status_table(project: Project, manifests: list[Manifest]) -> Table:
    from runops.ops.listing import relative_age

    table = Table("id", "status", "label", "case", "sweep", "created", "note", "why", box=None)
    for m in manifests:
        s = m.to_summary(project.root)
        color = {
            "completed": "green",
            "failed": "red",
            "running": "cyan",
            "submitted": "cyan",
            "cancelled": "yellow",
        }.get(s["status"], "")
        status = f"[{color}]{s['status']}[/]" if color else s["status"]
        if s["scratch"]:
            status += " [dim](scratch)[/]"
        if s["pinned"]:
            status += " [dim](pinned)[/]"
        table.add_row(
            s["id"],
            status,
            s["label"],
            s["case"],
            s["sweep"],
            relative_age(s["created_at"]),
            s["last_note"][:60],
            s["why"][:60],
        )
    return table


@app.command()
def status(
    runs: Optional[list[str]] = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show manifest state (no Slurm query). Without RUN: active runs."""
    from runops.manifest import ACTIVE_STATES

    project = _project()
    targets = (
        _resolve(project, runs)
        if runs
        else [m for m in project.iter_runs() if m.status in ACTIVE_STATES]
    )
    if as_json:
        data = []
        for m in targets:
            s = m.to_summary(project.root)
            s.update(
                {
                    "params": m.params,
                    "job": {k: v for k, v in m.job.items() if k != "attempts"},
                    "notes": m.notes,
                }
            )
            data.append(s)
        _print_json(data)
        return
    out.print(_status_table(project, targets))


@app.command("sync")
def sync_cmd(
    runs: Optional[list[str]] = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Update submitted/running runs from squeue/sacct."""
    from runops.ops.sync import sync_all

    project = _project()
    targets = _resolve(project, runs) if runs else None
    results = sync_all(project, targets, runner=_runner())
    if as_json:
        _print_json([r.__dict__ for r in results])
        return
    if not results:
        out.print("no active runs")
    for r in results:
        change = f"{r.before} -> {r.after}" if r.before != r.after else r.after
        extra = f"  ({r.message})" if r.message else ""
        out.print(f"{r.run_id}  {change}  {r.slurm_state}{extra}")


@app.command()
def log(
    run: str = typer.Argument(...),
    stderr: bool = typer.Option(False, "--err", help="Show stderr instead of stdout."),
    lines: int = typer.Option(50, "-n", help="Number of lines (0 = all)."),
    follow: bool = typer.Option(False, "-f", "--follow"),
) -> None:
    """Show the latest job's stdout/stderr."""
    from runops.ops.sync import read_log

    project = _project()
    m = project.resolve_run(run)
    path, text = read_log(m, stderr=stderr, lines=lines)
    err.print(f"[dim]{project.rel(path)}[/]")
    if follow:
        raise typer.Exit(subprocess.call(["tail", "-n", str(lines or 50), "-f", str(path)]))
    out.print(text, markup=False)


@app.command("list")
def list_cmd(
    path: Optional[Path] = typer.Argument(None, help="Limit to runs under this directory."),
    show_all: bool = typer.Option(False, "--all", help="Include old terminal runs."),
    since: str = typer.Option(
        "", "--since", help="Recent window, e.g. 30d (default from runops.toml)."
    ),
    cases: Optional[list[str]] = typer.Option(None, "--case"),
    sweeps: Optional[list[str]] = typer.Option(None, "--sweep"),
    statuses: Optional[list[str]] = typer.Option(None, "--status"),
    tags: Optional[list[str]] = typer.Option(None, "--tag"),
    scratch: bool = typer.Option(False, "--scratch", help="Also show scratch runs."),
    archived: bool = typer.Option(False, "--archived", help="Also show archived runs."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List active and recent runs."""
    from runops.ops.listing import ListFilter, select_runs

    project = _project()
    for s in statuses or []:
        if s not in {state.value for state in RunState}:
            raise UsageError(f"unknown status {s!r}")
    flt = ListFilter(
        path=path.resolve() if path else None,
        show_all=show_all,
        since=parse_age(since) if since else None,
        cases=cases or [],
        sweeps=sweeps or [],
        statuses=statuses or [],
        tags=tags or [],
        scratch=scratch,
        archived=archived,
    )
    runs = select_runs(project, flt)
    if as_json:
        _print_json([m.to_summary(project.root) for m in runs])
        return
    if not runs:
        out.print("no runs (try --all, --scratch, --archived)")
        return
    out.print(_status_table(project, runs))


@app.command()
def note(
    run: str = typer.Argument(...),
    text: Optional[str] = typer.Argument(None),
    by: str = typer.Option("", "--by"),
) -> None:
    """Append a note to a run, or show its notes."""
    from runops.ops.notes import add_note, read_notes

    project = _project()
    m = project.resolve_run(run)
    if text:
        add_note(m, text, by or _actor())
        out.print(f"noted on {m.id}")
        return
    data = read_notes(m)
    out.print(f"[bold]{m.id}[/] why: {data['why'] or '-'}")
    for n in data["notes"]:
        out.print(f"  {n.get('at', '')} [{n.get('by', '')}] {n.get('text', '')}", markup=False)
    if data["notes_md"]:
        out.print("--- notes.md ---")
        out.print(data["notes_md"], markup=False)


@app.command()
def pin(
    run: str = typer.Argument(...),
    off: bool = typer.Option(False, "--off", help="Unpin."),
    reason: str = typer.Option("", "--reason", help="Recorded as a note."),
) -> None:
    """Pin a run so list always shows it and tidy/delete never touch it."""
    project = _project()
    m = project.resolve_run(run)
    m.run["pinned"] = not off
    if reason:
        m.add_note(("unpin: " if off else "pin: ") + reason, _actor())
    m.save()
    out.print(f"{m.id} {'unpinned' if off else 'pinned'}")


@app.command()
def summarize(
    runs: list[str] = typer.Argument(...),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Write analysis/summary.json using the adapter's summarize()."""
    from runops.ops.notes import summarize_run

    project = _project()
    for m in _resolve(project, runs):
        written, payload = summarize_run(project, m, force=force)
        state = "wrote" if written else "exists (use --force)"
        out.print(f"{m.id}: {state} {project.rel(m.run_dir / 'analysis' / 'summary.json')}")
        if len(runs) == 1:
            _print_json(payload.get("summary", {}))


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


@app.command()
def archive(
    runs: Optional[list[str]] = typer.Argument(None),
    older_than: str = typer.Option(
        "", "--older-than", help="Archive completed runs older than this (e.g. 90d)."
    ),
    yes: bool = typer.Option(False, "-y", "--yes"),
) -> None:
    """Move terminal runs to runs/_archive/ (same relative path)."""
    from datetime import datetime

    from runops.ops.tidy import archive_run

    project = _project()
    if older_than:
        if runs:
            raise UsageError("give RUNs or --older-than, not both")
        cutoff = datetime.now().astimezone() - parse_age(older_than)
        targets = [
            m
            for m in project.iter_runs()
            if m.status == RunState.COMPLETED
            and not m.pinned
            and (m.created_datetime() or cutoff) < cutoff
        ]
    else:
        targets = _resolve(project, runs or [])
    if not targets:
        out.print("nothing to archive")
        return
    for m in targets:
        out.print(f"  {m.id}  {project.rel(m.run_dir)}")
    _confirm(f"Archive {len(targets)} runs?", yes)
    for m in targets:
        dst = archive_run(project, m)
        out.print(f"archived {m.id} -> {project.rel(dst)}")


@app.command()
def restore(run: str = typer.Argument(...)) -> None:
    """Move an archived run back to where it was."""
    from runops.ops.tidy import restore_run

    project = _project()
    m = project.resolve_run(run)
    dst = restore_run(project, m)
    out.print(f"restored {m.id} -> {project.rel(dst)}")


@app.command()
def delete(
    runs: list[str] = typer.Argument(...),
    yes: bool = typer.Option(False, "-y", "--yes"),
) -> None:
    """Delete created/failed/cancelled or scratch runs."""
    from runops.ops.tidy import check_deletable, delete_run

    project = _project()
    targets = _resolve(project, runs)
    for m in targets:
        check_deletable(m)
        out.print(f"  {m.id}  {m.status.value}  {project.rel(m.run_dir)}")
    _confirm(f"Delete {len(targets)} run directories permanently?", yes)
    for m in targets:
        delete_run(project, m)
        out.print(f"deleted {m.id}")


@app.command()
def tidy(
    apply: bool = typer.Option(False, "--apply"),
    only: Optional[list[str]] = typer.Option(None, "--only", help="Restrict to a kind."),
    older_than: str = typer.Option(
        "",
        "--older-than",
        help="Use this age (e.g. 14d) for both thresholds instead of "
        "[defaults].tidy_failed_days / tidy_archive_days.",
    ),
    purge_work: Optional[list[str]] = typer.Option(
        None,
        "--purge-work",
        help="Empty work/ of completed RUN (keeps adapter keep patterns).",
    ),
    as_json: bool = typer.Option(False, "--json"),
    yes: bool = typer.Option(False, "-y", "--yes"),
) -> None:
    """List cleanup candidates; --apply performs them."""
    from runops.ops.tidy import (
        KINDS,
        apply_candidates,
        find_candidates,
    )
    from runops.ops.tidy import (
        purge_work as do_purge,
    )

    project = _project()
    if purge_work:
        targets = _resolve(project, purge_work)
        _confirm("Delete work/ contents of " + ", ".join(m.id for m in targets) + "?", yes)
        for m in targets:
            removed = do_purge(project, m)
            out.print(f"{m.id}: removed {len(removed)} files from work/")
        return
    for kind in only or []:
        if kind not in KINDS:
            raise UsageError(f"unknown kind {kind!r}; known: {', '.join(KINDS)}")
    override = parse_age(older_than) if older_than else None
    candidates = find_candidates(
        project, failed_after=override, archive_after=override, runner=_runner()
    )
    if only:
        candidates = [c for c in candidates if c.kind in only]
    if as_json and not apply:
        _print_json([c.__dict__ for c in candidates])
        return
    if not candidates:
        out.print("nothing to tidy")
        return
    table = Table("kind", "target", "path", "reason", box=None)
    for c in candidates:
        table.add_row(c.kind, c.target, c.path, c.reason)
    out.print(table)
    if not apply:
        out.print("preview only; add --apply (optionally --only KIND) to perform")
        return
    _confirm(f"Apply {len(candidates)} actions?", yes)
    report = apply_candidates(project, candidates, runner=_runner())
    for item in report.applied:
        out.print(f"done {item}")
    for item in report.errors:
        err.print(f"[red]error:[/] {item}")
    if report.errors:
        raise typer.Exit(1)


@app.command("migrate-v1")
def migrate_v1(
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show the plan."),
    delete_test_runs: bool = typer.Option(
        False, "--apply-delete-test-runs", help="Also delete .runops/test-runs/."
    ),
    yes: bool = typer.Option(False, "-y", "--yes"),
) -> None:
    """Convert a runops v1 project in the current directory to v2."""
    from runops.ops.migrate import apply_plan, plan_migration

    root = Path.cwd()
    plan = plan_migration(root)
    for line in plan.describe():
        out.print(line, markup=False)
    if dry_run:
        return
    _confirm("Apply this migration?", yes)
    for line in apply_plan(plan, delete_test_runs=delete_test_runs):
        out.print(line, markup=False)


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    try:
        code = app(args=argv, standalone_mode=False)
    except RunopsError as exc:
        err.print(f"[red]error:[/] {exc}", markup=True)
        sys.exit(exc.exit_code)
    except typer.Exit as exc:
        sys.exit(exc.exit_code)
    except typer.Abort:
        err.print("aborted")
        sys.exit(1)
    except Exception as exc:  # click usage errors
        import click

        if isinstance(exc, click.ClickException):
            exc.show()
            sys.exit(2)
        raise
    if isinstance(code, int) and code:
        sys.exit(code)
