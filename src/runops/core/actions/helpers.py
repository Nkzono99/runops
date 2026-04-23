"""Shared helpers for agent action implementations."""

from __future__ import annotations

from pathlib import Path

from runops.core.actions.result import ActionResult, ActionStatus
from runops.core.state import RunState


def _require_state(run_dir: Path, *allowed: RunState) -> tuple[str, str | None]:
    """Read manifest and check run state.

    Returns:
        (current_state_value, error_message_or_None)
    """
    from runops.core.manifest import read_manifest

    manifest = read_manifest(run_dir)
    state_str = manifest.run.get("status", "")
    try:
        state = RunState(state_str)
    except ValueError:
        return state_str, f"Unknown run state: {state_str!r}"

    if state not in allowed:
        allowed_str = ", ".join(s.value for s in allowed)
        return state_str, f"Run state is {state_str!r}, requires one of: {allowed_str}"

    return state_str, None


def _precondition_fail(action: str, message: str) -> ActionResult:
    return ActionResult(
        action=action,
        status=ActionStatus.PRECONDITION_FAILED,
        message=message,
    )


def _error(action: str, message: str) -> ActionResult:
    return ActionResult(
        action=action,
        status=ActionStatus.ERROR,
        message=message,
    )


def _dir_size(dir_path: Path) -> int:
    """Calculate total size of files under a directory tree."""
    if not dir_path.is_dir():
        return 0
    total = 0
    for f in dir_path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total
