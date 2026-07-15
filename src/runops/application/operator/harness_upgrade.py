"""Application orchestration for versioned harness upgrades."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from runops.core.upgrade_chain import (
    UpgradePlanError,
    build_upgrade_plan,
    latest_version_in_versions,
)

_PYPI_JSON_URL = "https://pypi.org/pypi/runops/json"

VersionSource = Callable[[], Iterable[str]]
AppliedVersionSource = Callable[[Path], str | None]
ExecutableLookup = Callable[[str], str | None]


class CommandResult(Protocol):
    """Minimal result returned by an injected command runner."""

    returncode: int


class CommandRunner(Protocol):
    """Run one exact-version harness upgrade command."""

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        project_dir: Path,
    ) -> CommandResult: ...


@dataclass(frozen=True)
class HarnessUpgradeRequest:
    """Inputs required to plan a versioned harness upgrade."""

    project_dir: Path
    current_runtime_version: str
    target: str | None = None
    allow_major: bool = False
    force: bool = False


@dataclass(frozen=True)
class HarnessUpgradeStep:
    """One exact-version command in a harness upgrade plan."""

    from_version: str
    to_version: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class HarnessUpgradePlan:
    """Resolved, non-mutating harness upgrade plan."""

    project_dir: Path
    applied_version: str
    current_runtime_version: str
    target_version: str
    steps: tuple[HarnessUpgradeStep, ...]


@dataclass(frozen=True)
class HarnessUpgradeResult:
    """Successfully completed steps from an applied upgrade plan."""

    completed: tuple[HarnessUpgradeStep, ...]


class HarnessUpgradeStepError(RuntimeError):
    """An exact-version upgrade command returned a non-zero status."""

    def __init__(
        self,
        *,
        step: HarnessUpgradeStep,
        returncode: int,
    ) -> None:
        self.step = step
        self.returncode = returncode
        super().__init__(
            f"Upgrade step failed: {step.from_version} -> {step.to_version}"
        )


def plan_harness_upgrade(
    request: HarnessUpgradeRequest,
    *,
    applied_version_source: AppliedVersionSource,
    version_source: VersionSource | None = None,
    executable_lookup: ExecutableLookup | None = None,
) -> HarnessUpgradePlan:
    """Resolve versions and exact command vectors without mutating the project."""
    project_dir = request.project_dir.resolve()
    available_versions = tuple(
        str(version) for version in (version_source or _fetch_pypi_runops_versions)()
    )
    target_version = _resolve_upgrade_target(
        requested_target=request.target,
        current_runtime_version=request.current_runtime_version,
        available_versions=available_versions,
    )
    applied_version = applied_version_source(project_dir)
    core_plan = build_upgrade_plan(
        applied_version=applied_version,
        current_runtime_version=request.current_runtime_version,
        target_version=target_version,
        available_versions=available_versions,
        allow_major=request.allow_major,
    )
    uvx = (executable_lookup or shutil.which)("uvx") or "uvx"
    steps = tuple(
        HarnessUpgradeStep(
            from_version=step.from_version,
            to_version=step.to_version,
            command=_uvx_update_harness_command(
                uvx=uvx,
                project_dir=project_dir,
                to_version=step.to_version,
                from_version=step.from_version,
                force=request.force,
            ),
        )
        for step in core_plan.steps
    )
    return HarnessUpgradePlan(
        project_dir=project_dir,
        applied_version=core_plan.applied_version,
        current_runtime_version=core_plan.current_runtime_version,
        target_version=core_plan.target_version,
        steps=steps,
    )


def apply_harness_upgrade(
    plan: HarnessUpgradePlan,
    *,
    runner: CommandRunner | None = None,
    before_step: Callable[[int, int, HarnessUpgradeStep], None] | None = None,
) -> HarnessUpgradeResult:
    """Run planned commands sequentially and stop at the first failure."""
    execute = runner or _run_upgrade_step_command
    completed: list[HarnessUpgradeStep] = []
    for index, step in enumerate(plan.steps, start=1):
        if before_step is not None:
            before_step(index, len(plan.steps), step)
        result = execute(step.command, project_dir=plan.project_dir)
        if result.returncode != 0:
            raise HarnessUpgradeStepError(
                step=step,
                returncode=result.returncode,
            )
        completed.append(step)
    return HarnessUpgradeResult(completed=tuple(completed))


def _fetch_pypi_runops_versions(timeout: float = 2.0) -> tuple[str, ...]:
    """Return published runops versions from PyPI, or empty on lookup failure."""
    request = urllib.request.Request(
        _PYPI_JSON_URL,
        headers={"User-Agent": "runops upgrade-chain"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        TimeoutError,
        urllib.error.URLError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return ()

    if not isinstance(payload, dict):
        return ()
    releases = payload.get("releases")
    if not isinstance(releases, dict):
        return ()
    return tuple(str(version) for version in releases if isinstance(version, str))


def _resolve_upgrade_target(
    *,
    requested_target: str | None,
    current_runtime_version: str,
    available_versions: tuple[str, ...],
) -> str:
    if requested_target is None:
        return current_runtime_version
    if requested_target == "latest":
        latest = latest_version_in_versions(available_versions)
        if latest is None:
            raise UpgradePlanError("Could not resolve latest runops version from PyPI.")
        return latest
    return requested_target


def _uvx_update_harness_command(
    *,
    uvx: str,
    project_dir: Path,
    to_version: str,
    from_version: str,
    force: bool,
) -> tuple[str, ...]:
    command = [
        uvx,
        "--from",
        f"runops=={to_version}",
        "runo",
        "update-harness",
        str(project_dir),
        "--upgrade-step",
        "--from-version",
        from_version,
    ]
    if force:
        command.append("--force")
    return tuple(command)


def _run_upgrade_step_command(
    command: tuple[str, ...],
    *,
    project_dir: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=project_dir,
        text=True,
        check=False,
    )


__all__ = [
    "HarnessUpgradePlan",
    "HarnessUpgradeRequest",
    "HarnessUpgradeResult",
    "HarnessUpgradeStep",
    "HarnessUpgradeStepError",
    "apply_harness_upgrade",
    "plan_harness_upgrade",
]
