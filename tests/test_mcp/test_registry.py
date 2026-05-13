"""Tests for MCP registry conformance."""

from __future__ import annotations

from runops.mcp.registry import (
    REQUIRED_RUNOPS_TOOLS,
    all_tool_specs,
    conformance_report,
    exposed_tool_specs,
)


def test_registry_conformance_passes() -> None:
    report = conformance_report()

    assert report["ok"] is True
    assert all(check["ok"] for check in report["checks"])


def test_required_runops_tools_are_exposed() -> None:
    exposed = {spec.name for spec in exposed_tool_specs()}

    assert exposed >= REQUIRED_RUNOPS_TOOLS
    assert "runops.job.submit" not in exposed
    assert "runops.run.delete" not in exposed


def test_unsafe_action_tools_remain_disabled_by_default() -> None:
    specs = {spec.name: spec for spec in all_tool_specs()}

    for name in ("runops.job.submit", "runops.job.cancel", "runops.run.delete"):
        spec = specs[name]
        assert spec.enabled is False
        assert spec.exposed is False
        assert spec.safety.requires_confirmation is True
        assert spec.safety.confirmation_field == "confirm"
