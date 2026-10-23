"""``sync``, ``status``, ``log`` (SPEC §6.3, §7.3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from runops.errors import RunopsError, UsageError
from runops.jobgen import exit_record_path
from runops.manifest import ACTIVE_STATES, Manifest, RunState
from runops.ops.common import run_sim_context
from runops.ops.progress import record_progress
from runops.project import Project
from runops.slurm import CommandRunner, JobState, default_runner, query, query_many
from runops.util import format_duration, load_toml, now_iso, parse_duration, parse_iso, tomllib


@dataclass
class SyncResult:
    run_id: str
    before: str
    after: str
    slurm_state: str
    message: str = ""


def sync_run(
    project: Project,
    manifest: Manifest,
    *,
    runner: CommandRunner = default_runner,
) -> SyncResult:
    if manifest.status not in ACTIVE_STATES or not manifest.job_id:
        return _apply_state(project, manifest, None)
    return _apply_state(project, manifest, query(manifest.job_id, runner=runner))


def _apply_state(project: Project, manifest: Manifest, job: JobState | None) -> SyncResult:
    """Settle *manifest* under :meth:`Project.run_lock` from a fresh copy of the file.

    *job* was queried for the job id the caller saw; if a concurrent submit or
    retry changed it meanwhile, the run is left for the next sync.
    """
    with project.run_lock():
        queried = manifest.job_id
        manifest.reload()
        if manifest.job_id != queried:
            status = manifest.status.value
            return SyncResult(manifest.id, status, status, "", "job changed while syncing")
        return _settle(project, manifest, job)


def _settle(project: Project, manifest: Manifest, job: JobState | None) -> SyncResult:
    """Settle *manifest* from the Slurm state *job* (``None`` = unknown to Slurm).

    Precedence for a job Slurm no longer reports: the exit record job.sh wrote
    (``submit/exit.<job_id>``), then the adapter's ``detect_status``, then failed.
    """
    before = manifest.status
    if before not in ACTIVE_STATES:
        return SyncResult(manifest.id, before.value, before.value, "", "not active")
    if not manifest.job_id:
        return SyncResult(manifest.id, before.value, before.value, "", "no job id")
    record = read_exit_record(manifest.run_dir, manifest.job_id)
    message = ""
    if job is None:
        slurm_state = "UNKNOWN"
        if record is None:
            new_state = _adapter_verdict(project, manifest, RunState.COMPLETED, orphan=True)
            message = "job not found in squeue/sacct; state decided from outputs"
        elif record["exit_code"] == 0:
            new_state = _adapter_verdict(project, manifest, RunState.COMPLETED)
            message = "job not found in squeue/sacct; state from exit record"
        else:
            new_state = RunState.FAILED
            message = f"job not found in squeue/sacct; exit record says exit={record['exit_code']}"
    elif job.state is None:
        manifest.job["last_slurm_state"] = job.slurm_state
        manifest.save()
        return SyncResult(
            manifest.id,
            before.value,
            before.value,
            job.slurm_state,
            f"unrecognized Slurm state {job.slurm_state!r}; left {before.value}",
        )
    else:
        slurm_state = job.slurm_state
        new_state = job.state
        if new_state == RunState.COMPLETED:
            new_state = _adapter_verdict(project, manifest, RunState.COMPLETED)
            if new_state == RunState.FAILED:
                message = "Slurm COMPLETED but adapter reports failure"
        if job.exit_code:
            manifest.job["exit_code"] = job.exit_code
    if record is not None and record["stage"] == "setup":
        message = f"job setup failed before the program started (exit={record['exit_code']})"
    attempts = manifest.job.get("attempts") or []
    if record is not None:
        manifest.job.setdefault("exit_code", str(record["exit_code"]))
        if attempts:
            attempts[-1]["exit_code"] = record["exit_code"]
            attempts[-1]["started_at"] = record["started_at"]
    manifest.job["last_slurm_state"] = slurm_state
    if attempts:
        attempts[-1]["slurm_state"] = slurm_state
    if new_state not in ACTIVE_STATES:
        now = (record or {}).get("finished_at") or now_iso()
        manifest.job["finished_at"] = now
        if attempts:
            attempts[-1]["finished_at"] = now
            elapsed = _elapsed(job, record)
            if elapsed:
                attempts[-1]["elapsed"] = elapsed
        # The last sample is dated at the finish, so the rate ends where the job did.
        record_progress(
            project, manifest, at=parse_iso(now) or datetime.now().astimezone(), final=True
        )
    elif new_state == RunState.RUNNING:
        record_progress(project, manifest, at=datetime.now().astimezone())
    manifest.set_status(new_state)
    manifest.save()
    return SyncResult(manifest.id, before.value, new_state.value, slurm_state, message)


def _elapsed(job: JobState | None, record: dict[str, Any] | None) -> str:
    """Run time of the attempt: sacct ``Elapsed``, else the exit record's start/end."""
    seconds = parse_duration(job.elapsed) if job is not None and job.elapsed else None
    if seconds is None and record is not None:
        start, end = parse_iso(record["started_at"]), parse_iso(record["finished_at"])
        if start and end and end >= start:
            seconds = int((end - start).total_seconds())
    return format_duration(seconds) if seconds is not None else ""


