"""Structured result types for agent actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionStatus(str, Enum):
    """Outcome of an action execution."""

    SUCCESS = "success"
    FAILED = "failed"
    PRECONDITION_FAILED = "precondition_failed"
    ERROR = "error"


@dataclass
class ActionResult:
    """Structured result returned by every action.

    Attributes:
        action: Name of the executed action.
        status: Outcome status.
        message: Human-readable summary.
        data: Arbitrary result payload (action-specific).
        state_before: Run state before execution (if applicable).
        state_after: Run state after execution (if applicable).
    """

    action: str
    status: ActionStatus
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    state_before: str = ""
    state_after: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dictionary."""
        d: dict[str, Any] = {
            "action": self.action,
            "status": self.status.value,
            "message": self.message,
        }
        if self.data:
            d["data"] = self.data
        if self.state_before:
            d["state_before"] = self.state_before
        if self.state_after:
            d["state_after"] = self.state_after
        return d
