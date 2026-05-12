"""Tests for MCP registry conformance."""

from __future__ import annotations

from runops.mcp.registry import (
    REQUIRED_RUNOPS_TOOLS,
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
