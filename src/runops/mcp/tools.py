"""Domain tool implementations for the runops MCP provider."""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

from runops import __version__
from runops.core.context import build_project_context
from runops.core.discovery import discover_runs, resolve_run, validate_uniqueness
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, read_manifest
from runops.core.project import ProjectConfig, find_project_root, load_project
from runops.core.readiness import evaluate_run_readiness
from runops.core.state import RunState
from runops.mcp.registry import (
    capabilities_payload,
    exposed_tool_specs,
    tool_spec,
)
from runops.mcp.schemas import (
    CONTRACT_VERSION,
    EnvelopeStatus,
    blocked_envelope,
    envelope,
    error,
    now_iso,
    warning,
)
from runops.slurm.query import SlurmQueryError, query_job_status
from runops.slurm.submit import SlurmNotFoundError


def _tool_start() -> tuple[str, float]:
    return now_iso(), perf_counter()


def _path_from_arg(path: str | None) -> Path:
    return Path(path).expanduser().resolve() if path else Path.cwd().resolve()


def _resolve_project_root(project_root: str | None) -> Path:
    start = _path_from_arg(project_root)
    if (start / "runops.toml").exists():
        return start
    return find_project_root(start)


def _resolve_run_dir(run: str, project_root: Path) -> Path:
    candidate = Path(run).expanduser()
    if candidate.is_absolute() and (candidate / "manifest.toml").exists():
        return candidate.resolve()
    relative = (project_root / candidate).resolve()
    if (relative / "manifest.toml").exists():
        return relative
    cwd_relative = (Path.cwd() / candidate).resolve()
    if (cwd_relative / "manifest.toml").exists():
        return cwd_relative
    return resolve_run(run, project_root / "runs")


def _run_summary(
    run_dir: Path,
    manifest: ManifestData,
    project_root: Path,
) -> dict[str, Any]:
    tags = manifest.classification.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return {
        "run_id": str(manifest.run.get("id", run_dir.name)),
        "display_name": str(manifest.run.get("display_name", "")),
        "status": str(manifest.run.get("status", "unknown")),
        "path": str(run_dir),
        "relative_path": _relative_or_absolute(run_dir, project_root),
        "origin_case": str(manifest.origin.get("case", "")),
        "origin_survey": str(manifest.origin.get("survey", "")),
        "job_id": str(manifest.job.get("job_id", "")),
        "tags": [str(tag) for tag in tags],
    }


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _project_config_payload(project: ProjectConfig) -> dict[str, Any]:
    return {
        "name": project.name,
        "description": project.description,
        "root": str(project.root_dir),
        "simulators": sorted(project.simulators.keys()),
        "launchers": sorted(project.launchers.keys()),
        "knowledge_enabled": (
            project.knowledge.enabled if project.knowledge is not None else False
        ),
    }


def _find_latest_log(work_dir: Path, patterns: list[str]) -> Path | None:
    if not work_dir.is_dir():
        return None
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(path for path in work_dir.glob(pattern) if path.is_file())
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _tail_text(path: Path, lines: int) -> list[str]:
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return content[-lines:] if len(content) > lines else content


def health() -> dict[str, Any]:
    """Check the runops MCP server health."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.health")
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary="runops MCP server is healthy.",
        data={"healthy": True},
        started_at=started_at,
        started_perf=started_perf,
    )


def provider_info() -> dict[str, Any]:
    """Return provider metadata."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.provider.info")
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"runops {__version__} implements Ops MCP Contract {CONTRACT_VERSION}.",
        data={
            "provider": "runops",
            "provider_version": __version__,
            "contract_version": CONTRACT_VERSION,
            "supported_transports": ["stdio", "streamable-http"],
            "default_policy": {
                "read_enabled": True,
                "plan_enabled": True,
                "write_enabled": False,
                "external_enabled": False,
                "destructive_enabled": False,
            },
        },
        started_at=started_at,
        started_perf=started_perf,
    )


