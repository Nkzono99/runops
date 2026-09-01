"""Run discovery via recursive search under runs/.

Finds all run directories by locating manifest.toml files
and verifies run_id uniqueness within a project.
"""

from __future__ import annotations

import os
import re
import stat
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
    SimctlError,
)

_MANIFEST_FILE = "manifest.toml"
ARCHIVE_BUNDLE_METADATA_FILE = ".runops-archive.toml"
_ARCHIVE_DIR_NAME = "_archive"
_INACTIVE_RUN_STATUSES = frozenset({"archived", "purged"})
_RUN_ID_PATTERN = re.compile(r"^R\d{8}-\d{4}$")


class RunDiscoveryError(SimctlError):
    """Raised when an operator view cannot enumerate a Run namespace safely."""


def _is_internal_staging_dir(name: str) -> bool:
    """Return whether ``name`` is an unpublished runops staging directory."""
    return name.startswith((".tmp-", ".delete-"))


def find_archived_bundle(path: Path) -> Path | None:
    """Return the nearest archived bundle containing ``path``.

    Bundle archival is orthogonal to each run's lifecycle state, so callers
    must use the marker file rather than infer archival from ``run.status``.
    """
    current = path.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ARCHIVE_BUNDLE_METADATA_FILE).is_file():
            return candidate
    return None


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
    for dirpath, dirnames, filenames in os.walk(
        runs_dir,
        topdown=True,
        onerror=lambda _err: None,
    ):
        dirnames[:] = [
            dirname for dirname in dirnames if not _is_internal_staging_dir(dirname)
        ]
        if _MANIFEST_FILE in filenames:
            run_dirs.append(Path(dirpath).resolve())

    return sorted(run_dirs)


def discover_runs_checked(runs_dir: Path) -> list[Path]:
    """Discover every Run or fail if the formal namespace is incomplete."""
    return _discover_runs_checked(runs_dir, active_only=False)


def discover_active_runs(runs_dir: Path) -> list[Path]:
    """Find runs that belong to the active operational view.

    Unlike :func:`discover_runs`, this bounded walker prunes archive roots and
    archive-marker bundles before descending into them.  Runs archived in
    place are excluded by their manifest status.  Unreadable manifests remain
    discoverable so callers can report them as malformed rather than silently
    losing them.

    This function is for list/context views only.  Identity resolution,
    uniqueness checks, and ID allocation must continue to use the exhaustive
    :func:`discover_runs` traversal.
    """
    if not runs_dir.is_dir():
        return []

    root = runs_dir.resolve()
    if root.name == _ARCHIVE_DIR_NAME or find_archived_bundle(root) is not None:
        return []

    run_dirs: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(
        root,
        topdown=True,
        onerror=lambda _err: None,
    ):
        current = Path(dirpath)
        if ARCHIVE_BUNDLE_METADATA_FILE in filenames:
            dirnames[:] = []
            continue

        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not _is_internal_staging_dir(dirname)
            and dirname != _ARCHIVE_DIR_NAME
            and not (current / dirname / ARCHIVE_BUNDLE_METADATA_FILE).is_file()
        ]

        if _MANIFEST_FILE not in filenames:
            continue
        status = _read_run_status(current)
        if status not in _INACTIVE_RUN_STATUSES:
            run_dirs.append(current.resolve())

    return sorted(run_dirs)


def discover_active_runs_checked(runs_dir: Path) -> list[Path]:
    """Discover the active Run view without hiding unsafe subtrees."""
    return _discover_runs_checked(runs_dir, active_only=True)


def _discover_runs_checked(runs_dir: Path, *, active_only: bool) -> list[Path]:
    """Walk a formal Run tree while making incomplete enumeration explicit."""
    root = Path(os.path.abspath(runs_dir))
    try:
        root_metadata = root.lstat()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise RunDiscoveryError(
            f"Cannot inspect the Run namespace root {root}: {exc}"
        ) from exc
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise RunDiscoveryError(f"Run namespace root must be a real directory: {root}")
    try:
        canonical_root = root.resolve(strict=True)
    except OSError as exc:
        raise RunDiscoveryError(
            f"Cannot resolve the Run namespace root {root}: {exc}"
        ) from exc
    if canonical_root != root:
        raise RunDiscoveryError(
            f"Run namespace root escapes its canonical path: {root} -> {canonical_root}"
        )
    if active_only and (
        root.name == _ARCHIVE_DIR_NAME
        or _find_archived_bundle_checked(root) is not None
    ):
        return []

    def raise_walk_error(error: OSError) -> None:
        raise RunDiscoveryError(
            f"Cannot safely walk the Run namespace {root}: {error}"
        ) from error

    run_dirs: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(
        canonical_root,
        topdown=True,
        onerror=raise_walk_error,
        followlinks=False,
    ):
        current = Path(dirpath)
        _require_checked_directory(current, canonical_root)

        if _MANIFEST_FILE in filenames:
            manifest_path = current / _MANIFEST_FILE
            try:
                manifest_metadata = manifest_path.lstat()
            except OSError as exc:
                raise RunDiscoveryError(
                    f"Cannot inspect Run manifest {manifest_path}: {exc}"
                ) from exc
            if (
                not stat.S_ISREG(manifest_metadata.st_mode)
                or manifest_metadata.st_nlink != 1
            ):
                raise RunDiscoveryError(
                    f"Run manifest must be a single-link regular file: {manifest_path}"
                )
            if (
                not active_only
                or _read_run_status(current) not in _INACTIVE_RUN_STATUSES
            ):
                run_dirs.append(current.resolve())
            # Simulator output below an admitted Run is payload, not namespace.
            dirnames[:] = []
            continue

        if active_only and _archive_marker_exists_checked(current):
            dirnames[:] = []
            continue

        visible_children: list[str] = []
        for dirname in dirnames:
            child = current / dirname
            _require_checked_directory(child, canonical_root)
            if _is_internal_staging_dir(dirname):
                continue
            if active_only and dirname == _ARCHIVE_DIR_NAME:
                continue
            if active_only and _archive_marker_exists_checked(child):
                continue
            visible_children.append(dirname)
        dirnames[:] = visible_children

    return sorted(run_dirs)


