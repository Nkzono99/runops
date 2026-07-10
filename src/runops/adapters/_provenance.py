"""Shared executable and source provenance collection."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def collect_executable_provenance(
    runtime_info: Mapping[str, Any],
) -> dict[str, Any]:
    """Collect the stable executable provenance payload.

    Args:
        runtime_info: Runtime data produced by executable resolution.

    Returns:
        Flat provenance payload with stable keys for manifest serialization.
    """
    provenance: dict[str, Any] = {
        "resolver_mode": runtime_info.get("resolver_mode", ""),
        "executable": runtime_info.get("executable", ""),
        "exe_hash": "",
        "git_commit": "",
        "git_dirty": False,
        "source_repo": runtime_info.get("source_repo", ""),
        "build_command": runtime_info.get("build_command", ""),
        "package_version": runtime_info.get("package_version", ""),
    }

    executable = Path(runtime_info.get("executable", ""))
    if executable.is_file():
        provenance["exe_hash"] = _compute_file_hash(executable)

    if runtime_info.get("resolver_mode") == "local_source":
        source_repo = runtime_info.get("source_repo", "")
        if source_repo:
            commit, dirty = _collect_git_state(Path(source_repo))
            provenance["git_commit"] = commit
            provenance["git_dirty"] = dirty

    return provenance


def _compute_file_hash(path: Path) -> str:
    """Return the SHA-256 digest of a regular file."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _collect_git_state(repo_path: Path) -> tuple[str, bool]:
    """Return the current commit and worktree-dirty flag when available."""
    if not repo_path.is_dir():
        return "", False

    commit = ""
    dirty = False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            check=False,
        )
        if result.returncode == 0:
            commit = result.stdout.strip()

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            check=False,
        )
        if result.returncode == 0:
            dirty = bool(result.stdout.strip())
    except FileNotFoundError:
        logger.debug("git not found on PATH; skipping git provenance")

    return commit, dirty


__all__ = ["collect_executable_provenance"]