def capabilities() -> dict[str, Any]:
    """Return provider capabilities."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.capabilities")
    exposed_count = len(exposed_tool_specs())
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"runops exposes {exposed_count} read/inspect/plan tools.",
        data=capabilities_payload(),
        started_at=started_at,
        started_perf=started_perf,
    )


def project_list(project_root: str | None = None) -> dict[str, Any]:
    """List the current local runops project."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.project.list")
    inputs = {"project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        project = load_project(root)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="project_not_found",
            message=str(exc),
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Found project {project.name!r}.",
        data={"projects": [_project_config_payload(project)]},
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def project_status(project_root: str | None = None) -> dict[str, Any]:
    """Return a compact project status bundle."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.project.status")
    inputs = {"project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        context = build_project_context(root)
    except Exception as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="project_status_failed",
            message=str(exc),
            inputs=inputs,
        )

    runs = context.get("runs", {})
    total_runs = runs.get("total", 0) if isinstance(runs, dict) else 0
    status: EnvelopeStatus = "warning" if context.get("diagnostics") else "ok"
    summary = f"{total_runs} run(s); project status is {context.get('status', 'ok')}."
    warnings = [
        warning("diagnostic", str(item.get("message", "")))
        for item in context.get("diagnostics", [])
        if isinstance(item, dict)
    ]
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status=status,
        summary=summary,
        data={
            "project": context.get("project", {}),
            "status": context.get("status", "ok"),
            "runs": runs,
            "recent_failures": context.get("recent_failures", []),
            "section_status": context.get("section_status", {}),
        },
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def project_inspect(project_root: str | None = None) -> dict[str, Any]:
    """Return detailed project metadata and agent context."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.project.inspect")
    inputs = {"project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        project = load_project(root)
        context = build_project_context(root)
    except Exception as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="project_inspect_failed",
            message=str(exc),
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Project {project.name!r} inspected.",
        data={
            "project": _project_config_payload(project),
            "context": context,
        },
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def project_doctor(project_root: str | None = None) -> dict[str, Any]:
    """Diagnose project configuration without mutating files."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.project.doctor")
    inputs = {"project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="project_not_found",
            message=str(exc),
            inputs=inputs,
        )

    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, message: str, *, severity: str = "error") -> None:
        checks.append(
            {
                "name": name,
                "ok": ok,
                "message": message,
                "severity": "low" if ok else severity,
            }
        )

    try:
        project = load_project(root)
        add("runops.toml", True, f"Project config is valid: {project.name}")
    except SimctlError as exc:
        add("runops.toml", False, str(exc))

    add(
        "simulators.toml",
        (root / "simulators.toml").is_file(),
        "simulators.toml found"
        if (root / "simulators.toml").is_file()
        else "simulators.toml not found",
    )
    add(
        "launchers.toml",
        (root / "launchers.toml").is_file(),
        "launchers.toml found"
        if (root / "launchers.toml").is_file()
        else "launchers.toml not found",
    )
    add(
        "sbatch",
        shutil.which("sbatch") is not None,
        "sbatch is available"
        if shutil.which("sbatch") is not None
        else "sbatch not found in PATH",
        severity="medium",
    )
    try:
        validate_uniqueness(root / "runs")
        add("run_id_uniqueness", True, "No duplicate run_ids")
    except SimctlError as exc:
        add("run_id_uniqueness", False, str(exc))

    if (root / "campaign.toml").is_file():
        add("campaign.toml", True, "campaign.toml found")
    else:
        add("campaign.toml", True, "campaign.toml is optional and missing")

    failed = [check for check in checks if not check["ok"]]
    summary = "All checks passed." if not failed else f"{len(failed)} check(s) failed."
    status: EnvelopeStatus = "ok" if not failed else "warning"
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status=status,
        summary=summary,
        data={"checks": checks, "failed_count": len(failed)},
        project_root=root,
        warnings=[
            warning(str(check["name"]), str(check["message"]), severity="medium")
            for check in failed
        ],
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def run_list(
    project_root: str | None = None,
    status_filter: str | None = None,
    tag: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """List runs under a project."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.run.list")
    inputs = {
        "project_root": project_root,
        "status_filter": status_filter,
        "tag": tag,
        "limit": limit,
    }
    try:
        root = _resolve_project_root(project_root)
        run_dirs = discover_runs(root / "runs")
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="run_list_failed",
            message=str(exc),
            inputs=inputs,
        )

    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for run_dir in run_dirs:
        try:
            manifest = read_manifest(run_dir)
        except SimctlError:
            continue
        summary = _run_summary(run_dir, manifest, root)
        counts[str(summary["status"])] += 1
        if status_filter and summary["status"] != status_filter:
            continue
        if tag and tag not in summary["tags"]:
            continue
        rows.append(summary)

    rows.sort(key=lambda item: str(item["run_id"]))
    clipped = rows[: max(limit, 0)]
    warnings = []
    if len(rows) > len(clipped):
        warnings.append(
            warning(
                "result_limited",
                f"Returned {len(clipped)} of {len(rows)} matching runs.",
                severity="low",
            )
        )
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"{len(rows)} run(s) matched.",
        data={
            "runs": clipped,
            "matched_count": len(rows),
            "total_count": len(run_dirs),
            "state_counts": dict(counts),
        },
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def run_inspect(run: str, project_root: str | None = None) -> dict[str, Any]:
    """Inspect one run."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.run.inspect")
    inputs = {"run": run, "project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        run_dir = _resolve_run_dir(run, root)
        manifest = read_manifest(run_dir)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="run_inspect_failed",
            message=str(exc),
            inputs=inputs,
        )

    readiness: dict[str, Any] | None = None
    if manifest.run.get("status") == RunState.COMPLETED.value:
        try:
            details = evaluate_run_readiness(run_dir, manifest=manifest)
            readiness = {
                "analysis_status": details.analysis_status,
                "analysis_ready": details.analysis_ready,
                "missing_required_artifacts": list(details.missing_required_artifacts),
                "warnings": list(details.warnings),
            }
        except SimctlError:
            readiness = None

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Run {manifest.run.get('id', run_dir.name)} inspected.",
        data={
            "run": _run_summary(run_dir, manifest, root),
            "manifest": manifest.to_dict(),
            "readiness": readiness,
        },
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def run_logs(
    run: str,
    project_root: str | None = None,
    lines: int = 50,
    stderr: bool = False,
) -> dict[str, Any]:
    """Return tail lines from the latest run log."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.run.logs")
    inputs = {
        "run": run,
        "project_root": project_root,
        "lines": lines,
        "stderr": stderr,
    }
    try:
        root = _resolve_project_root(project_root)
        run_dir = _resolve_run_dir(run, root)
        manifest = read_manifest(run_dir)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="run_logs_failed",
            message=str(exc),
            inputs=inputs,
        )

    job_id = str(manifest.job.get("job_id", ""))
    if stderr:
        patterns = [f"stderr.{job_id}.log", f"*.{job_id}.err", "*.err", "stderr*"]
        stream = "stderr"
    else:
        patterns = [
            f"stdout.{job_id}.log",
            f"*.{job_id}.out",
            "*.out",
            "stdout*",
            "*.log",
        ]
        stream = "stdout"
    log_file = _find_latest_log(run_dir / "work", patterns)
    if log_file is None:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="log_not_found",
            message=(
                f"No {stream} log found for {manifest.run.get('id', run_dir.name)}."
            ),
            project_root=root,
            inputs=inputs,
        )

    safe_lines = max(1, min(lines, 500))
    try:
        tail = _tail_text(log_file, safe_lines)
    except OSError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="log_read_failed",
            message=str(exc),
            project_root=root,
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Last {len(tail)} line(s) from {log_file.name}.",
        data={
            "run_id": str(manifest.run.get("id", run_dir.name)),
            "stream": stream,
            "log_file": str(log_file),
            "lines": tail,
        },
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def slurm_queue(
    project_root: str | None = None,
    all_states: bool = False,
    live: bool = False,
) -> dict[str, Any]:
    """List Slurm job records known to project manifests."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.slurm.queue")
    inputs = {"project_root": project_root, "all_states": all_states, "live": live}
    try:
        root = _resolve_project_root(project_root)
        run_dirs = discover_runs(root / "runs")
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="slurm_queue_failed",
            message=str(exc),
            inputs=inputs,
        )

    active_states = {RunState.SUBMITTED.value, RunState.RUNNING.value}
    jobs: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        try:
            manifest = read_manifest(run_dir)
        except SimctlError:
            continue
        run_status = str(manifest.run.get("status", "unknown"))
        job_id = str(manifest.job.get("job_id", ""))
        if not all_states and run_status not in active_states:
            continue
        if not job_id and not all_states:
            continue
        job: dict[str, Any] = {
            "job_id": job_id,
            "run_id": str(manifest.run.get("id", run_dir.name)),
            "run_status": run_status,
            "run_dir": str(run_dir),
            "submitted_at": str(manifest.job.get("submitted_at", "")),
            "partition": str(
                manifest.job.get("partition", manifest.job.get("queue", ""))
            ),
            "qos": str(manifest.job.get("qos", "")),
            "last_slurm_state": str(manifest.run.get("last_slurm_state", "")),
        }
        if live and job_id:
            try:
                live_status = query_job_status(job_id)
                job["live_slurm_state"] = live_status.slurm_state
                job["live_run_state"] = live_status.run_state.value
            except (SlurmNotFoundError, SlurmQueryError) as exc:
                warnings.append(
                    warning(
                        "slurm_query_failed",
                        f"{job_id}: {exc}",
                        severity="medium",
                    )
                )
        jobs.append(job)

    jobs.sort(key=lambda item: str(item["run_id"]))
    active = sum(1 for job in jobs if job["run_status"] in active_states)
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="warning" if warnings else "ok",
        summary=f"{active} active job(s), {len(jobs)} listed.",
        data={"jobs": jobs, "active_count": active, "total_listed": len(jobs)},
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def slurm_job_inspect(job_id: str) -> dict[str, Any]:
    """Inspect a Slurm job through squeue/sacct."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.slurm.job.inspect")
    inputs = {"job_id": job_id}
    try:
        job_status = query_job_status(job_id)
    except (SlurmNotFoundError, SlurmQueryError) as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="slurm_job_query_failed",
            message=str(exc),
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Job {job_id} is {job_status.slurm_state}.",
        data={
            "job_id": job_id,
            "slurm_state": job_status.slurm_state,
            "run_state": job_status.run_state.value,
            "failure_reason": job_status.failure_reason,
            "exit_code": job_status.exit_code,
        },
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def job_plan_submit(
    run: str,
    project_root: str | None = None,
    queue_name: str | None = None,
    qos: str | None = None,
    afterok: str | None = None,
) -> dict[str, Any]:
    """Plan an sbatch submission command without submitting it."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.job.plan_submit")
    inputs = {
        "run": run,
        "project_root": project_root,
        "queue_name": queue_name,
        "qos": qos,
        "afterok": afterok,
    }
    try:
        root = _resolve_project_root(project_root)
        run_dir = _resolve_run_dir(run, root)
        manifest = read_manifest(run_dir)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="plan_submit_failed",
            message=str(exc),
            inputs=inputs,
        )

    preconditions: list[dict[str, Any]] = []

    def add_precondition(name: str, ok: bool, message: str) -> None:
        preconditions.append({"name": name, "ok": ok, "message": message})

    status = str(manifest.run.get("status", ""))
    add_precondition(
        "state_created",
        status == RunState.CREATED.value,
        f"run status is {status!r}",
    )
    job_script = run_dir / "submit" / "job.sh"
    add_precondition(
        "job_script_exists",
        job_script.is_file(),
        f"job script: {job_script}",
    )
    if job_script.is_file():
        try:
            job_text = job_script.read_text(encoding="utf-8")
            add_precondition(
                "job_script_has_sbatch",
                "#SBATCH" in job_text,
                "job.sh contains #SBATCH directives"
                if "#SBATCH" in job_text
                else "job.sh does not contain #SBATCH directives",
            )
        except OSError as exc:
            add_precondition("job_script_readable", False, str(exc))
    input_dir = run_dir / "input"
    input_ready = input_dir.is_dir() and any(input_dir.iterdir())
    add_precondition(
        "input_ready",
        input_ready,
        f"input directory: {input_dir}",
    )

    work_dir = run_dir / "work"
    if not work_dir.is_dir():
        work_dir = run_dir
    command = ["sbatch", f"--chdir={work_dir}"]
    if afterok:
        command.append(f"--dependency=afterok:{afterok}")
    if queue_name:
        command.append(f"--partition={queue_name}")
    if qos:
        command.append(f"--qos={qos}")
    command.append(str(job_script))

    failed = [item for item in preconditions if not item["ok"]]
    data = {
        "run_id": str(manifest.run.get("id", run_dir.name)),
        "run_dir": str(run_dir),
        "job_script": str(job_script),
        "work_dir": str(work_dir),
        "command": command,
        "preconditions": preconditions,
        "dry_run": True,
        "will_submit": not failed,
    }
    if failed:
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="blocked",
            summary=f"Submission plan is blocked by {len(failed)} precondition(s).",
            data=data,
            project_root=root,
            errors=[
                error(
                    "precondition_failed",
                    f"{item['name']}: {item['message']}",
                )
                for item in failed
            ],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Run {manifest.run.get('id', run_dir.name)} is ready to submit.",
        data=data,
        project_root=root,
        next_actions=[
            {
                "title": "Submit the planned job",
                "kind": "apply",
                "tool": "runops.job.submit",
                "arguments": {
                    "run": str(manifest.run.get("id", run_dir.name)),
                    "confirm": True,
                    "dry_run": False,
                },
                "requires_user": True,
            }
        ],
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )
