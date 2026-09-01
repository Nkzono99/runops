"""Shared planning and application workflow for scheduler submission."""

import fcntl  # noqa: F401 - compatibility patch point
import os  # noqa: F401 - compatibility patch point
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import TypeVar

from runops.application.ports.scheduler import Submitter
from runops.core.manifest import update_manifest
from runops.core.state import update_state

from . import apply as _apply
from . import claim as _claim
from .models import (
    Clock,
    SubmissionBlockedError,
    SubmissionClaimError,
    SubmissionGuard,
    SubmissionLockError,
    SubmissionOutcomeUnknownError,
    SubmissionPersistenceError,
    SubmissionResult,
    SubmissionStaleError,
    SubmitPlan,
    SubmitPrecondition,
    SubmitRequest,
)
from .planning import plan_submit

_ResetResult = TypeVar("_ResetResult")
_fsync_directory = _claim._fsync_directory


def _sync_patch_points() -> None:
    _claim._fsync_directory = _fsync_directory
    _apply.update_manifest = update_manifest  # type: ignore[attr-defined]
    _apply.update_state = update_state  # type: ignore[attr-defined]


def apply_submit(
    plan: SubmitPlan, submitter: Submitter, *, now: Clock | None = None
) -> SubmissionResult:
    _sync_patch_points()
    return _apply.apply_submit(plan, submitter, now=now)


@contextmanager
def submission_guard(run_dir: Path) -> Iterator[SubmissionGuard]:
    _sync_patch_points()
    with _claim.submission_guard(run_dir) as guard:
        yield guard


def reset_retry_under_submission_lock(
    run_dir: Path,
    resetter: Callable[[], _ResetResult],
    *,
    mutation_guard: AbstractContextManager[None] | None = None,
    preflight: Callable[[], None] | None = None,
) -> _ResetResult:
    _sync_patch_points()
    return _claim.reset_retry_under_submission_lock(
        run_dir,
        resetter,
        mutation_guard=mutation_guard,
        preflight=preflight,
    )


__all__ = [
    "SubmissionBlockedError",
    "SubmissionClaimError",
    "SubmissionGuard",
    "SubmissionLockError",
    "SubmissionOutcomeUnknownError",
    "SubmissionPersistenceError",
    "SubmissionResult",
    "SubmissionStaleError",
    "SubmitPlan",
    "SubmitPrecondition",
    "SubmitRequest",
    "apply_submit",
    "plan_submit",
    "reset_retry_under_submission_lock",
    "submission_guard",
]
