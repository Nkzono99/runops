"""Tests for bundled TOML JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_schema(name: str) -> dict[str, Any]:
    path = _REPO_ROOT / "schemas" / name
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)
    return data


def test_runops_schema_is_the_project_schema() -> None:
    """runops.toml schema includes current project and harness sections."""
    schema = _load_schema("runops.json")

    assert schema["title"] == "runops.toml"
    assert "project" in schema["properties"]
    project_props = schema["properties"]["project"]["properties"]
    assert "codex_plugins" in project_props
    plugin_schema = project_props["codex_plugins"]["additionalProperties"]
    assert plugin_schema["$ref"] == "codex-plugin-recommendation.json"
    assert "research" in schema["properties"]
    workspace = schema["properties"]["research"]["properties"]["workspace"]
    assert workspace["properties"]["current_chars"]["default"] == 20000
    assert workspace["properties"]["current_lines"]["default"] == 50
    assert workspace["properties"]["current_path_references"]["default"] == 10
    assert workspace["properties"]["current_chronological_headings"]["default"] == 3
    assert workspace["properties"]["active_results"]["default"] == 8


def test_codex_plugin_recommendation_schema_defines_shared_contract() -> None:
    """Plugin recommendation metadata is defined once for all TOML schemas."""
    schema = _load_schema("codex-plugin-recommendation.json")

    assert schema["title"] == "Codex plugin recommendation"
    assert schema["required"] == ["display_name", "reason", "install_hint"]
    assert "capabilities" in schema["properties"]


def test_codex_plugin_inventory_schema_defines_json_output_contract() -> None:
    """Plugin inventory JSON output has a schema for external clients."""
    schema = _load_schema("codex-plugin-inventory.json")
    recommendation = schema["definitions"]["recommendation"]

    assert schema["title"] == "Codex plugin inventory"
    assert "$schema" in schema["required"]
    assert schema["properties"]["$schema"]["const"] == (
        "schemas/codex-plugin-inventory.json"
    )
    assert schema["properties"]["schema_version"]["const"] == 1
    assert "delegated_capabilities" in schema["required"]
    assert "sources" in recommendation["required"]
    assert "capabilities" in recommendation["required"]


def test_codex_plugin_check_result_schema_wraps_inventory_contract() -> None:
    """Plugin check JSON output references the inventory schema."""
    schema = _load_schema("codex-plugin-check-result.json")

    assert schema["title"] == "Codex plugin check result"
    assert "$schema" in schema["required"]
    assert schema["properties"]["$schema"]["const"] == (
        "schemas/codex-plugin-check-result.json"
    )
    assert schema["properties"]["schema_version"]["const"] == 1
    assert schema["properties"]["inventory"]["$ref"] == ("codex-plugin-inventory.json")
    assert schema["properties"]["issues"]["items"]["$ref"] == (
        "codex-plugin-inventory.json#/definitions/issue"
    )


def test_simulators_schema_includes_plugin_recommendation_metadata() -> None:
    """simulators.toml schema exposes simulator-scoped plugin metadata."""
    schema = _load_schema("simulators.json")
    simulator_schema = schema["properties"]["simulators"]["additionalProperties"]
    plugin_schema = simulator_schema["properties"]["codex_plugins"][
        "additionalProperties"
    ]

    assert plugin_schema["$ref"] == "codex-plugin-recommendation.json"


def test_site_schema_includes_plugin_recommendation_metadata() -> None:
    """site.toml schema exposes site-scoped plugin metadata."""
    schema = _load_schema("site.json")
    site_props = schema["properties"]["site"]["properties"]
    plugin_schema = site_props["codex_plugins"]["additionalProperties"]

    assert schema["title"] == "site.toml"
    assert "simulators" in site_props
    assert plugin_schema["$ref"] == "codex-plugin-recommendation.json"


def test_case_schema_matches_current_case_sections() -> None:
    """case.toml schema should describe [case], [classification], [job], params."""
    schema = _load_schema("case.json")

    assert schema["properties"]["case"]["required"] == [
        "name",
        "simulator",
        "launcher",
    ]
    assert "job" in schema["properties"]
    job_props = schema["properties"]["job"]["properties"]
    for key in ("walltime", "processes", "threads", "cores", "modules"):
        assert key in job_props
    assert "slurm" not in schema["properties"]


def test_survey_schema_matches_current_required_fields_and_job_overlay() -> None:
    """survey.toml schema should match load_survey and partial job overlays."""
    schema = _load_schema("survey.json")

    assert schema["properties"]["survey"]["required"] == [
        "base_case",
        "simulator",
        "launcher",
    ]
    job_props = schema["properties"]["job"]["properties"]
    for key in ("walltime", "processes", "threads", "cores", "pre_commands"):
        assert key in job_props
    assert "threads_per_process" not in job_props


def test_manifest_schema_matches_manifest_data_sections() -> None:
    """manifest.toml schema should use the sections emitted by ManifestData."""
    schema = _load_schema("manifest.json")
    props = schema["properties"]

    assert schema["required"] == [
        "run",
        "origin",
        "simulator",
        "launcher",
        "simulator_source",
        "job",
        "params_snapshot",
    ]
    assert schema["additionalProperties"] is True

    for section in (
        "run",
        "path",
        "origin",
        "classification",
        "simulator",
        "launcher",
        "simulator_source",
        "job",
        "variation",
        "params_snapshot",
        "files",
    ):
        assert section in props
    assert "slurm" not in props
    assert "provenance" not in props
    assert "params" not in props
    assert props["origin"]["required"] == ["case"]
    assert props["simulator"]["required"] == ["name"]
    assert props["launcher"]["required"] == ["name"]
    assert props["job"]["required"] == ["scheduler", "job_id", "submitted_at"]


def test_launcher_schema_accepts_current_and_legacy_type_keys() -> None:
    """launchers.toml schema should describe both type and kind inputs."""
    schema = _load_schema("launchers.json")
    launcher_schema = schema["properties"]["launchers"]["additionalProperties"]

    assert {"required": ["type"]} in launcher_schema["anyOf"]
    assert {"required": ["kind"]} in launcher_schema["anyOf"]
    assert "kind" in launcher_schema["properties"]