def read_exit_record(run_dir: Path, job_id: str) -> dict[str, Any] | None:
    """Parse ``submit/exit.<job_id>``; ``None`` if absent or unreadable."""
    path = exit_record_path(run_dir, job_id)
    try:
        data = load_toml(path)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    try:
        code = int(data.get("exit_code", ""))
    except (TypeError, ValueError):
        return None
    return {
        "exit_code": code,
        "started_at": str(data.get("started_at", "")),
        "finished_at": str(data.get("finished_at", "")),
        "hostname": str(data.get("hostname", "")),
        "stage": str(data.get("stage", "")),
    }


def _adapter_verdict(
    project: Project, manifest: Manifest, default: RunState, *, orphan: bool = False
) -> RunState:
    try:
        ctx = run_sim_context(project, manifest)
        verdict = str(ctx.adapter.detect_status(manifest.run_dir))
    except RunopsError:
        verdict = "unknown"
    if verdict == "failed":
        return RunState.FAILED
    if verdict == "completed":
        return RunState.COMPLETED
    return RunState.FAILED if orphan else default


def sync_all(
    project: Project,
    manifests: list[Manifest] | None = None,
    *,
    runner: CommandRunner = default_runner,
) -> list[SyncResult]:
    targets = (
        manifests
        if manifests is not None
        else [m for m in project.iter_runs() if m.status in ACTIVE_STATES]
    )
    # One squeue + one sacct for every run, however many are active.
    states = query_many(
        [m.job_id for m in targets if m.status in ACTIVE_STATES and m.job_id], runner=runner
    )
    return [_apply_state(project, m, states.get(m.job_id)) for m in targets]


def log_paths(manifest: Manifest) -> tuple[Path | None, Path | None]:
    """Find stdout/stderr files of the latest job in ``work/``."""
    work = manifest.run_dir / "work"
    if not work.is_dir():
        return None, None
    job_id = manifest.job_id
    files = [p for p in work.iterdir() if p.is_file()]
    if job_id:
        tagged = [p for p in files if job_id in p.name]
        if tagged:
            files = tagged
    out = [p for p in files if _is_stdout(p.name)]
    err = [p for p in files if _is_stderr(p.name)]

    def newest(paths: list[Path]) -> Path | None:
        return max(paths, key=lambda p: p.stat().st_mtime) if paths else None

    return newest(out), newest(err)


def _is_stdout(name: str) -> bool:
    return name.endswith(".out") or name.startswith("stdout")


def _is_stderr(name: str) -> bool:
    return name.endswith(".err") or name.startswith("stderr")


def read_log(manifest: Manifest, *, stderr: bool = False, lines: int = 50) -> tuple[Path, str]:
    out, err = log_paths(manifest)
    path = err if stderr else out
    if path is None:
        kind = "stderr" if stderr else "stdout"
        raise UsageError(f"{manifest.id}: no {kind} file found in work/")
    text = path.read_text(errors="replace").splitlines()
    return path, "\n".join(text[-lines:]) if lines > 0 else "\n".join(text)
