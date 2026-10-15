"""``sync``, ``status``, ``log`` (SPEC §6.3, §7.3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from runops.errors import RunopsError, UsageError
from runops.manifest import ACTIVE_STATES, Manifest, RunState
from runops.ops.common import run_sim_context
from runops.project import Project
from runops.slurm import CommandRunner, default_runner, query
from runops.util import now_iso


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
    before = manifest.status
    if before not in ACTIVE_STATES:
        return SyncResult(manifest.id, before.value, before.value, "", "not active")
    if not manifest.job_id:
        return SyncResult(manifest.id, before.value, before.value, "", "no job id")
    job = query(manifest.job_id, runner=runner)
    if job is None:
        new_state = _adapter_verdict(project, manifest, RunState.COMPLETED, orphan=True)
        message = "job not found in squeue/sacct; state decided from outputs"
        slurm_state = "UNKNOWN"
    else:
        slurm_state = job.slurm_state
        message = ""
        new_state = job.state
        if new_state == RunState.COMPLETED:
            new_state = _adapter_verdict(project, manifest, RunState.COMPLETED)
            if new_state == RunState.FAILED:
                message = "Slurm COMPLETED but adapter reports failure"
        if job.exit_code:
            manifest.job["exit_code"] = job.exit_code
    manifest.job["last_slurm_state"] = slurm_state
    attempts = manifest.job.get("attempts") or []
    if attempts:
        attempts[-1]["slurm_state"] = slurm_state
    if new_state not in ACTIVE_STATES:
        now = now_iso()
        manifest.job["finished_at"] = now
        if attempts:
            attempts[-1]["finished_at"] = now
    manifest.set_status(new_state)
    manifest.save()
    return SyncResult(manifest.id, before.value, new_state.value, slurm_state, message)


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
    return [sync_run(project, m, runner=runner) for m in targets]


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
