"""Run discovery via recursive search under runs/.

Finds all run directories by locating manifest.toml files
and verifies run_id uniqueness within a project.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.core.exceptions import (
    DuplicateRunIdError,
    ManifestNotFoundError,
    RunNotFoundError,
)

_MANIFEST_FILE = "manifest.toml"


def discover_runs(runs_dir: Path) -> list[Path]:
    """Recursively find all run directories under runs/.

    A directory is considered a run if it contains a manifest.toml file.

    Args:
        runs_dir: Root runs/ directory to search.

    Returns:
        Sorted list of absolute paths to run directories.
    """
    if not runs_dir.is_dir():
        return []

    run_dirs: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(
        runs_dir,
        onerror=lambda _err: None,
    ):
        if _MANIFEST_FILE in filenames:
            run_dirs.append(Path(dirpath).resolve())

    return sorted(run_dirs)


def _read_run_id(run_dir: Path) -> str:
    """Read the run_id from a run directory's manifest.toml.

    Args:
        run_dir: Path to the run directory.

    Returns:
        The run_id string.

    Raises:
        ManifestNotFoundError: If manifest.toml does not exist.
    """
    manifest_path = run_dir / _MANIFEST_FILE
    if not manifest_path.exists():
        raise ManifestNotFoundError(f"{_MANIFEST_FILE} not found in {run_dir}")

    with open(manifest_path, "rb") as f:
        data = tomllib.load(f)

    run_section = data.get("run", {})
    run_id = run_section.get("id", "")
    if not isinstance(run_id, str):
        return str(run_id)
    return run_id


def check_run_id_uniqueness(runs_dir: Path) -> list[str]:
    """Check for duplicate run_ids under runs/.

    Args:
        runs_dir: Root runs/ directory to search.

    Returns:
        List of duplicate run_id strings (empty if all unique).
    """
    run_dirs = discover_runs(runs_dir)
    id_to_paths: defaultdict[str, list[str]] = defaultdict(list)

    for run_dir in run_dirs:
        try:
            run_id = _read_run_id(run_dir)
            if run_id:
                id_to_paths[run_id].append(str(run_dir))
        except (ManifestNotFoundError, Exception):
            # Skip directories with unreadable manifests
            continue

    return [run_id for run_id, paths in id_to_paths.items() if len(paths) > 1]


def validate_uniqueness(runs_dir: Path) -> None:
    """Validate that all run_ids are unique under runs/.

    Args:
        runs_dir: Root runs/ directory to search.

    Raises:
        DuplicateRunIdError: If any duplicate run_ids are found.
    """
    run_dirs = discover_runs(runs_dir)
    id_to_paths: defaultdict[str, list[str]] = defaultdict(list)

    for run_dir in run_dirs:
        try:
            run_id = _read_run_id(run_dir)
            if run_id:
                id_to_paths[run_id].append(str(run_dir))
        except (ManifestNotFoundError, Exception):
            continue

    for run_id, paths in id_to_paths.items():
        if len(paths) > 1:
            raise DuplicateRunIdError(run_id, paths)


def resolve_run(identifier: str, runs_dir: Path) -> Path:
    """Find a run by run_id or path.

    If the identifier looks like a run_id (starts with 'R' and matches
    the RYYYYMMDD-NNNN pattern), searches all manifests. Otherwise,
    treats it as a path.

    Args:
        identifier: A run_id string or path to a run directory.
        runs_dir: Root runs/ directory to search.

    Returns:
        Absolute path to the run directory.

    Raises:
        RunNotFoundError: If the run cannot be found.
        DuplicateRunIdError: If the run_id matches multiple manifests.
    """
    # Check if identifier is a path
    try:
        id_path = Path(identifier)
        if id_path.is_absolute():
            if (id_path / _MANIFEST_FILE).exists():
                return id_path.resolve()
            raise RunNotFoundError(f"No manifest.toml found at path: {identifier}")

        # Check as relative path from cwd
        if (id_path / _MANIFEST_FILE).exists():
            return id_path.resolve()
    except OSError as e:
        raise RunNotFoundError(f"Invalid run path {identifier!r}: {e}") from None

    # Search by run_id
    matches: list[Path] = []
    run_dirs = discover_runs(runs_dir)
    for run_dir in run_dirs:
        try:
            run_id = _read_run_id(run_dir)
            if run_id == identifier:
                matches.append(run_dir)
        except (ManifestNotFoundError, Exception):
            continue

    if len(matches) > 1:
        raise DuplicateRunIdError(identifier, [str(path) for path in matches])
    if len(matches) == 1:
        return matches[0]

    raise RunNotFoundError(f"Run not found for identifier: {identifier!r}")


def collect_existing_run_ids(runs_dir: Path) -> set[str]:
    """Collect all existing run_ids from a runs/ directory.

    Args:
        runs_dir: Root runs/ directory to search.

    Returns:
        Set of run_id strings.
    """
    run_dirs = discover_runs(runs_dir)
    ids: set[str] = set()

    for run_dir in run_dirs:
        try:
            run_id = _read_run_id(run_dir)
            if run_id:
                ids.add(run_id)
        except (ManifestNotFoundError, Exception):
            continue

    return ids
