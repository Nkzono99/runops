"""Error types carrying CLI exit codes (SPEC §7.1)."""

from __future__ import annotations


class RunopsError(Exception):
    """Base error. ``exit_code`` is used by the CLI."""

    exit_code = 1


class UsageError(RunopsError):
    """Invalid usage or configuration (exit code 2)."""

    exit_code = 2


class RunError(RunopsError):
    """Runtime failure on a target run, e.g. sbatch rejected (exit code 1)."""

    exit_code = 1
