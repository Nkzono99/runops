"""Helpers for delegating HarnessOps lifecycle work to the ``hops`` CLI."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

HarnessOpsStatus = Literal["created", "updated", "skipped", "failed"]


@dataclass(frozen=True)
class HarnessOpsResult:
    """Outcome from a best-effort HarnessOps lifecycle command."""

    status: HarnessOpsStatus
    message: str


def _hops_in_venv(project_dir: Path) -> Path:
    """Return the expected ``hops`` path inside the project venv."""
    if sys.platform == "win32":
        return project_dir / ".venv" / "Scripts" / "hops.exe"
    return project_dir / ".venv" / "bin" / "hops"


def _project_uses_uv(project_dir: Path) -> bool:
    """Return whether ``uv run`` is likely to use a project-local environment."""
    return (project_dir / "uv.lock").exists() or (
        project_dir / "pyproject.toml"
    ).exists()


def resolve_hops_command(project_dir: Path) -> list[str] | None:
    """Return a command prefix for ``hops``, preferring project-local installs."""
    env_command = os.environ.get("RUNOPS_HOPS_COMMAND")
    if env_command:
        return shlex.split(env_command)

    venv_hops = _hops_in_venv(project_dir)
    if venv_hops.exists():
        return [str(venv_hops)]

    hops = shutil.which("hops")
    if hops:
        return [hops]

    uv = shutil.which("uv")
    if uv and _project_uses_uv(project_dir):
        return [uv, "run", "hops"]

    uvx = shutil.which("uvx")
    if uvx:
        return [uvx, "--from", "harnessops", "hops"]
    return None


def _run_hops(
    project_dir: Path,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    """Run ``hops`` with ``args`` in ``project_dir``."""
    command = resolve_hops_command(project_dir)
    if command is None:
        return subprocess.CompletedProcess(
            ["hops", *args],
            127,
            stdout="",
            stderr="hops command not found",
        )
    return subprocess.run(
        [*command, *args],
        cwd=project_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _summarize_failure(action: str, result: subprocess.CompletedProcess[str]) -> str:
    """Return a compact user-facing failure summary."""
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        detail = f": {detail[:300]}"
    return f"HarnessOps {action} failed{detail}"


def initialize_project_harnessops(
    project_dir: Path,
    *,
    profile: str = "runops-project",
    dry_run: bool = False,
) -> HarnessOpsResult:
    """Initialize or verify the project-side HarnessOps overlay via ``hops``.

    This function never writes HarnessOps-managed files directly.  It only
    delegates to ``hops`` when the command is available.
    """
    if resolve_hops_command(project_dir) is None:
        return HarnessOpsResult(
            "skipped",
            "HarnessOps skipped (hops command not found)",
        )

    project_file = project_dir / ".harnessops" / "project.toml"
    if project_file.exists():
        result = _run_hops(
            project_dir,
            ["doctor", "--check-overlay", "--check-records"],
        )
        if result.returncode == 0:
            return HarnessOpsResult("skipped", "HarnessOps already initialized")
        return HarnessOpsResult("failed", _summarize_failure("doctor", result))

    args = ["init", "--profile", profile, "--with-agent-bridge"]
    if dry_run:
        args.append("--dry-run")
    result = _run_hops(project_dir, args)
    if result.returncode != 0:
        return HarnessOpsResult("failed", _summarize_failure("init", result))
    if dry_run:
        return HarnessOpsResult("skipped", "HarnessOps init would run")

    doctor = _run_hops(project_dir, ["doctor", "--check-overlay", "--check-records"])
    if doctor.returncode != 0:
        return HarnessOpsResult("failed", _summarize_failure("doctor", doctor))
    return HarnessOpsResult("created", "HarnessOps initialized")


def update_project_harnessops(
    project_dir: Path,
    *,
    profile: str = "runops-project",
    dry_run: bool = False,
) -> HarnessOpsResult:
    """Update the project-side HarnessOps overlay via ``hops``."""
    if resolve_hops_command(project_dir) is None:
        return HarnessOpsResult(
            "skipped",
            "HarnessOps skipped (hops command not found)",
        )

    project_file = project_dir / ".harnessops" / "project.toml"
    if not project_file.exists():
        return initialize_project_harnessops(
            project_dir,
            profile=profile,
            dry_run=dry_run,
        )

    args = ["update-harness", "--agent-bridge", "--codex", "--claude"]
    if dry_run:
        args.append("--dry-run")
    result = _run_hops(project_dir, args)
    if result.returncode != 0:
        return HarnessOpsResult("failed", _summarize_failure("update-harness", result))
    if dry_run:
        return HarnessOpsResult("skipped", "HarnessOps update would run")

    doctor = _run_hops(project_dir, ["doctor", "--check-overlay", "--check-records"])
    if doctor.returncode != 0:
        return HarnessOpsResult("failed", _summarize_failure("doctor", doctor))
    return HarnessOpsResult("updated", "HarnessOps updated")
