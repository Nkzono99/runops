"""Project-wide serialization for formal Run namespace publication."""

from __future__ import annotations

import contextlib
import fcntl
import os
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from runops.application.state_root import require_project_state_root
from runops.core.exceptions import SimctlError

_LOCK_FILE = "run-namespace.lock"
_LOCAL = threading.local()


@contextmanager
def run_namespace_guard(project_root: Path) -> Iterator[None]:
    """Serialize formal Run publication and parent-directory bundle moves."""
    state_root = require_project_state_root(project_root)
    lock_path = state_root / _LOCK_FILE
    key = str(lock_path)
    held = getattr(_LOCAL, "held", None)
    if held is None:
        held = set()
        _LOCAL.held = held
    if key in held:
        yield
        return
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise SimctlError(
            f"failed to open Run namespace lock {lock_path}: {exc}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SimctlError(f"Run namespace lock must be single-link: {lock_path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise SimctlError(
                f"failed to lock Run namespace {lock_path}: {exc}"
            ) from exc
        held.add(key)
        yield
    finally:
        held.discard(key)
        with contextlib.suppress(OSError):
            os.close(descriptor)


__all__ = ["run_namespace_guard"]
