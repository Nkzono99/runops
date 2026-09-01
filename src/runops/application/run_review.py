"""Structured terminal-Run review used by Experiment WIP gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from runops.application.execution.submission import (
    SubmissionLockError,
    submission_guard,
)
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest, write_manifest

_REVIEWABLE_STATES = frozenset(
    {"completed", "failed", "cancelled", "archived", "purged"}
)


class RunReviewError(SimctlError):
    """Raised when a Run cannot be marked reviewed safely."""


@dataclass(frozen=True)
class RunReviewResult:
    """Latest durable review record."""

    run_id: str
    run_dir: Path
    reason: str
    reviewed_by: str
    reviewed_at: str


def review_run(
    run_dir: Path,
    *,
    reason: str,
    reviewed_by: str = "human",
    now: datetime | None = None,
) -> RunReviewResult:
    """Acknowledge a terminal Run without declaring it selected evidence."""
    if run_dir.is_symlink():
        raise RunReviewError(f"Run directory must not be a symlink: {run_dir}")
    target = run_dir.resolve()
    clean_reason = reason.strip()
    if not clean_reason:
        raise RunReviewError("Run review requires a non-empty reason")
    actor = reviewed_by.strip() or "human"
    timestamp = (
        (now or datetime.now(tz=timezone.utc)).astimezone(timezone.utc).isoformat()
    )

    try:
        with submission_guard(target):
            manifest = read_manifest(target)
            status = str(manifest.run.get("status", ""))
            if status not in _REVIEWABLE_STATES:
                raise RunReviewError(
                    f"Run state {status!r} is not reviewable; wait for a terminal state"
                )
            run_id = str(manifest.run.get("id", target.name))
            manifest.curation.update(
                {
                    "review_status": "reviewed",
                    "reviewed_at": timestamp,
                    "reviewed_by": actor,
                    "reason": clean_reason,
                }
            )
            write_manifest(target, manifest)
    except SubmissionLockError as exc:
        raise RunReviewError(f"failed to lock Run review target: {exc}") from exc

    return RunReviewResult(
        run_id=run_id,
        run_dir=target,
        reason=clean_reason,
        reviewed_by=actor,
        reviewed_at=timestamp,
    )


__all__ = ["RunReviewError", "RunReviewResult", "review_run"]
