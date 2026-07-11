"""Read-only submission precondition planning."""

from __future__ import annotations

from pathlib import Path

from runops.core.manifest import read_manifest
from runops.core.state import RunState

from .claim import _read_submission_claim
from .models import (
    SubmissionClaimError,
    SubmissionLockError,
    SubmitPlan,
    SubmitPrecondition,
    SubmitRequest,
)

_DIRTY_PRODUCTION_WARNING = "production run submitted with dirty git working tree"


def plan_submit(request: SubmitRequest) -> SubmitPlan:
    """Build a complete, read-only plan for one run submission."""
    run_dir = request.run_dir.resolve()
    manifest = read_manifest(run_dir)
    run_id = str(manifest.run.get("id", run_dir.name))
    state_before = str(manifest.run.get("status", ""))
    job_id_before = str(manifest.job.get("job_id", "") or "")
    try:
        claim_before = _read_submission_claim(run_dir)
    except (SubmissionLockError, SubmissionClaimError) as exc:
        claim_before = f"<unreadable: {type(exc).__name__}: {exc}>"
    job_script = run_dir / "submit" / "job.sh"
    input_dir = run_dir / "input"

    preconditions: list[SubmitPrecondition] = [
        SubmitPrecondition(
            name="state_created",
            passed=state_before == RunState.CREATED.value,
            message=(
                f"Run state is {state_before!r}; expected {RunState.CREATED.value!r}"
            ),
        )
    ]
    preconditions.append(
        SubmitPrecondition(
            name="job_id_empty",
            passed=not job_id_before,
            message=(
                "No accepted job_id is recorded"
                if not job_id_before
                else f"Accepted job_id is already recorded: {job_id_before}"
            ),
        )
    )
    preconditions.append(
        SubmitPrecondition(
            name="submission_claim_empty",
            passed=not claim_before,
            message=(
                "No durable submission claim is recorded"
                if not claim_before
                else f"Durable submission claim is recorded: {claim_before}"
            ),
        )
    )

    script_exists = _is_file(job_script)
    preconditions.append(
        SubmitPrecondition(
            name="job_script_exists",
            passed=script_exists,
            message=(
                f"Job script exists: {job_script}"
                if script_exists
                else f"Job script not found: {job_script}"
            ),
        )
    )

    job_content = ""
    script_readable = False
    read_error = ""
    if script_exists:
        try:
            job_content = job_script.read_text(encoding="utf-8")
            script_readable = True
        except (OSError, UnicodeError) as exc:
            read_error = str(exc)
    else:
        read_error = "job script does not exist"
    preconditions.append(
        SubmitPrecondition(
            name="job_script_readable",
            passed=script_readable,
            message=(
                f"Job script is readable: {job_script}"
                if script_readable
                else f"Failed to read job script {job_script}: {read_error}"
            ),
        )
    )

    has_sbatch = script_readable and "#SBATCH" in job_content
    if has_sbatch:
        sbatch_message = "job.sh contains expected #SBATCH directives"
    elif script_readable:
        sbatch_message = "job.sh does not contain expected #SBATCH directives"
    else:
        sbatch_message = "Cannot inspect #SBATCH directives in an unreadable job.sh"
    preconditions.append(
        SubmitPrecondition(
            name="job_script_has_sbatch",
            passed=has_sbatch,
            message=sbatch_message,
        )
    )

    input_ready, input_message = _check_input(input_dir)
    preconditions.append(
        SubmitPrecondition(
            name="input_ready",
            passed=input_ready,
            message=input_message,
        )
    )

    work_dir = _select_work_dir(run_dir)

    command = ["sbatch", f"--chdir={work_dir}"]
    if request.afterok:
        command.append(f"--dependency=afterok:{request.afterok}")
    if request.queue_name:
        command.append(f"--partition={request.queue_name}")
    if request.qos:
        command.append(f"--qos={request.qos}")
    command.append(str(job_script))

    warnings: tuple[str, ...] = ()
    tags = manifest.classification.get("tags", [])
    if "production" in tags and manifest.simulator_source.get("git_dirty", False):
        warnings = (_DIRTY_PRODUCTION_WARNING,)

    return SubmitPlan(
        run_id=run_id,
        run_dir=run_dir,
        state_before=state_before,
        job_id_before=job_id_before,
        claim_before=claim_before,
        job_script=job_script,
        work_dir=work_dir,
        queue_name=request.queue_name,
        qos=request.qos,
        afterok=request.afterok,
        command=tuple(command),
        preconditions=tuple(preconditions),
        warnings=warnings,
    )


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _select_work_dir(run_dir: Path) -> Path:
    work_dir = run_dir / "work"
    return work_dir if _is_dir(work_dir) else run_dir


def _check_input(input_dir: Path) -> tuple[bool, str]:
    try:
        if not input_dir.is_dir():
            return False, f"input/ directory is missing in {input_dir.parent}"
        if not any(input_dir.iterdir()):
            return False, f"input/ directory is empty in {input_dir.parent}"
    except OSError as exc:
        return False, f"Failed to inspect input/ directory {input_dir}: {exc}"
    return True, f"input/ directory contains submission inputs: {input_dir}"
