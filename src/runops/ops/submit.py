"""``submit``, ``cancel``, ``retry`` and job.sh writing (SPEC §6.3, §7.3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runops.adapters.base import exe_str
from runops.adapters.registry import optional
from runops.case import core_hours
from runops.errors import RunError, UsageError
from runops.jobgen import render_job_script, write_job_script
from runops.manifest import ACTIVE_STATES, Manifest, RunState
from runops.ops.common import SimContext, run_sim_context
from runops.project import Project
from runops.slurm import CommandRunner, default_runner, sbatch, scancel
from runops.util import hash_file, now_iso


def write_job_for(project: Project, manifest: Manifest, *, ctx: SimContext | None = None) -> Path:
    """(Re)generate ``submit/job.sh`` from the manifest's recorded job and executable."""
    ctx = ctx or run_sim_context(project, manifest)
    launcher_name = str(manifest.section("launcher").get("name", ""))
    launcher = project.config.launcher(launcher_name)
    sim_section = manifest.section("simulator")
    from runops.adapters.base import RuntimeInfo

    runtime = RuntimeInfo(
        executable=Path(str(sim_section.get("executable", ""))),
        package_version=str(sim_section.get("package_version", "")),
        exe_hash=str(sim_section.get("exe_hash", "")),
        git_commit=str(sim_section.get("git_commit", "")),
        git_dirty=bool(sim_section.get("git_dirty", False)),
        resolver_mode=str(sim_section.get("resolver_mode", "")),
    )
    run_dir = manifest.run_dir.resolve()
    program = list(ctx.adapter.build_command(runtime, run_dir))
    prelude = [str(x) for x in optional(ctx.adapter, "job_prelude", [], run_dir) or []]
    activate = project.venv_dir / "bin" / "activate"
    content = render_job_script(
        run_dir=run_dir,
        run_id=manifest.id,
        job=_job_config(manifest),
        site=project.config.site,
        launcher=launcher,
        sim=ctx.sim,
        program=program,
        prelude=prelude,
        venv_activate=activate if activate.is_file() else None,
    )
    return write_job_script(run_dir, content)


_RUNTIME_JOB_KEYS = {
    "scheduler",
    "job_id",
    "attempt",
    "attempts",
    "submitted_at",
    "finished_at",
    "last_slurm_state",
    "exit_code",
}


def _job_config(manifest: Manifest) -> dict[str, Any]:
    return {k: v for k, v in manifest.job.items() if k not in _RUNTIME_JOB_KEYS}


def estimate_core_hours(project: Project, manifests: list[Manifest]) -> float:
    style = project.config.site.resource_style
    return sum(core_hours(_job_config(m), style) for m in manifests)


@dataclass
class SubmitOptions:
    partition: str = ""
    qos: str = ""
    afterok: str = ""


def submit_run(
    project: Project,
    manifest: Manifest,
    options: SubmitOptions | None = None,
    *,
    runner: CommandRunner = default_runner,
    warnings: list[str] | None = None,
) -> str:
    """sbatch *manifest*; returns the job id. Warnings are appended to *warnings*.

    The manifest is re-read under :meth:`Project.run_lock`, so a run given twice
    (or submitted by two processes at once) is sbatch'ed only once.
    """
    with project.run_lock():
        manifest.reload()
        return _submit_locked(project, manifest, options or SubmitOptions(), runner, warnings)


