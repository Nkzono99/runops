"""Project-wide, durable run identity allocation."""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import stat
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

from runops.application.run_discovery import (
    StrictRunNamespaceError,
    collect_run_manifests_strict,
)
from runops.application.state_root import require_project_state_root
from runops.core.exceptions import SimctlError
from runops.core.run import RunInfo, create_run_directory, generate_run_id

_LOCK_NAME = "run-id.lock"
_SEQUENCE_NAME = "run-id-sequence.toml"
_RUN_ID = re.compile(r"^R(?P<date>\d{8})-(?P<sequence>\d{4})$")


class RunIdentityAllocationError(SimctlError):
    """Raised when the project-wide identity ledger cannot be used safely."""


@contextmanager
def project_run_identity_lock(project_root: Path) -> Iterator[None]:
    """Serialize identity allocation across every survey and creation path.

    The lock file is persistent so concurrent processes never lock different
    inodes for the same project.  It is state coordination, not the identity
    source of truth; manifests and the monotonic sequence ledger remain the
    durable inputs to allocation.
    """
    state_dir = require_project_state_root(project_root)
    lock_path = state_dir / _LOCK_NAME
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise RunIdentityAllocationError(
            f"Failed to open project run identity lock {lock_path}: {exc}"
        ) from exc
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise RunIdentityAllocationError(
                f"Failed to lock project run identity allocator {lock_path}: {exc}"
            ) from exc
        yield
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)


def reserve_run_id(
    project_root: Path,
    existing_ids: set[str],
    *,
    target_date: date | None = None,
) -> str:
    """Reserve and durably burn the next project-wide ``R...`` identity.

    A failed creation intentionally leaves a sequence gap.  Reusing an ID
    after a partial failure or deletion is more dangerous than a harmless gap.
    """
    root = project_root.resolve()
    selected_date = target_date or date.today()
    date_key = selected_date.strftime("%Y%m%d")
    with project_run_identity_lock(root):
        # Callers may only know about their destination subtree.  Re-scan the
        # canonical project Run namespace while holding the allocator lock so
        # an empty/new ledger cannot reuse an older ID elsewhere in ``runs``.
        observed_ids = set(existing_ids)
        observed_ids.update(_collect_existing_run_ids_strict(root / "runs"))
        ledger_path = root / ".runops" / _SEQUENCE_NAME
        ledger = _read_sequence_ledger(ledger_path)
        dates = ledger.setdefault("dates", {})
        if not isinstance(dates, dict):
            raise RunIdentityAllocationError(
                f"Invalid [{_SEQUENCE_NAME}] dates table in {ledger_path}"
            )

        prefix = f"R{date_key}-"
        observed = 0
        for run_id in observed_ids:
            if not run_id.startswith(prefix):
                continue
            try:
                observed = max(observed, int(run_id[len(prefix) :]))
            except ValueError:
                continue

        stored_raw = dates.get(date_key, 0)
        if isinstance(stored_raw, bool) or not isinstance(stored_raw, int):
            raise RunIdentityAllocationError(
                f"Invalid sequence for {date_key!r} in {ledger_path}"
            )
        sequence = max(observed, stored_raw) + 1
        run_id = generate_run_id(date_key, sequence)
        dates[date_key] = sequence
        _write_sequence_ledger(ledger_path, ledger)
        return run_id


def release_unused_run_id(project_root: Path, run_id: str) -> bool:
    """Release the latest reservation after a successful no-create reuse.

    Failed creation still burns its reservation.  This narrowly compensates a
    successful scientific-identity reuse, where no new Run ever became visible.
    If another allocator has already advanced the same date, the harmless gap
    is retained instead of rewinding past a concurrent reservation.
    """
    match = _RUN_ID.fullmatch(run_id)
    if match is None:
        raise RunIdentityAllocationError(f"Invalid reserved Run ID: {run_id}")
    root = project_root.resolve()
    date_key = match.group("date")
    sequence = int(match.group("sequence"))
    with project_run_identity_lock(root):
        observed_ids = _collect_existing_run_ids_strict(root / "runs")
        if run_id in observed_ids:
            return False
        ledger_path = root / ".runops" / _SEQUENCE_NAME
        ledger = _read_sequence_ledger(ledger_path)
        dates = ledger.setdefault("dates", {})
        if not isinstance(dates, dict):
            raise RunIdentityAllocationError(
                f"Invalid [{_SEQUENCE_NAME}] dates table in {ledger_path}"
            )
        current = dates.get(date_key, 0)
        if isinstance(current, bool) or not isinstance(current, int):
            raise RunIdentityAllocationError(
                f"Invalid sequence for {date_key!r} in {ledger_path}"
            )
        if current != sequence:
            return False
        observed = max(
            (
                int(candidate.rsplit("-", 1)[1])
                for candidate in observed_ids
                if candidate.startswith(f"R{date_key}-")
            ),
            default=0,
        )
        dates[date_key] = max(observed, sequence - 1)
        _write_sequence_ledger(ledger_path, ledger)
        return True


def _collect_existing_run_ids_strict(runs_dir: Path) -> set[str]:
    """Read every formal manifest or stop allocation on ambiguous state."""
    try:
        return {
            str(manifest.run["id"])
            for _run_dir, manifest in collect_run_manifests_strict(runs_dir)
        }
    except StrictRunNamespaceError as exc:
        raise RunIdentityAllocationError(str(exc)) from exc


def create_reserved_run_directory(
    project_root: Path,
    parent_dir: Path,
    existing_ids: set[str],
    *,
    display_name: str = "",
    params: dict[str, Any] | None = None,
) -> RunInfo:
    """Reserve an ID and create the standard empty run directory for it."""
    run_id = reserve_run_id(project_root, existing_ids)
    run_dir = create_run_directory(parent_dir, run_id)
    return RunInfo(
        run_id=run_id,
        run_dir=run_dir,
        display_name=display_name,
        created_at=datetime.now(tz=timezone.utc).isoformat(),
        params=dict(params or {}),
    )


def _read_sequence_ledger(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"schema_version": 1, "dates": {}}
    except OSError as exc:
        raise RunIdentityAllocationError(
            f"Failed to inspect run identity sequence ledger {path}: {exc}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RunIdentityAllocationError(
            f"Run identity sequence ledger must be a single-link regular file: {path}"
        )
    try:
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened_metadata = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened_metadata.st_mode)
                or opened_metadata.st_nlink != 1
                or (opened_metadata.st_dev, opened_metadata.st_ino)
                != (metadata.st_dev, metadata.st_ino)
            ):
                raise RunIdentityAllocationError(
                    "Run identity sequence ledger changed while opening or is not "
                    f"a single-link regular file: {path}"
                )
            raw = tomllib.load(stream)
    except RunIdentityAllocationError:
        raise
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise RunIdentityAllocationError(
            f"Failed to read run identity sequence ledger {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise RunIdentityAllocationError(
            f"Invalid run identity sequence ledger: {path}"
        )
    version = raw.get("schema_version", 1)
    if type(version) is not int or version != 1:
        raise RunIdentityAllocationError(
            f"Unsupported run identity ledger schema_version {version!r}"
        )
    return dict(raw)


def _write_sequence_ledger(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            tomli_w.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
        directory_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except (OSError, TypeError) as exc:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise RunIdentityAllocationError(
            f"Failed to persist run identity sequence ledger {path}: {exc}"
        ) from exc
