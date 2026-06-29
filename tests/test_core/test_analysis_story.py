"""Tests for story acceptance audit helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import tomli_w

from runops.core.analysis import audit_story_workspace, create_story_workspace
from runops.core.exceptions import SimctlError


def _write_project_file(project_root: Path) -> None:
    with open(project_root / "runops.toml", "wb") as f:
        tomli_w.dump({"project": {"name": "story-test"}}, f)


def _write_artifacts_index(index_path: Path, artifacts: list[dict[str, Any]]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "wb") as f:
        tomli_w.dump(
            {
                "schema_version": 1,
                "scope": "run",
                "generated_by": "test",
                "artifacts": artifacts,
            },
            f,
        )


def _write_manifest(run_dir: Path, run_id: str) -> None:
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(
            {
                "run": {
                    "id": run_id,
                    "display_name": run_id,
                    "status": "completed",
                },
                "simulator": {"name": "test", "adapter": "generic"},
            },
            f,
        )


def test_create_story_workspace_writes_story_toml(tmp_path: Path) -> None:
    _write_project_file(tmp_path)

    result = create_story_workspace(
        tmp_path,
        "surface adhesion",
        title="Surface adhesion story",
        sources=(tmp_path / "runs" / "scan",),
    )

    assert result.story_id == "surface-adhesion"
    assert result.story_dir == tmp_path / "analysis" / "stories" / "surface-adhesion"
    assert result.story_path == result.story_dir / "story.toml"
    assert result.story_path.is_file()
    story_text = result.story_path.read_text(encoding="utf-8")
    assert 'id = "surface-adhesion"' in story_text
    assert 'title = "Surface adhesion story"' in story_text
    assert 'path = "runs/scan"' in story_text


def test_audit_story_workspace_reports_covered_missing_and_weak_steps(
    tmp_path: Path,
) -> None:
    _write_project_file(tmp_path)
    run_dir = tmp_path / "runs" / "scan" / "R20260629-0001"
    run_dir.mkdir(parents=True)
    _write_manifest(run_dir, "R20260629-0001")
    _write_artifacts_index(
        run_dir / "analysis" / "artifacts.toml",
        [
            {
                "kind": "figure",
                "path": "figures/surface_potential.png",
                "title": "Surface Potential",
                "status": "main",
                "quantity": "surface_potential",
                "run_id": "R20260629-0001",
            },
            {
                "kind": "figure",
                "path": "figures/force_time.png",
                "title": "Force Time",
                "status": "draft",
                "quantity": "force_time",
                "run_id": "R20260629-0001",
            },
        ],
    )
    story_dir = tmp_path / "analysis" / "stories" / "surface-adhesion"
    story_dir.mkdir(parents=True)
    with open(story_dir / "story.toml", "wb") as f:
        tomli_w.dump(
            {
                "schema_version": 1,
                "id": "surface-adhesion",
                "title": "Surface adhesion story",
                "sources": [{"kind": "survey", "path": "runs/scan"}],
                "steps": [
                    {
                        "id": "surface-potential",
                        "title": "Surface-potential visualization",
                        "required_artifacts": ["figure:surface_potential"],
                        "acceptable_status": ["main", "accepted"],
                        "claim_ceiling": "static field evidence",
                    },
                    {
                        "id": "velocity-distribution",
                        "title": "Velocity distribution",
                        "required_artifacts": ["figure:velocity_distribution"],
                        "acceptable_status": ["main", "accepted"],
                    },
                    {
                        "id": "force-time",
                        "title": "Force-time history",
                        "required_artifacts": ["figure:force_time"],
                        "acceptable_status": ["main", "accepted"],
                    },
                ],
            },
            f,
        )

    result = audit_story_workspace(story_dir)

    assert result.overall_status == "partial"
    statuses = {step["id"]: step["status"] for step in result.steps}
    assert statuses == {
        "surface-potential": "covered",
        "velocity-distribution": "missing",
        "force-time": "partial",
    }
    assert (story_dir / "audit.json").is_file()
    assert (story_dir / "audit.md").is_file()
    with open(story_dir / "audit.json", encoding="utf-8") as f:
        audit_json = json.load(f)
    assert audit_json["overall_status"] == "partial"
    assert audit_json["steps"][0]["matched_artifacts"][0]["path"] == (
        "runs/scan/R20260629-0001/analysis/figures/surface_potential.png"
    )
    audit_md = (story_dir / "audit.md").read_text(encoding="utf-8")
    assert "# Story Acceptance Audit: Surface adhesion story" in audit_md
    assert "Velocity distribution" in audit_md
    assert "figure:velocity_distribution" in audit_md


def test_audit_story_workspace_rejects_duplicate_step_ids(tmp_path: Path) -> None:
    _write_project_file(tmp_path)
    story_dir = tmp_path / "analysis" / "stories" / "duplicate"
    story_dir.mkdir(parents=True)
    with open(story_dir / "story.toml", "wb") as f:
        tomli_w.dump(
            {
                "schema_version": 1,
                "id": "duplicate",
                "title": "Duplicate story",
                "steps": [
                    {"id": "same", "title": "One"},
                    {"id": "same", "title": "Two"},
                ],
            },
            f,
        )

    with pytest.raises(SimctlError, match="Duplicate story step id"):
        audit_story_workspace(story_dir)


def test_audit_story_workspace_blocks_when_only_source_is_missing(
    tmp_path: Path,
) -> None:
    _write_project_file(tmp_path)
    story_dir = tmp_path / "analysis" / "stories" / "missing-source"
    story_dir.mkdir(parents=True)
    with open(story_dir / "story.toml", "wb") as f:
        tomli_w.dump(
            {
                "schema_version": 1,
                "id": "missing-source",
                "title": "Missing source story",
                "sources": [{"kind": "survey", "path": "runs/missing"}],
                "steps": [
                    {
                        "id": "surface-potential",
                        "title": "Surface-potential visualization",
                        "required_artifacts": ["figure:surface_potential"],
                    }
                ],
            },
            f,
        )

    result = audit_story_workspace(story_dir)

    assert result.overall_status == "blocked"
    assert result.steps[0]["status"] == "blocked"
    assert result.warnings == ["Story source not found: runs/missing"]