def _submit_locked(
    project: Project,
    manifest: Manifest,
    options: SubmitOptions,
    runner: CommandRunner,
    warnings: list[str] | None,
) -> str:
    if manifest.status != RunState.CREATED:
        raise UsageError(
            f"{manifest.id} is {manifest.status.value}; only created runs can be "
            "submitted (use `runo retry` for failed/cancelled runs)"
        )
    if options.partition:
        manifest.job["partition"] = options.partition
    if options.qos:
        manifest.job["qos"] = options.qos
    manifest.save()
    job_sh = write_job_for(project, manifest)
    extra = [f"--dependency=afterok:{options.afterok}"] if options.afterok else []
    work = manifest.run_dir.resolve() / "work"
    work.mkdir(exist_ok=True)
    log_path = manifest.run_dir / "submit" / "sbatch.log"
    try:
        job_id, result = sbatch(job_sh, work, extra=extra, runner=runner)
    except RunError as exc:
        _append(log_path, f"[{now_iso()}] FAILED: {exc}\n")
        raise RunError(f"{manifest.id}: {exc}") from None
    _append(log_path, f"[{now_iso()}] {result.stdout.strip()} {result.stderr.strip()}\n")
    now = now_iso()
    attempt = int(manifest.job.get("attempt", 0) or 0) + 1
    manifest.job.update(
        {
            "job_id": job_id,
            "submitted_at": now,
            "finished_at": "",
            "last_slurm_state": "PENDING",
            "attempt": attempt,
        }
    )
    manifest.job.pop("exit_code", None)
    attempts = manifest.job.setdefault("attempts", [])
    entry: dict[str, Any] = {
        "attempt": attempt,
        "job_id": job_id,
        "partition": str(manifest.job.get("partition", "")),
        "submitted_at": now,
        "finished_at": "",
        "slurm_state": "PENDING",
    }
    exe_hash = _current_exe_hash(manifest)
    if exe_hash:
        entry["exe_hash"] = exe_hash
        recorded = str(manifest.section("simulator").get("exe_hash", ""))
        if recorded and exe_hash != recorded and warnings is not None:
            warnings.append(
                f"{manifest.id}: executable changed since the run was created "
                f"(hash recorded on attempt {attempt})"
            )
    attempts.append(entry)
    manifest.set_status(RunState.SUBMITTED)
    manifest.save()
    return job_id


def _current_exe_hash(manifest: Manifest) -> str:
    """Hash of the executable as it is now; ``""`` if it is not a file."""
    exe = Path(str(manifest.section("simulator").get("executable", "")))
    try:
        return hash_file(exe) if exe_str(exe) and exe.is_file() else ""
    except OSError:
        return ""


def cancel_run(
    project: Project,
    manifest: Manifest,
    *,
    runner: CommandRunner = default_runner,
    why: str = "",
    by: str = "",
) -> None:
    with project.run_lock():
        manifest.reload()
        if manifest.status not in ACTIVE_STATES:
            raise UsageError(f"{manifest.id} is {manifest.status.value}; nothing to cancel")
        if manifest.job_id:
            scancel(manifest.job_id, runner=runner)
        now = now_iso()
        manifest.job["finished_at"] = now
        manifest.job["last_slurm_state"] = "CANCELLED"
        attempts = manifest.job.get("attempts") or []
        if attempts:
            attempts[-1]["finished_at"] = now
            attempts[-1]["slurm_state"] = "CANCELLED"
        if why:
            (attempts[-1] if attempts else manifest.job)["cancel_reason"] = why
            manifest.add_note(f"cancelled: {why}", by or "runops")
        manifest.set_status(RunState.CANCELLED)
        manifest.save()


def cancel_reason(manifest: Manifest) -> str:
    """The ``cancel --why`` reason of a cancelled run, if its latest cancel gave one."""
    if manifest.status != RunState.CANCELLED:
        return ""
    attempts = manifest.job.get("attempts") or []
    record = attempts[-1] if attempts else manifest.job
    return str(record.get("cancel_reason", ""))


def retry_run(project: Project, manifest: Manifest) -> None:
    with project.run_lock():
        manifest.reload()
        if manifest.status not in (RunState.FAILED, RunState.CANCELLED):
            raise UsageError(
                f"{manifest.id} is {manifest.status.value}; "
                "only failed/cancelled runs can be retried"
            )
        manifest.set_status(RunState.CREATED)
        manifest.job["job_id"] = ""
        manifest.job["finished_at"] = ""
        manifest.save()


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(text)
