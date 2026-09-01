"""Fail-closed discovery for the project-wide formal Run namespace."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, read_manifest

_MANIFEST_NAME = "manifest.toml"
_INTERNAL_TRANSACTION_PREFIXES = (".tmp-", ".delete-")
_RUN_ID = re.compile(r"^R\d{8}-\d{4}$")


class StrictRunNamespaceError(SimctlError):
    """Raised when a formal Run namespace cannot be enumerated completely."""


def collect_run_manifests_strict(
    runs_dir: Path,
) -> tuple[tuple[Path, ManifestData], ...]:
    """Return every formal Run manifest or reject an ambiguous namespace."""
    lexical_root = Path(os.path.abspath(runs_dir))
    try:
        root_metadata = lexical_root.lstat()
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise StrictRunNamespaceError(
            f"Cannot inspect the Run namespace root {lexical_root}: {exc}"
        ) from exc
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise StrictRunNamespaceError(
            "Run namespace root must be a real directory, not a symbolic link "
            f"or another file type: {lexical_root}"
        )
    try:
        root = lexical_root.resolve(strict=True)
    except OSError as exc:
        raise StrictRunNamespaceError(
            f"Cannot resolve the Run namespace root {lexical_root}: {exc}"
        ) from exc
    if root != lexical_root:
        raise StrictRunNamespaceError(
            f"Run namespace root escapes its canonical path: {lexical_root} -> {root}"
        )

    def raise_walk_error(error: OSError) -> None:
        raise StrictRunNamespaceError(
            f"Cannot safely walk the Run namespace {root}: {error}"
        ) from error

    ids: set[str] = set()
    records: list[tuple[Path, ManifestData]] = []
    for dirpath, dirnames, filenames in os.walk(
        root,
        topdown=True,
        onerror=raise_walk_error,
        followlinks=False,
    ):
        run_dir = Path(dirpath)
        _require_safe_namespace_directory(run_dir, root)
        if _MANIFEST_NAME in filenames:
            manifest_path = run_dir / _MANIFEST_NAME
            try:
                metadata = manifest_path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise StrictRunNamespaceError(
                        f"Unsafe formal Run manifest: {manifest_path}"
                    )
                manifest = read_manifest(run_dir)
                run_id = str(manifest.run.get("id", "")).strip()
            except StrictRunNamespaceError:
                raise
            except (OSError, SimctlError, TypeError, ValueError) as exc:
                raise StrictRunNamespaceError(
                    f"formal manifest is unreadable at {manifest_path}: {exc}"
                ) from exc
            if _RUN_ID.fullmatch(run_id) is None:
                raise StrictRunNamespaceError(
                    f"Invalid Run ID {run_id!r} in formal manifest {manifest_path}"
                )
            if run_id in ids:
                raise StrictRunNamespaceError(
                    f"Duplicate Run ID {run_id!r} found in the formal namespace"
                )
            ids.add(run_id)
            records.append((run_dir, manifest))
            # A formal Run cannot contain another formal Run. Avoid simulator
            # output trees and their legitimate internal symlinks.
            dirnames[:] = []
            continue

        visible_children: list[str] = []
        for dirname in dirnames:
            child = run_dir / dirname
            _require_safe_namespace_directory(child, root)
            if not dirname.startswith(_INTERNAL_TRANSACTION_PREFIXES):
                visible_children.append(dirname)
        dirnames[:] = visible_children
    return tuple(records)


def resolve_project_run_strict(
    project_root: Path,
    run_id: str,
) -> tuple[Path, ManifestData]:
    """Resolve one immutable Run ID only inside the strict project namespace."""
    if _RUN_ID.fullmatch(run_id) is None:
        raise StrictRunNamespaceError(f"Invalid formal Run ID: {run_id!r}")
    matches = [
        (run_dir, manifest)
        for run_dir, manifest in collect_run_manifests_strict(
            project_root.resolve() / "runs"
        )
        if manifest.run.get("id") == run_id
    ]
    if len(matches) != 1:
        raise StrictRunNamespaceError(
            f"Run {run_id!r} was not found uniquely in the project namespace"
        )
    return matches[0]


def _require_safe_namespace_directory(path: Path, root: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise StrictRunNamespaceError(
            f"Cannot inspect directory while walking the Run namespace: {path}: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise StrictRunNamespaceError(
            f"Unsafe symbolic link directory in the Run namespace: {path}"
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise StrictRunNamespaceError(
            f"Non-directory entry appeared in the Run namespace walk: {path}"
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise StrictRunNamespaceError(
            f"Cannot resolve directory while walking the Run namespace: {path}: {exc}"
        ) from exc
    if not resolved.is_relative_to(root):
        raise StrictRunNamespaceError(
            f"Directory escapes the Run namespace: {path} -> {resolved}"
        )


__all__ = [
    "StrictRunNamespaceError",
    "collect_run_manifests_strict",
    "resolve_project_run_strict",
]
