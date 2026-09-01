"""Staging helpers for transactional run creation."""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import stat
import warnings
from dataclasses import dataclass
from pathlib import Path

from runops.core.exceptions import SimctlError
from runops.core.run import next_run_id
from runops.core.survey import NamingConfig, render_run_directory_name

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


class MoveCommittedError(RuntimeError):
    """A no-replace rename left an ambiguous post-failure topology.

    This intentionally does not inherit from ``SimctlError``.  Transaction
    callers commonly catch ``SimctlError`` only when the source still owns the
    data; catching this exception in those branches could manufacture a second
    copy or omit a recovery receipt.
    """

    def __init__(self, source: Path, destination: Path, detail: str) -> None:
        super().__init__(
            "atomic move is visible at the destination but could not be made "
            f"durable or rolled back: {source} -> {destination}: {detail}"
        )
        self.source = source
        self.destination = destination


class MoveDurabilityWarning(RuntimeWarning):
    """The rename committed, but parent-directory durability is unconfirmed."""


@dataclass(frozen=True)
class MoveOutcome:
    """Observable result of an atomic no-replace move."""

    source: Path
    destination: Path
    durability_confirmed: bool
    warning: str = ""


def commit_staged_directory(staging_dir: Path, final_dir: Path) -> MoveOutcome:
    """Publish a staged directory without replacing another creator's path.

    Run creation is a Linux/HPC workflow, so use ``renameat2`` with
    ``RENAME_NOREPLACE`` instead of the racy ``exists()`` + ``Path.rename``
    sequence.  Fsyncing the parent makes the visible Run durable before a
    caller persists its Experiment usage ledger.  If that fsync fails and the
    rename cannot be rolled back, the move remains a logical success with a
    ``MoveDurabilityWarning``; callers must continue the transaction from the
    destination instead of reconstructing the source.
    """
    if staging_dir.is_symlink():
        raise SimctlError(f"staged directory must not be a symlink: {staging_dir}")
    source = staging_dir.parent.resolve() / staging_dir.name
    destination = final_dir.parent.resolve() / final_dir.name
    if source.parent != destination.parent:
        raise SimctlError(
            "staged and final directories must share a parent directory: "
            f"{source} -> {destination}"
        )
    if not source.is_dir():
        raise SimctlError(f"staged path must be a real directory: {source}")

    return move_directory_noreplace(source, destination)


def move_directory_noreplace(source_dir: Path, destination_dir: Path) -> MoveOutcome:
    """Atomically move a directory without replacing an existing path.

    The source and destination may have different parents, but must be on the
    same filesystem.  Cross-filesystem copy/delete is deliberately rejected:
    it cannot provide the atomic publication and crash semantics required by
    Run and bundle lifecycle operations.
    """
    if source_dir.is_symlink():
        raise SimctlError(f"move source must not be a symlink: {source_dir}")
    source = source_dir.parent.resolve() / source_dir.name
    destination = destination_dir.parent.resolve() / destination_dir.name
    if not source.is_dir():
        raise SimctlError(f"move source must be a real directory: {source}")

    return _move_path_noreplace(source, destination)


def move_path_noreplace(source_path: Path, destination_path: Path) -> MoveOutcome:
    """Atomically move one regular file or directory without replacement."""
    if source_path.is_symlink():
        raise SimctlError(f"move source must not be a symlink: {source_path}")
    source = source_path.parent.resolve() / source_path.name
    destination = destination_path.parent.resolve() / destination_path.name
    try:
        metadata = source.lstat()
    except FileNotFoundError as exc:
        raise SimctlError(f"move source does not exist: {source}") from exc
    if (
        not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode))
        or metadata.st_nlink < 1
    ):
        raise SimctlError(f"move source must be a regular file or directory: {source}")

    return _move_path_noreplace(source, destination)