def _require_checked_directory(path: Path, root: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RunDiscoveryError(
            f"Cannot inspect directory while walking the Run namespace: {path}: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise RunDiscoveryError(
            f"Unsafe symbolic link directory in the Run namespace: {path}"
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise RunDiscoveryError(
            f"Non-directory entry appeared in the Run namespace walk: {path}"
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RunDiscoveryError(
            f"Cannot resolve directory while walking the Run namespace: {path}: {exc}"
        ) from exc
    if not resolved.is_relative_to(root):
        raise RunDiscoveryError(
            f"Directory escapes the Run namespace: {path} -> {resolved}"
        )


def _archive_marker_exists_checked(path: Path) -> bool:
    marker = path / ARCHIVE_BUNDLE_METADATA_FILE
    if not os.path.lexists(marker):
        return False
    try:
        metadata = marker.lstat()
    except OSError as exc:
        raise RunDiscoveryError(
            f"Cannot inspect archive marker {marker}: {exc}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RunDiscoveryError(
            f"Archive marker must be a single-link regular file: {marker}"
        )
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(marker, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
        ):
            raise RunDiscoveryError(
                f"Archive marker changed while being opened: {marker}"
            )
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 64 * 1024):
            total += len(chunk)
            if total > 1024 * 1024:
                raise RunDiscoveryError(f"Archive marker is too large: {marker}")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        current = marker.lstat()
    except OSError as exc:
        raise RunDiscoveryError(
            f"Cannot safely read archive marker {marker}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    opened_identity = (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
        opened.st_nlink,
    )
    if opened_identity != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_nlink,
    ) or opened_identity != (
        current.st_dev,
        current.st_ino,
        current.st_size,
        current.st_mtime_ns,
        current.st_nlink,
    ):
        raise RunDiscoveryError(f"Archive marker changed while being read: {marker}")
    try:
        raw = tomllib.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RunDiscoveryError(f"Invalid archive marker {marker}: {exc}") from exc
    bundle = raw.get("bundle")
    if not isinstance(bundle, dict):
        raise RunDiscoveryError(f"Archive marker lacks [bundle]: {marker}")
    archived_from = bundle.get("archived_from")
    format_version = bundle.get("format_version")
    run_count = bundle.get("run_count")
    adopted_ids = bundle.get("adopted_run_ids")
    if not isinstance(archived_from, str) or not archived_from:
        raise RunDiscoveryError(
            f"Archive marker has invalid bundle.archived_from: {marker}"
        )
    if format_version is not None and (
        type(format_version) is not int or format_version != 1
    ):
        raise RunDiscoveryError(
            f"Archive marker has unsupported format_version: {marker}"
        )
    if run_count is not None and (type(run_count) is not int or run_count < 0):
        raise RunDiscoveryError(f"Archive marker has invalid run_count: {marker}")
    if adopted_ids is not None and (
        not isinstance(adopted_ids, list)
        or any(not isinstance(item, str) or not item for item in adopted_ids)
        or len(set(adopted_ids)) != len(adopted_ids)
    ):
        raise RunDiscoveryError(f"Archive marker has invalid adopted_run_ids: {marker}")
    return True


def _find_archived_bundle_checked(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if _archive_marker_exists_checked(candidate):
            return candidate
        if candidate.name == "runs":
            break
    return None


def _read_run_status(run_dir: Path) -> str | None:
    """Return a best-effort run status for active-view filtering."""
    try:
        with open(run_dir / _MANIFEST_FILE, "rb") as f:
            data = tomllib.load(f)
        run_section = data.get("run", {})
        if not isinstance(run_section, dict):
            return None
        status = run_section.get("status")
        return str(status) if status is not None else None
    except (OSError, TypeError, ValueError):
        return None


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


def require_run_directory(path: Path) -> Path:
    """Validate an explicit path as a canonical formal Run directory."""
    resolved = path.resolve()
    try:
        run_id = _read_run_id(resolved)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise RunNotFoundError(f"Invalid Run manifest at {resolved}: {exc}") from exc
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise RunNotFoundError(
            f"Manifest at {resolved} is not a formal Run: "
            "run.id must match RYYYYMMDD-NNNN"
        )
    return resolved


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
