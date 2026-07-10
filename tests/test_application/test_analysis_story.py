"""Tests for story acceptance audit helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.application.analysis import audit_story_workspace, create_story_workspace
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
        name="surface adhesion",
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
                    {
                        "id": "same",
                        "title": "One",
                        "required_artifacts": ["figure:one"],
                        "acceptable_status": ["main"],
                    },
                    {
                        "id": "same",
                        "title": "Two",
                        "required_artifacts": ["figure:two"],
                        "acceptable_status": ["main"],
                    },
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
                        "acceptable_status": ["main", "accepted"],
                    }
                ],
            },
            f,
        )

    result = audit_story_workspace(story_dir)

    assert result.overall_status == "blocked"
    assert result.steps[0]["status"] == "blocked"
    assert result.warnings == ["Story source not found: runs/missing"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_artifacts", []),
        ("required_artifacts", "figure:surface_potential"),
        ("required_artifacts", [1]),
        ("acceptable_status", []),
        ("acceptable_status", "main"),
        ("acceptable_status", [1]),
    ],
)
def test_audit_story_workspace_rejects_invalid_step_arrays_without_outputs(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    _write_project_file(tmp_path)
    story_dir = tmp_path / "analysis" / "stories" / "invalid-schema"
    story_dir.mkdir(parents=True)
    step: dict[str, Any] = {
        "id": "surface-potential",
        "title": "Surface potential",
        "required_artifacts": ["figure:surface_potential"],
        "acceptable_status": ["main"],
    }
    step[field] = value
    with open(story_dir / "story.toml", "wb") as f:
        tomli_w.dump(
            {
                "schema_version": 1,
                "id": "invalid-schema",
                "title": "Invalid schema",
                "steps": [step],
            },
            f,
        )

    with pytest.raises(SimctlError, match=field):
        audit_story_workspace(story_dir)

    assert not (story_dir / "audit.json").exists()
    assert not (story_dir / "audit.md").exists()


def test_audit_story_workspace_blocks_all_steps_when_any_source_is_missing(
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
                "path": "figures/surface.png",
                "title": "Surface Potential",
                "status": "main",
                "quantity": "surface_potential",
            }
        ],
    )
    story_dir = tmp_path / "analysis" / "stories" / "mixed-sources"
    story_dir.mkdir(parents=True)
    with open(story_dir / "story.toml", "wb") as f:
        tomli_w.dump(
            {
                "schema_version": 1,
                "id": "mixed-sources",
                "title": "Mixed sources",
                "sources": [
                    {"kind": "survey", "path": "runs/scan"},
                    {"kind": "survey", "path": "runs/missing"},
                ],
                "steps": [
                    {
                        "id": "surface",
                        "title": "Surface",
                        "required_artifacts": ["figure:surface_potential"],
                        "acceptable_status": ["main"],
                    }
                ],
            },
            f,
        )

    result = audit_story_workspace(story_dir)

    assert result.overall_status == "blocked"
    assert result.steps[0]["status"] == "blocked"


@pytest.mark.parametrize("kind", ["unknown", "RUN"])
def test_audit_story_workspace_rejects_unknown_source_kind(
    tmp_path: Path,
    kind: str,
) -> None:
    _write_project_file(tmp_path)
    story_dir = tmp_path / "analysis" / "stories" / "bad-kind"
    story_dir.mkdir(parents=True)
    with open(story_dir / "story.toml", "wb") as f:
        tomli_w.dump(
            {
                "schema_version": 1,
                "id": "bad-kind",
                "title": "Bad kind",
                "sources": [{"kind": kind, "path": "runs/scan"}],
                "steps": [
                    {
                        "id": "surface",
                        "required_artifacts": ["figure:surface"],
                        "acceptable_status": ["main"],
                    }
                ],
            },
            f,
        )

    with pytest.raises(SimctlError, match="kind"):
        audit_story_workspace(story_dir)


def test_audit_story_workspace_rejects_source_kind_mismatch(tmp_path: Path) -> None:
    _write_project_file(tmp_path)
    run_dir = tmp_path / "runs" / "R20260629-0001"
    run_dir.mkdir(parents=True)
    _write_manifest(run_dir, "R20260629-0001")
    story_dir = tmp_path / "analysis" / "stories" / "mismatch"
    story_dir.mkdir(parents=True)
    with open(story_dir / "story.toml", "wb") as f:
        tomli_w.dump(
            {
                "schema_version": 1,
                "id": "mismatch",
                "title": "Mismatch",
                "sources": [{"kind": "survey", "path": "runs/R20260629-0001"}],
                "steps": [
                    {
                        "id": "surface",
                        "required_artifacts": ["figure:surface"],
                        "acceptable_status": ["main"],
                    }
                ],
            },
            f,
        )

    with pytest.raises(SimctlError, match="kind mismatch"):
        audit_story_workspace(story_dir)

    assert not (story_dir / "audit.json").exists()


def test_create_story_workspace_resolves_relative_sources_from_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_project_file(tmp_path)
    run_dir = tmp_path / "runs" / "R20260629-0001"
    run_dir.mkdir(parents=True)
    _write_manifest(run_dir, "R20260629-0001")
    elsewhere = tmp_path / "nested" / "cwd"
    elsewhere.mkdir(parents=True)
    monkeypatch.chdir(elsewhere)

    result = create_story_workspace(
        tmp_path,
        name="Root relative",
        sources=(Path("runs/R20260629-0001"),),
    )

    with open(result.story_path, "rb") as f:
        story = tomllib.load(f)
    assert story["sources"] == [{"kind": "run", "path": "runs/R20260629-0001"}]


def test_create_story_workspace_preserves_explicit_id(tmp_path: Path) -> None:
    _write_project_file(tmp_path)

    result = create_story_workspace(
        tmp_path,
        name="Human name",
        story_id="foo_bar",
    )

    assert result.story_id == "foo_bar"
    assert result.title == "Human name"


def test_create_story_workspace_rejects_whitespace_around_explicit_id(
    tmp_path: Path,
) -> None:
    _write_project_file(tmp_path)

    with pytest.raises(SimctlError, match="whitespace"):
        create_story_workspace(
            tmp_path,
            name="Human name",
            story_id=" foo ",
        )


def test_audit_story_workspace_rejects_boolean_schema_version(tmp_path: Path) -> None:
    _write_project_file(tmp_path)
    story_dir = tmp_path / "analysis" / "stories" / "boolean-version"
    story_dir.mkdir(parents=True)
    with open(story_dir / "story.toml", "wb") as f:
        tomli_w.dump(
            {
                "schema_version": True,
                "id": "boolean-version",
                "title": "Boolean version",
                "steps": [
                    {
                        "id": "surface",
                        "required_artifacts": ["figure:surface"],
                        "acceptable_status": ["main"],
                    }
                ],
            },
            f,
        )

    with pytest.raises(SimctlError, match="schema_version"):
        audit_story_workspace(story_dir)

    assert not (story_dir / "audit.json").exists()


def test_create_story_workspace_generates_stable_id_for_japanese_name(
    tmp_path: Path,
) -> None:
    _write_project_file(tmp_path)

    first = create_story_workspace(tmp_path, name="表面電位の物語")
    first_id = first.story_id
    for path in first.story_dir.iterdir():
        path.unlink()
    first.story_dir.rmdir()
    second = create_story_workspace(tmp_path, name="表面電位の物語")

    assert first_id.startswith("story-")
    assert second.story_id == first_id
    assert second.title == "表面電位の物語"


def test_audit_story_workspace_accepts_comparison_source(tmp_path: Path) -> None:
    _write_project_file(tmp_path)
    comparison_dir = tmp_path / "analysis" / "cross_run" / "comparison-a"
    comparison_dir.mkdir(parents=True)
    with open(comparison_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(
            {
                "comparison": {"id": "comparison-a", "name": "Comparison A"},
                "artifacts": {"figures": ["figures/result.png"]},
            },
            f,
        )
    story_dir = tmp_path / "analysis" / "stories" / "comparison-story"
    story_dir.mkdir(parents=True)
    with open(story_dir / "story.toml", "wb") as f:
        tomli_w.dump(
            {
                "schema_version": 1,
                "id": "comparison-story",
                "title": "Comparison story",
                "sources": [
                    {"kind": "comparison", "path": "analysis/cross_run/comparison-a"}
                ],
                "steps": [
                    {
                        "id": "result",
                        "required_artifacts": ["figure:result"],
                        "acceptable_status": ["draft"],
                    }
                ],
            },
            f,
        )

    result = audit_story_workspace(story_dir)

    assert result.overall_status == "covered"
