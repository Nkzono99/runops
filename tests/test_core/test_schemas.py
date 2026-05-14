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
    assert "harness" in schema["properties"]
    assert "upstream_feedback" in schema["properties"]["harness"]["properties"]


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


def test_launcher_schema_accepts_current_and_legacy_type_keys() -> None:
    """launchers.toml schema should describe both type and kind inputs."""
    schema = _load_schema("launchers.json")
    launcher_schema = schema["properties"]["launchers"]["additionalProperties"]

    assert {"required": ["type"]} in launcher_schema["anyOf"]
    assert {"required": ["kind"]} in launcher_schema["anyOf"]
    assert "kind" in launcher_schema["properties"]


def test_paper_requests_schema_defines_request_contract() -> None:
    """paper_requests.toml schema should describe paper-facing request rows."""
    schema = _load_schema("paper_requests.json")
    request_schema = schema["properties"]["requests"]["items"]

    assert schema["properties"]["schema_version"]["const"] == 1
    assert "requests" in schema["properties"]
    assert schema["required"] == ["schema_version"]
    assert request_schema["properties"]["type"]["enum"] == [
        "analysis_request",
        "figure_request",
        "experiment_request",
        "evidence_gap",
        "export_request",
    ]
    assert request_schema["properties"]["status"]["enum"] == [
        "open",
        "planned",
        "in_progress",
        "blocked",
        "done",
        "rejected",
    ]
