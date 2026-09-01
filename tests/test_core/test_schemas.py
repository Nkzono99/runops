"""Tests for bundled TOML JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

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
    policy = schema["properties"]["experiments"]["properties"]["policy"]
    assert policy["properties"]["require_experiment"]["default"] is False
    assert policy["properties"]["max_active_experiments"]["default"] == 5


def test_experiment_schema_matches_execution_kernel_contract() -> None:
    schema = _load_schema("experiment.json")

    assert schema["title"] == "experiment.toml"
    assert schema["required"] == [
        "schema_version",
        "experiment",
        "baseline",
        "budget",
        "exit",
    ]
    experiment = schema["properties"]["experiment"]
    assert experiment["properties"]["lifecycle"]["enum"] == [
        "draft",
        "active",
        "closed",
    ]
    assert "smoke" not in experiment["properties"]["intent"]["enum"]
    budget = schema["properties"]["budget"]
    assert "expires_at" in budget["required"]
    assert budget["properties"]["expires_at"] == {
        "type": "string",
        "format": "date-time",
    }


def test_sealed_result_schema_requires_included_evidence() -> None:
    schema = _load_schema("result.json")

    sealed = schema["allOf"][0]["then"]["properties"]["evidence"]
    assert sealed["minItems"] == 1
    assert sealed["contains"]["properties"]["disposition"]["const"] == "include"
    payload = {
        "result": {
            "schema_version": 1,
            "id": "R0001-example",
            "status": "sealed",
            "title": "Example",
            "claim": "A bounded claim.",
            "outcome": "supported",
        },
        "evidence": [
            {
                "kind": "run",
                "run_id": "R20260901-0001",
                "disposition": "exclude",
                "role": "comparison",
                "reason": "Not selected.",
                "source_path": "runs/R20260901-0001",
                "receipt_kind": "run-scientific-snapshot-v1",
                "sha256": "a" * 64,
                "bytes": 1,
            }
        ],
        "seal": {
            "sealed_at": "2026-09-01T00:00:00+00:00",
            "content_sha256": "b" * 64,
            "readme_sha256": "c" * 64,
            "readme_bytes": 1,
        },
    }
    validator = Draft7Validator(schema)

    assert not validator.is_valid(payload)
    payload["evidence"][0]["disposition"] = "include"
    assert validator.is_valid(payload)


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
    survey_props = schema["properties"]["survey"]["properties"]
    assert survey_props["phase"]["enum"] == ["pilot", "main", "followup"]
    assert schema["properties"]["intent"]["properties"]["purpose"]["enum"] == [
        "explore",
        "confirm",
        "validate",
        "reproduce",
    ]


def test_formal_run_schemas_share_strict_positive_walltime_contract() -> None:
    for schema_name in ("case.json", "survey.json", "manifest.json"):
        schema = _load_schema(schema_name)
        walltime = schema["properties"]["job"]["properties"]["walltime"]
        validator = Draft7Validator(walltime)

        for valid in ("0:00:01", "120:00:00", "5-00:00:00"):
            assert validator.is_valid(valid), (schema_name, valid)
        for invalid in (
            "",
            "00:00:00",
            "0-00:00:00",
            "-01:00:00",
            "01:60:00",
            "01:00:60",
        ):
            assert not validator.is_valid(invalid), (schema_name, invalid)


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
        "intent",
        "identity",
        "curation",
        "storage",
    ):
        assert section in props
    assert "slurm" not in props
    assert "provenance" not in props
    assert "params" not in props
    assert props["origin"]["required"] == ["case"]
    assert props["simulator"]["required"] == ["name"]
    assert props["launcher"]["required"] == ["name"]
    assert props["job"]["required"] == ["scheduler", "job_id", "submitted_at"]
    assert props["storage"]["properties"]["tier"]["enum"] == ["hot", "cold"]
    assert props["storage"]["properties"]["form"]["enum"] == [
        "full",
        "compacted",
        "metadata_only",
    ]
    assert props["storage"]["properties"]["protected_by_results"]["uniqueItems"]
    canonical_hash = "^sha256:[0-9a-f]{64}$"
    for key in (
        "point_id",
        "condition_hash",
        "input_hash",
        "scientific_hash",
        "execution_hash",
        "provenance_hash",
        "plan_hash",
    ):
        assert props["identity"]["properties"][key]["pattern"] == canonical_hash
    for key in ("exe_hash", "executable_hash"):
        assert props["simulator_source"]["properties"][key]["pattern"] == (
            "^(|sha256:[0-9a-f]{64})$"
        )
    assert props["simulator_source"]["properties"]["git_state_observed"] == {
        "type": "boolean"
    }
    curation = props["curation"]
    assert "reviewed_by" in curation["properties"]
    reviewed_rule = curation["allOf"][0]
    assert reviewed_rule["if"]["properties"]["review_status"] == {"const": "reviewed"}
    assert reviewed_rule["then"]["required"] == [
        "reviewed_at",
        "reviewed_by",
        "reason",
    ]


def test_manifest_schema_rejects_incomplete_reviewed_record() -> None:
    schema = _load_schema("manifest.json")
    payload = {
        "run": {"id": "R20260901-0001", "status": "completed"},
        "origin": {"case": "base"},
        "simulator": {"name": "generic"},
        "launcher": {"name": "srun"},
        "simulator_source": {},
        "job": {"scheduler": "slurm", "job_id": "1", "submitted_at": "now"},
        "params_snapshot": {},
        "curation": {"review_status": "reviewed"},
    }

    errors = list(Draft7Validator(schema).iter_errors(payload))

    assert {error.validator for error in errors} == {"required"}


def test_launcher_schema_accepts_current_and_legacy_type_keys() -> None:
    """launchers.toml schema should describe both type and kind inputs."""
    schema = _load_schema("launchers.json")
    launcher_schema = schema["properties"]["launchers"]["additionalProperties"]

    assert {"required": ["type"]} in launcher_schema["anyOf"]
    assert {"required": ["kind"]} in launcher_schema["anyOf"]
    assert "kind" in launcher_schema["properties"]
