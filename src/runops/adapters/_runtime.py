"""Shared executable runtime resolution for bundled adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runops.adapters._utils import find_venv

_RESOLVER_MODES = frozenset({"package", "local_source", "local_executable"})


@dataclass(frozen=True)
class ExecutableRuntimeDefaults:
    """Simulator-specific defaults used by executable runtime resolution."""

    executable: str | None = None
    build_command: str = ""
    discover_venv: bool = False
    require_executable: bool = True


def resolve_executable_runtime(
    config: Mapping[str, Any],
    mode: str,
    *,
    defaults: ExecutableRuntimeDefaults,
    which: Callable[[str], str | None],
    start_dir: Path,
) -> dict[str, Any]:
    """Resolve one of the three executable-backed runtime modes.

    Args:
        config: Simulator configuration from ``simulators.toml``.
        mode: ``package``, ``local_source``, or ``local_executable``.
        defaults: Simulator-specific executable and build defaults.
        which: Injected executable lookup used by package mode.
        start_dir: Starting directory for optional virtualenv discovery.

    Returns:
        Runtime information preserving the established mode-specific keys.

    Raises:
        ValueError: If the mode is unsupported or required data is missing.
    """
    if mode not in _RESOLVER_MODES:
        msg = (
            f"Unsupported resolver_mode '{mode}'. "
            f"Expected one of {sorted(_RESOLVER_MODES)}"
        )
        raise ValueError(msg)

    runtime: dict[str, Any] = {"resolver_mode": mode}
    if defaults.discover_venv:
        venv_path = config.get("venv_path", "")
        if not venv_path:
            found = find_venv(start_dir)
            if found:
                venv_path = str(found)
        if venv_path:
            runtime["venv_path"] = venv_path

    if mode == "package":
        executable = config.get("executable", defaults.executable)
        _require_executable(executable, mode=mode, defaults=defaults)
        resolved = which(executable)
        runtime["executable"] = resolved if resolved else executable
        runtime["source"] = "package"
        return runtime

    if mode == "local_source":
        source_repo = config.get("source_repo", "")
        if not source_repo:
            msg = "source_repo required for local_source mode"
            raise ValueError(msg)
        executable = config.get("executable", defaults.executable)
        _require_executable(executable, mode=mode, defaults=defaults)
        runtime["source_repo"] = source_repo
        runtime["executable"] = executable
        runtime["build_command"] = config.get(
            "build_command",
            defaults.build_command,
        )
        return runtime

    executable = config.get("executable", "")
    if not executable:
        msg = "executable path required for local_executable mode"
        raise ValueError(msg)
    runtime["executable"] = executable
    return runtime


def _require_executable(
    executable: Any,
    *,
    mode: str,
    defaults: ExecutableRuntimeDefaults,
) -> None:
    """Raise when an adapter requires a non-empty executable value."""
    if executable or not defaults.require_executable:
        return
    msg = f"executable required for {mode} mode"
    raise ValueError(msg)


__all__ = [
    "ExecutableRuntimeDefaults",
    "resolve_executable_runtime",
]
