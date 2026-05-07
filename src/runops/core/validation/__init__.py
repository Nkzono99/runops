"""Validation data structures for parameter checking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding for a parameter set.

    Attributes:
        severity: ``"error"`` (run will likely fail) or ``"warning"``
            (suboptimal but may work).
        message: Human-readable explanation.
        parameter: Dot-notation path to the offending parameter
            (empty if the issue involves multiple parameters).
        constraint_name: Machine-readable constraint identifier
            (e.g. ``"cfl_condition"``, ``"debye_resolution"``).
        details: Numeric context for programmatic consumers and
            AI agents (e.g. computed value, threshold, formula).
    """

    severity: str
    message: str
    parameter: str = ""
    constraint_name: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# Valid insight types for .runops/insights/ files
INSIGHT_TYPES = frozenset(
    {
        "constraint",  # Stability/constraint findings (learned from failures)
        "result",  # Experiment result summaries
        "analysis",  # Physical interpretation / discussion
        "dependency",  # Parameter dependency trends
    }
)
