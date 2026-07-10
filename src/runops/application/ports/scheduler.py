"""Narrow scheduler port used by the submission application workflow."""

from __future__ import annotations

from collections.abc import Callable


class SchedulerRejectedError(RuntimeError):
    """The scheduler definitively rejected a request before accepting a job."""


class SchedulerOutcomeUnknownError(RuntimeError):
    """The scheduler may have accepted a request, but its outcome is unknown."""


Submitter = Callable[[tuple[str, ...]], str]

__all__ = [
    "SchedulerOutcomeUnknownError",
    "SchedulerRejectedError",
    "Submitter",
]
