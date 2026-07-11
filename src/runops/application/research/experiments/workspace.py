"""Atomic plan/apply workflow for experiment creation."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, NoReturn

import tomli_w

from runops.application.research.experiments.models import (
    ExperimentCreatePlan,
    ExperimentCreateRequest,
    ExperimentCreateResult,
    ExperimentLedger,
    ExperimentRecord,
)
from runops.application.research.experiments.schema import load_experiment_ledger
from runops.core.exceptions import SimctlError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ExperimentStalePlanError(SimctlError):
    """Raised when project state changed after planning."""


class ExperimentCreateApplyError(SimctlError):
    """Raised when an apply failed and reports its recovery state."""

    def __init__(
        self,
        message: str,
        *,
        completed_paths: tuple[Path, ...],
        failed_path: Path,
        recovery_path: Path | None,
        cause: BaseException,
    ) -> None:
        super().__init__(message)
        self.completed_paths = completed_paths
        self.failed_path = failed_path
        self.recovery_path = recovery_path
        self.cause = cause


def plan_create_experiment(request: ExperimentCreateRequest) -> ExperimentCreatePlan:
    """Validate and render an experiment creation without writing files."""
    project_root = request.project_root.resolve()
    experiment_id = request.experiment_id
    if not _EXPERIMENT_ID.fullmatch(experiment_id):
        raise SimctlError(
            "experiment id must start with an alphanumeric character and contain "
            "at most 64 alphanumeric, dot, underscore, or hyphen characters"
        )
    ledger = load_experiment_ledger(project_root)
    if ledger.schema_version != 2:
        raise SimctlError("experiment creation requires ledger schema_version 2")
    if any(record.id == experiment_id for record in ledger.experiments):
        raise SimctlError(f"experiment already exists: {experiment_id}")
    proposal_path = project_root / "research" / "proposals" / f"{experiment_id}.md"
    if proposal_path.exists():
        raise SimctlError(f"experiment proposal already exists: {proposal_path}")

    spec = request.spec
    record = ExperimentRecord(
        id=experiment_id,
        title=spec.title,
        question=spec.question,
        decision="WAIT",
        proposal=proposal_path.relative_to(project_root),
        review=None,
        selected_candidate=spec.selected_candidate,
        cost_ceiling_core_hours=spec.cost_ceiling_core_hours,
        candidates=spec.candidates,
    )
    original = ledger.path.read_bytes()
    if _identity(ledger.path) != ledger.identity:
        raise ExperimentStalePlanError("experiment ledger changed while planning")
    payload = _parse_ledger_bytes(original, ledger.path)
    raw_experiments = payload.setdefault("experiments", [])
    if not isinstance(raw_experiments, list):
        raise SimctlError("research/experiments.toml must define [[experiments]]")
    raw_experiments.append(_record_payload(record))
    after_bytes = tomli_w.dumps(payload).encode("utf-8")
    after = ExperimentLedger(
        path=ledger.path,
        schema_version=2,
        experiments=(*ledger.experiments, record),
        identity=ledger.identity,
    )
    return ExperimentCreatePlan(
        project_root=project_root,
        experiment_id=experiment_id,
        ledger_path=ledger.path,
        ledger_identity=ledger.identity,
        ledger_after=after,
        proposal_path=proposal_path,
        proposal_text=_render_proposal(record),
        original_ledger_bytes=original,
        ledger_bytes_after=after_bytes,
    )


def apply_create_experiment(plan: ExperimentCreatePlan) -> ExperimentCreateResult:
    """Apply a creation plan with stale-state checks and rollback."""
    if _identity(plan.ledger_path) != plan.ledger_identity:
        raise ExperimentStalePlanError("experiment ledger changed after planning")
    if plan.proposal_path.exists():
        raise ExperimentStalePlanError("experiment proposal appeared after planning")

    proposal_dir_existed = plan.proposal_path.parent.is_dir()
    plan.proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_stage: Path | None = None
    ledger_stage: Path | None = None
    proposal_inode: tuple[int, int] | None = None
    ledger_replaced = False
    completed: list[Path] = []
    failed_path = plan.proposal_path
    recovery_path: Path | None = None
    try:
        proposal_stage = _stage_bytes(
            plan.proposal_path.parent,
            ".experiment-proposal-",
            plan.proposal_text.encode("utf-8"),
        )
        ledger_stage = _stage_bytes(
            plan.ledger_path.parent,
            ".experiment-ledger-",
            plan.ledger_bytes_after,
        )
        _publish_proposal(proposal_stage, plan.proposal_path)
        proposal_stage = None
        proposal_stat = plan.proposal_path.stat()
        proposal_inode = (proposal_stat.st_dev, proposal_stat.st_ino)
        completed.append(plan.proposal_path)
        failed_path = plan.ledger_path
        _publish_ledger(ledger_stage, plan.ledger_path)
        ledger_stage = None
        ledger_replaced = True
        completed.append(plan.ledger_path)
        _fsync_directory(plan.proposal_path.parent)
        _fsync_directory(plan.ledger_path.parent)
    except BaseException as exc:
        recovery_path = _rollback(
            plan,
            ledger_replaced=ledger_replaced,
            proposal_inode=proposal_inode,
        )
        _cleanup_stage(proposal_stage)
        _cleanup_stage(ledger_stage)
        if not proposal_dir_existed:
            _remove_empty_directory(plan.proposal_path.parent)
        _raise_apply_error(
            plan,
            exc,
            completed=tuple(completed),
            failed_path=failed_path,
            recovery_path=recovery_path,
        )
    record = plan.ledger_after.experiments[-1]
    return ExperimentCreateResult(record, plan.ledger_path, plan.proposal_path)


def _record_payload(record: ExperimentRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "title": record.title,
        "question": record.question,
        "decision": record.decision,
        "proposal": record.proposal.as_posix(),
        "review": "",
        "selected_candidate": record.selected_candidate,
        "cost_ceiling_core_hours": record.cost_ceiling_core_hours,
        "candidates": [
            {
                "id": candidate.id,
                "information_gain": candidate.information_gain,
                "falsification": candidate.falsification,
                "estimated_core_hours": candidate.estimated_core_hours,
                "operational_risk": candidate.operational_risk,
            }
            for candidate in record.candidates
        ],
    }


def _render_proposal(record: ExperimentRecord) -> str:
    rows = "\n".join(
        "| "
        + " | ".join(
            (
                item.id,
                item.information_gain,
                item.falsification,
                f"{item.estimated_core_hours:g}",
                item.operational_risk,
            )
        )
        + " |"
        for item in record.candidates
    )
    return (
        f"# {record.title}\n\n"
        f"Experiment ID: `{record.id}`\n\n"
        "## Question\n\n"
        f"{record.question}\n\n"
        "## Candidates\n\n"
        "| ID | Information gain | Falsification | Core hours | Risk |\n"
        "|---|---|---|---:|---|\n"
        f"{rows}\n\n"
        "## Selection and budget\n\n"
        f"- Selected candidate: `{record.selected_candidate}`\n"
        f"- Cost ceiling: {record.cost_ceiling_core_hours:g} core-hours\n\n"
        "## Evidence\n\n"
        "Record evidence paths and observations here.\n\n"
        "## Review\n\n"
        "Record the human WAIT/EXPAND/REVISE/STOP decision separately.\n"
    )


def _parse_ledger_bytes(data: bytes, path: Path) -> dict[str, Any]:
    try:
        parsed = tomllib.loads(data.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise SimctlError(f"Invalid experiment TOML {path}: {exc}") from exc
    return parsed


def _identity(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_mtime_ns


def _stage_bytes(directory: Path, prefix: str, data: bytes) -> Path:
    fd, raw_path = tempfile.mkstemp(dir=directory, prefix=prefix, suffix=".tmp")
    path = Path(raw_path)
    try:
        os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def _publish_proposal(staged: Path, target: Path) -> None:
    os.link(staged, target)
    staged.unlink()


def _publish_ledger(staged: Path, target: Path) -> None:
    os.replace(staged, target)


def _rollback(
    plan: ExperimentCreatePlan,
    *,
    ledger_replaced: bool,
    proposal_inode: tuple[int, int] | None,
) -> Path | None:
    recovery: Path | None = None
    if ledger_replaced:
        try:
            restore = _stage_bytes(
                plan.ledger_path.parent,
                ".experiment-recovery-",
                plan.original_ledger_bytes,
            )
            recovery = restore
            os.replace(restore, plan.ledger_path)
            recovery = None
            _fsync_directory(plan.ledger_path.parent)
        except OSError:
            pass
    if proposal_inode is not None:
        try:
            stat = plan.proposal_path.stat()
            if (stat.st_dev, stat.st_ino) == proposal_inode:
                plan.proposal_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            if recovery is None:
                recovery = plan.proposal_path
    return recovery


def _cleanup_stage(path: Path | None) -> None:
    if path is not None:
        with suppress(OSError):
            path.unlink(missing_ok=True)


def _remove_empty_directory(path: Path) -> None:
    with suppress(OSError):
        path.rmdir()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _raise_apply_error(
    plan: ExperimentCreatePlan,
    cause: BaseException,
    *,
    completed: tuple[Path, ...],
    failed_path: Path,
    recovery_path: Path | None,
) -> NoReturn:
    raise ExperimentCreateApplyError(
        f"Failed to create experiment {plan.experiment_id}: {cause}",
        completed_paths=completed,
        failed_path=failed_path,
        recovery_path=recovery_path,
        cause=cause,
    ) from cause
