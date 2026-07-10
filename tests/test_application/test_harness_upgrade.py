"""Tests for versioned harness-upgrade application orchestration."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from runops.application.operator import harness_upgrade as harness_upgrade_module
from runops.application.operator.harness_upgrade import (
    HarnessUpgradeRequest,
    HarnessUpgradeStepError,
    apply_harness_upgrade,
    plan_harness_upgrade,
)
from runops.core.upgrade_chain import UpgradePlanError


def _request(
    tmp_path: Path,
    *,
    target: str | None = "0.9.0",
    allow_major: bool = False,
    force: bool = False,
    no_harnessops: bool = False,
) -> HarnessUpgradeRequest:
    return HarnessUpgradeRequest(
        project_dir=tmp_path,
        current_runtime_version="0.9.0",
        target=target,
        allow_major=allow_major,
        force=force,
        no_harnessops=no_harnessops,
    )


def test_plan_resolves_latest_and_builds_exact_uvx_commands(tmp_path: Path) -> None:
    plan = plan_harness_upgrade(
        _request(
            tmp_path,
            target="latest",
            force=True,
            no_harnessops=True,
        ),
        version_source=lambda: ("0.8.2", "0.9.0", "0.10.1", "0.11.0rc1"),
        applied_version_source=lambda _path: "0.8.0",
        executable_lookup=lambda name: f"/tools/{name}",
    )

    assert plan.applied_version == "0.8.0"
    assert plan.target_version == "0.10.1"
    assert [(step.from_version, step.to_version) for step in plan.steps] == [
        ("0.8.0", "0.8.2"),
        ("0.8.2", "0.9.0"),
        ("0.9.0", "0.10.1"),
    ]
    assert plan.steps[0].command == (
        "/tools/uvx",
        "--from",
        "runops==0.8.2",
        "runo",
        "update-harness",
        str(tmp_path.resolve()),
        "--upgrade-step",
        "--from-version",
        "0.8.0",
        "--force",
        "--no-harnessops",
    )
    assert plan.steps[-1].command[2] == "runops==0.10.1"


def test_plan_exact_target_works_with_empty_version_source(tmp_path: Path) -> None:
    plan = plan_harness_upgrade(
        _request(tmp_path, target="0.9.0"),
        version_source=lambda: (),
        applied_version_source=lambda _path: "0.8.0",
        executable_lookup=lambda _name: None,
    )

    assert plan.target_version == "0.9.0"
    assert [step.command[0] for step in plan.steps] == ["uvx"]
    assert plan.steps[0].command[2] == "runops==0.9.0"


def test_plan_latest_requires_a_published_stable_version(tmp_path: Path) -> None:
    with pytest.raises(UpgradePlanError, match="Could not resolve latest"):
        plan_harness_upgrade(
            _request(tmp_path, target="latest"),
            version_source=lambda: ("0.10.0rc1", "invalid"),
            applied_version_source=lambda _path: "0.8.0",
        )


def test_planning_is_non_mutating_and_never_runs_commands(tmp_path: Path) -> None:
    marker = tmp_path / "unchanged"
    marker.write_text("before", encoding="utf-8")

    plan = plan_harness_upgrade(
        _request(tmp_path),
        version_source=lambda: ("0.9.0",),
        applied_version_source=lambda _path: "0.8.0",
    )

    assert plan.steps
    assert marker.read_text(encoding="utf-8") == "before"


def test_apply_runs_steps_sequentially_and_reports_progress(tmp_path: Path) -> None:
    plan = plan_harness_upgrade(
        _request(tmp_path),
        version_source=lambda: ("0.8.2", "0.9.0"),
        applied_version_source=lambda _path: "0.8.0",
        executable_lookup=lambda _name: "uvx",
    )
    commands: list[tuple[str, ...]] = []
    progress: list[tuple[int, int, str]] = []

    result = apply_harness_upgrade(
        plan,
        runner=lambda command, *, project_dir: (
            commands.append(command) or SimpleNamespace(returncode=0)
        ),
        before_step=lambda index, total, step: progress.append(
            (index, total, step.to_version)
        ),
    )

    assert commands == [step.command for step in plan.steps]
    assert progress == [(1, 2, "0.8.2"), (2, 2, "0.9.0")]
    assert result.completed == plan.steps


def test_apply_stops_at_first_failed_command(tmp_path: Path) -> None:
    plan = plan_harness_upgrade(
        _request(tmp_path),
        version_source=lambda: ("0.8.2", "0.9.0"),
        applied_version_source=lambda _path: "0.8.0",
    )
    commands: list[tuple[str, ...]] = []

    def fail_first(
        command: tuple[str, ...],
        *,
        project_dir: Path,
    ) -> SimpleNamespace:
        assert project_dir == tmp_path.resolve()
        commands.append(command)
        return SimpleNamespace(returncode=17)

    with pytest.raises(HarnessUpgradeStepError) as caught:
        apply_harness_upgrade(plan, runner=fail_first)

    assert caught.value.returncode == 17
    assert caught.value.step == plan.steps[0]
    assert commands == [plan.steps[0].command]


def test_harness_upgrade_application_does_not_import_harness_implementation() -> None:
    source_path = Path(harness_upgrade_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(module.startswith("runops.harness") for module in imported_modules)
