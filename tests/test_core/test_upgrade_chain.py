"""Tests for versioned runops upgrade planning."""

from __future__ import annotations

import pytest

from runops.core.upgrade_chain import (
    UpgradePlanError,
    build_upgrade_plan,
    latest_version_in_versions,
)


def test_build_upgrade_plan_uses_minor_checkpoints() -> None:
    """Plans step through the latest known version in each release line."""
    plan = build_upgrade_plan(
        applied_version="0.9.1",
        current_runtime_version="0.12.3",
        target_version="0.12.3",
        available_versions=[
            "0.9.2",
            "0.10.1",
            "0.10.4",
            "0.11.2",
            "0.12.1",
            "0.12.3",
        ],
    )

    assert [(step.from_version, step.to_version) for step in plan.steps] == [
        ("0.9.1", "0.9.2"),
        ("0.9.2", "0.10.4"),
        ("0.10.4", "0.11.2"),
        ("0.11.2", "0.12.3"),
    ]


def test_build_upgrade_plan_rejects_major_without_flag() -> None:
    """Major upgrades require explicit opt-in."""
    with pytest.raises(UpgradePlanError, match="--allow-major"):
        build_upgrade_plan(
            applied_version="0.9.1",
            current_runtime_version="1.0.0",
            target_version="1.0.0",
        )


def test_latest_version_in_versions_ignores_prereleases() -> None:
    """latest resolution uses stable PEP 440 releases only."""
    assert latest_version_in_versions(["0.9.0", "1.0.0rc1", "0.10.0"]) == "0.10.0"
