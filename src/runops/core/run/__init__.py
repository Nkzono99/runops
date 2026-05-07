"""Run generation and run_id assignment.

Creates run directories with standard subdirectories and assigns unique
run identifiers in the format RYYYYMMDD-NNNN.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from runops.core.exceptions import DuplicateRunIdError, SimctlError


@dataclass(frozen=True)
class RunInfo:
    """Immutable information about a generated run.

    Attributes:
        run_id: Unique run identifier (e.g. "R20260327-0001").
        run_dir: Absolute path to the run directory.
        display_name: Human-readable display name.
        created_at: Timestamp of run creation.
        params: Parameter snapshot for this run.
    """

    run_id: str
    run_dir: Path
    display_name: str = ""
    created_at: str = ""
    params: dict[str, Any] = field(default_factory=dict)


#: Standard subdirectories to create in each run directory.
_RUN_SUBDIRS = ("input", "submit", "work", "analysis", "status")


def generate_run_id(date_str: str, sequence: int) -> str:
    """Generate a run_id in the format RYYYYMMDD-NNNN.

    Args:
        date_str: Date string in YYYYMMDD format.
        sequence: Sequence number for the day (1-based).

    Returns:
        Formatted run_id string.

    Raises:
        SimctlError: If date_str or sequence is invalid.
    """
    if len(date_str) != 8 or not date_str.isdigit():
        raise SimctlError(f"Invalid date string {date_str!r}: must be YYYYMMDD format")
    if sequence < 1 or sequence > 9999:
        raise SimctlError(f"Invalid sequence number {sequence}: must be 1-9999")
    return f"R{date_str}-{sequence:04d}"


def next_run_id(
    existing_ids: set[str],
    target_date: date | None = None,
) -> str:
    """Generate the next available run_id for a given date.

    Examines existing run_ids to determine the next sequence number.

    Args:
        existing_ids: Set of all existing run_ids in the project.
        target_date: Date to generate the run_id for. Defaults to today.

    Returns:
        Next available run_id string.

    Raises:
        SimctlError: If the sequence number would exceed 9999.
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime("%Y%m%d")
    prefix = f"R{date_str}-"

    max_seq = 0
    for rid in existing_ids:
        if rid.startswith(prefix):
            try:
                seq = int(rid[len(prefix) :])
                max_seq = max(max_seq, seq)
            except ValueError:
                continue

    next_seq = max_seq + 1
    if next_seq > 9999:
        raise SimctlError(
            f"Run sequence overflow for date {date_str}: maximum 9999 runs per day"
        )

    return generate_run_id(date_str, next_seq)


def create_run_directory(
    parent_dir: Path,
    run_id: str,
    case_data: dict[str, Any] | None = None,
) -> Path:
    """Create a run directory with standard subdirectories.

    Creates the run directory and all standard subdirectories
    (input/, submit/, work/, analysis/, status/) as defined in
    SPEC section 8.

    Args:
        parent_dir: Parent directory (typically the survey directory).
        run_id: Unique run identifier.
        case_data: Optional case configuration for this run (reserved
            for future use by adapters).

    Returns:
        Absolute path to the created run directory.

    Raises:
        SimctlError: If the run directory already exists.
    """
    run_dir = (parent_dir / run_id).resolve()

    if run_dir.exists():
        raise DuplicateRunIdError(run_id, [str(run_dir)])

    run_dir.mkdir(parents=True)
    for subdir in _RUN_SUBDIRS:
        (run_dir / subdir).mkdir()

    return run_dir


def create_run(
    parent_dir: Path,
    existing_ids: set[str],
    *,
    display_name: str = "",
    params: dict[str, Any] | None = None,
    target_date: date | None = None,
) -> RunInfo:
    """Create a new run with auto-incremented run_id.

    Combines run_id generation and directory creation into a single
    high-level operation.

    Args:
        parent_dir: Parent directory (typically the survey directory).
        existing_ids: Set of all existing run_ids in the project.
        display_name: Human-readable display name for the run.
        params: Parameter snapshot for this run.
        target_date: Date to generate the run_id for. Defaults to today.

    Returns:
        RunInfo with the created run's details.
    """
    run_id = next_run_id(existing_ids, target_date)
    run_dir = create_run_directory(parent_dir, run_id)
    created_at = datetime.now(tz=timezone.utc).isoformat()

    return RunInfo(
        run_id=run_id,
        run_dir=run_dir,
        display_name=display_name,
        created_at=created_at,
        params=params or {},
    )
