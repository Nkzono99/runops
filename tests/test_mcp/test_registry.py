"""Tests for MCP registry conformance."""

from __future__ import annotations

from runops.mcp.registry import (
    CODEX_PLUGIN_POLICY,
    REQUIRED_RUNOPS_TOOLS,
    all_tool_specs,
    capabilities_payload,
    conformance_report,
    exposed_tool_specs,
)


def test_registry_conformance_passes() -> None:
    report = conformance_report()
    checks = {check["name"]: check for check in report["checks"]}

    assert report["ok"] is True
    assert all(check["ok"] for check in report["checks"])
    assert checks["cli_action_bindings_conform"]["ok"] is True
    assert checks["mcp_action_bindings_conform"]["ok"] is True


def test_required_runops_tools_are_exposed() -> None:
    exposed = {spec.name for spec in exposed_tool_specs()}

    assert exposed >= REQUIRED_RUNOPS_TOOLS
    assert "runops.job.submit" not in exposed
    assert "runops.run.delete" not in exposed


def test_unsafe_action_tools_remain_disabled_by_default() -> None:
    specs = {spec.name: spec for spec in all_tool_specs()}

    for name in (
        "runops.job.submit",
        "runops.job.cancel",
        "runops.run.delete",
        "runops.experiment.create",
    ):
        spec = specs[name]
        assert spec.enabled is False
        assert spec.exposed is False
        if spec.safety.safety_class in {"external", "destructive"}:
            assert spec.safety.requires_confirmation is True
            assert spec.safety.confirmation_field == "confirm"


def test_capabilities_payload_exposes_codex_plugin_policy() -> None:
    payload = capabilities_payload()
    exposed = {spec.name for spec in exposed_tool_specs()}

    assert payload["codex_plugin_policy"] == CODEX_PLUGIN_POLICY
    assert payload["codex_plugin_policy"]["inventory_schema_version"] == 1
    assert payload["codex_plugin_policy"]["inventory_schema"] == (
        "schemas/codex-plugin-inventory.json"
    )
    assert payload["codex_plugin_policy"]["check_result_schema"] == (
        "schemas/codex-plugin-check-result.json"
    )
    assert CODEX_PLUGIN_POLICY["project_tool"] in exposed
    assert "recommendations" in payload["codex_plugin_policy"]["inventory_fields"]
    assert "$schema" in payload["codex_plugin_policy"]["inventory_fields"]
    assert "strict_ok" in payload["codex_plugin_policy"]["check_result_fields"]
    assert "$schema" in payload["codex_plugin_policy"]["check_result_fields"]
    assert "sources" in payload["codex_plugin_policy"]["recommendation_fields"]
    assert (
        payload["codex_plugin_policy"]["delegated_capabilities_field"]
        == "delegated_capabilities"
    )


def test_capabilities_payload_exposes_only_nonempty_action_bindings() -> None:
    tools = {tool["name"]: tool for tool in capabilities_payload()["tools"]}

    assert tools["runops.job.submit"]["action_name"] == "submit_run"
    assert tools["runops.run.logs"]["action_name"] == "show_log"
    assert "action_name" not in tools["runops.health"]
