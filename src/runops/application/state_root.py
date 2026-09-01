"""Safety boundary for project-local mutable coordination state."""

from __future__ import annotations

import stat
from pathlib import Path

from runops.core.exceptions import SimctlError


class ProjectStateRootError(SimctlError):
    """Raised when ``<project>/.runops`` is not a real local directory."""


def require_project_state_root(project_root: Path) -> Path:
    """Return a canonical project-local ``.runops`` directory or fail closed."""
    root = project_root.resolve()
    state_dir = root / ".runops"
    try:
        metadata = state_dir.lstat()
    except FileNotFoundError:
        try:
            state_dir.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise ProjectStateRootError(
                f"failed to create project state root {state_dir}: {exc}"
            ) from exc
        try:
            metadata = state_dir.lstat()
        except OSError as exc:
            raise ProjectStateRootError(
                f"failed to inspect project state root {state_dir}: {exc}"
            ) from exc
    except OSError as exc:
        raise ProjectStateRootError(
            f"failed to inspect project state root {state_dir}: {exc}"
        ) from exc

    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ProjectStateRootError(
            "project state root must be a real directory, not a symbolic link "
            f"or another file type: {state_dir}"
        )
    try:
        canonical = state_dir.resolve(strict=True)
    except OSError as exc:
        raise ProjectStateRootError(
            f"failed to resolve project state root {state_dir}: {exc}"
        ) from exc
    if canonical != state_dir:
        raise ProjectStateRootError(
            f"project state root escapes the project: {state_dir} -> {canonical}"
        )
    return canonical


__all__ = ["ProjectStateRootError", "require_project_state_root"]
