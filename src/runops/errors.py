"""Error types carrying CLI exit codes (SPEC §7.1)."""

from __future__ import annotations

# runops 2.9 dropped `migrate-v1`; a v1 project is converted with the last release that had it.
V1_MIGRATION = (
    "migrate it with `runo migrate-v1` of runops 2.8 first "
    "(`uvx --from runops==2.8.0 runo migrate-v1 --dry-run` in the project root), "
    "then use this version"
)


class RunopsError(Exception):
    """Base error. ``exit_code`` is used by the CLI."""

    exit_code = 1


class UsageError(RunopsError):
    """Invalid usage or configuration (exit code 2)."""

    exit_code = 2


class RunError(RunopsError):
    """Runtime failure on a target run, e.g. sbatch rejected (exit code 1)."""

    exit_code = 1


class SlurmTimeoutError(RunError):
    """A Slurm command gave no answer in time; after sbatch, acceptance is unknown."""