def _move_path_noreplace(source: Path, destination: Path) -> MoveOutcome:
    """Perform one validated Linux ``RENAME_NOREPLACE`` move."""
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise SimctlError(
            f"move destination parent must be a real directory: {destination.parent}"
        )

    _rename_noreplace(source, destination)
    try:
        _fsync_directory(destination.parent)
        if source.parent != destination.parent:
            _fsync_directory(source.parent)
    except OSError as durability_error:
        # Keep the public contract unambiguous: an ordinary exception means
        # the source path still owns the data.  If directory durability fails
        # after rename, atomically move it back before reporting failure.
        try:
            _rename_noreplace(destination, source)
        except (OSError, SimctlError) as rollback_error:
            source_exists = os.path.lexists(source)
            destination_exists = os.path.lexists(destination)
            detail = (
                f"fsync failed ({durability_error}); rollback failed ({rollback_error})"
            )
            if destination_exists and not source_exists:
                message = (
                    "atomic move committed at the destination, but parent-directory "
                    f"durability is unconfirmed: {source} -> {destination}: {detail}"
                )
                warnings.warn(message, MoveDurabilityWarning, stacklevel=3)
                return MoveOutcome(
                    source=source,
                    destination=destination,
                    durability_confirmed=False,
                    warning=message,
                )
            raise MoveCommittedError(
                source,
                destination,
                f"{detail}; source_exists={source_exists}; "
                f"destination_exists={destination_exists}",
            ) from durability_error
        rollback_fsync_errors: list[str] = []
        for parent in dict.fromkeys((source.parent, destination.parent)):
            try:
                _fsync_directory(parent)
            except OSError as rollback_fsync_error:
                rollback_fsync_errors.append(str(rollback_fsync_error))
        detail = (
            "; rollback fsync also failed: " + "; ".join(rollback_fsync_errors)
            if rollback_fsync_errors
            else ""
        )
        raise SimctlError(
            f"atomic move durability failed and the rename was rolled back: "
            f"{source} -> {destination}: {durability_error}{detail}"
        ) from durability_error
    return MoveOutcome(
        source=source,
        destination=destination,
        durability_confirmed=True,
    )


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Invoke Linux renameat2 without performing durability fsyncs."""
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise SimctlError("atomic no-replace move requires Linux renameat2")
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise FileExistsError(error_number, os.strerror(error_number), destination)
        if error_number == errno.EXDEV:
            raise SimctlError(
                "atomic no-replace move requires source and destination "
                f"on the same filesystem: {source} -> {destination}"
            )
        raise OSError(error_number, os.strerror(error_number), destination)


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def copy_case_files(case_dir: Path, input_dir: Path) -> list[str]:
    src_dir = case_dir / "input"
    if src_dir.is_symlink():
        raise SimctlError(f"case input directory must not be a symlink: {src_dir}")
    if not src_dir.is_dir():
        return []
    input_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for src in src_dir.rglob("*"):
        if src.is_symlink():
            raise SimctlError(f"case input must not contain symlinks: {src}")
        if src.is_dir():
            continue
        if not src.is_file():
            raise SimctlError(f"case input must contain only regular files: {src}")
        rel = src.relative_to(src_dir)
        dest = input_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        created.append(str(Path("input") / rel))
    return created


def next_available_run_target(
    parent_dir: Path,
    known_ids: set[str],
    *,
    display_name: str = "",
    naming: NamingConfig | None = None,
) -> tuple[str, Path]:
    """Return the next run_id whose final directory is currently free."""
    while True:
        run_id = next_run_id(known_ids)
        directory_name = render_run_directory_name(run_id, display_name, naming)
        final_run_dir = (parent_dir / directory_name).resolve()
        claim_dir = parent_dir / f".tmp-{run_id}"
        existing_candidates = list(parent_dir.glob(f"{run_id}*"))
        if not existing_candidates and not claim_dir.exists():
            return run_id, final_run_dir
        known_ids.add(run_id)


def reserved_run_target(
    parent_dir: Path,
    run_id: str,
    *,
    display_name: str = "",
    naming: NamingConfig | None = None,
) -> Path:
    """Return the no-clobber destination for a previously reserved run ID."""
    directory_name = render_run_directory_name(run_id, display_name, naming)
    final_run_dir = (parent_dir / directory_name).resolve()
    existing_candidates = list(parent_dir.glob(f"{run_id}*"))
    if existing_candidates or final_run_dir.exists():
        from runops.core.exceptions import DuplicateRunIdError

        paths = [str(path) for path in existing_candidates]
        if final_run_dir.exists() and str(final_run_dir) not in paths:
            paths.append(str(final_run_dir))
        raise DuplicateRunIdError(run_id, paths)
    return final_run_dir
