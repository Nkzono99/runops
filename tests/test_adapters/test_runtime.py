"""Tests for shared executable runtime resolution."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from runops.adapters._runtime import (
    ExecutableRuntimeDefaults,
    resolve_executable_runtime,
)


def test_runtime_defaults_are_frozen() -> None:
    defaults = ExecutableRuntimeDefaults(executable="solver")

    with pytest.raises(FrozenInstanceError):
        defaults.executable = "other"  # type: ignore[misc]


def test_package_mode_uses_injected_lookup(tmp_path: Path) -> None:
    looked_up: list[str] = []

    def which(executable: str) -> str | None:
        looked_up.append(executable)
        return "/opt/package/bin/solver"

    runtime = resolve_executable_runtime(
        {},
        "package",
        defaults=ExecutableRuntimeDefaults(executable="solver"),
        which=which,
        start_dir=tmp_path,
    )

    assert runtime == {
        "resolver_mode": "package",
        "executable": "/opt/package/bin/solver",
        "source": "package",
    }
    assert looked_up == ["solver"]


def test_package_mode_falls_back_to_configured_name(tmp_path: Path) -> None:
    runtime = resolve_executable_runtime(
        {"executable": "configured-solver"},
        "package",
        defaults=ExecutableRuntimeDefaults(executable="default-solver"),
        which=lambda _executable: None,
        start_dir=tmp_path,
    )

    assert runtime["executable"] == "configured-solver"


def test_local_source_mode_applies_explicit_defaults(tmp_path: Path) -> None:
    runtime = resolve_executable_runtime(
        {"source_repo": "/src/simulator"},
        "local_source",
        defaults=ExecutableRuntimeDefaults(
            executable="solver",
            build_command="make build",
        ),
        which=lambda _executable: None,
        start_dir=tmp_path,
    )

    assert runtime == {
        "resolver_mode": "local_source",
        "source_repo": "/src/simulator",
        "executable": "solver",
        "build_command": "make build",
    }


def test_local_source_mode_prefers_configured_values(tmp_path: Path) -> None:
    runtime = resolve_executable_runtime(
        {
            "source_repo": "/src/simulator",
            "executable": "/src/simulator/build/custom",
            "build_command": "ninja custom",
        },
        "local_source",
        defaults=ExecutableRuntimeDefaults(
            executable="solver",
            build_command="make build",
        ),
        which=lambda _executable: None,
        start_dir=tmp_path,
    )

    assert runtime["executable"] == "/src/simulator/build/custom"
    assert runtime["build_command"] == "ninja custom"


def test_local_executable_mode_requires_configured_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="executable"):
        resolve_executable_runtime(
            {},
            "local_executable",
            defaults=ExecutableRuntimeDefaults(executable="package-default"),
            which=lambda _executable: None,
            start_dir=tmp_path,
        )


def test_local_executable_mode_preserves_path(tmp_path: Path) -> None:
    runtime = resolve_executable_runtime(
        {"executable": "/opt/simulator/bin/solver"},
        "local_executable",
        defaults=ExecutableRuntimeDefaults(executable="package-default"),
        which=lambda _executable: None,
        start_dir=tmp_path,
    )

    assert runtime == {
        "resolver_mode": "local_executable",
        "executable": "/opt/simulator/bin/solver",
    }


@pytest.mark.parametrize("mode", ["package", "local_source"])
def test_modes_without_executable_or_default_raise(
    mode: str,
    tmp_path: Path,
) -> None:
    config = {"source_repo": "/src/simulator"} if mode == "local_source" else {}

    with pytest.raises(ValueError, match="executable"):
        resolve_executable_runtime(
            config,
            mode,
            defaults=ExecutableRuntimeDefaults(),
            which=lambda _executable: None,
            start_dir=tmp_path,
        )


def test_local_source_mode_requires_source_repo(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source_repo"):
        resolve_executable_runtime(
            {},
            "local_source",
            defaults=ExecutableRuntimeDefaults(executable="solver"),
            which=lambda _executable: None,
            start_dir=tmp_path,
        )


def test_invalid_mode_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported resolver_mode"):
        resolve_executable_runtime(
            {},
            "container",
            defaults=ExecutableRuntimeDefaults(executable="solver"),
            which=lambda _executable: None,
            start_dir=tmp_path,
        )


def test_venv_discovery_starts_from_injected_directory(tmp_path: Path) -> None:
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "activate").touch()
    start_dir = tmp_path / "projects" / "case"
    start_dir.mkdir(parents=True)

    runtime = resolve_executable_runtime(
        {},
        "package",
        defaults=ExecutableRuntimeDefaults(
            executable="solver",
            discover_venv=True,
        ),
        which=lambda executable: executable,
        start_dir=start_dir,
    )

    assert runtime["venv_path"] == str(venv)


def test_explicit_venv_path_skips_discovery(tmp_path: Path) -> None:
    runtime = resolve_executable_runtime(
        {"venv_path": "/opt/simulator-venv"},
        "package",
        defaults=ExecutableRuntimeDefaults(
            executable="solver",
            discover_venv=True,
        ),
        which=lambda executable: executable,
        start_dir=tmp_path,
    )

    assert runtime["venv_path"] == "/opt/simulator-venv"
