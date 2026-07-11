"""Tests for typed Story source collection."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomli_w

from runops.application.analysis.story.models import ArtifactEvidence, StorySource
from runops.application.analysis.story.sources import (
    artifact_record,
    collect_source_artifacts,
)
from runops.core.exceptions import SimctlError


def test_artifact_record_normalizes_matching_fields_and_preserves_omissions() -> None:
    record = artifact_record(
        {
            "kind": "figure",
            "path": "figures/surface.png",
            "quantity": "surface_potential",
            "tags": ["surface", 3],
        }
    )

    assert record.kind == "figure"
    assert record.status == "draft"
    assert record.tags == ("surface", "3")
    assert record.present_fields == frozenset({"kind", "path", "quantity"})
    assert ArtifactEvidence("figure:surface", record).to_dict() == {
        "kind": "figure",
        "path": "figures/surface.png",
        "quantity": "surface_potential",
        "selector": "figure:surface",
    }


def test_collect_source_artifacts_reports_missing_source(tmp_path: Path) -> None:
    result = collect_source_artifacts(
        tmp_path,
        StorySource(kind="survey", path="runs/missing"),
    )

    assert result.artifacts == ()
    assert result.warnings == ("Story source not found: runs/missing",)


def test_collect_source_artifacts_rejects_kind_mismatch(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "R20260711-0001"
    run_dir.mkdir(parents=True)
    with open(run_dir / "manifest.toml", "wb") as stream:
        tomli_w.dump({"run": {"id": "R20260711-0001"}}, stream)

    with pytest.raises(SimctlError, match="kind mismatch"):
        collect_source_artifacts(
            tmp_path,
            StorySource(kind="survey", path="runs/R20260711-0001"),
        )


def test_collect_source_artifacts_reads_run_index(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "R20260711-0001"
    index_path = run_dir / "analysis" / "artifacts.toml"
    index_path.parent.mkdir(parents=True)
    with open(run_dir / "manifest.toml", "wb") as stream:
        tomli_w.dump({"run": {"id": "R20260711-0001"}}, stream)
    with open(index_path, "wb") as stream:
        tomli_w.dump(
            {
                "schema_version": 1,
                "scope": "run",
                "generated_by": "test",
                "artifacts": [
                    {
                        "kind": "figure",
                        "path": "figures/surface.png",
                        "status": "main",
                        "quantity": "surface",
                    }
                ],
            },
            stream,
        )

    result = collect_source_artifacts(
        tmp_path,
        StorySource(kind="run", path="runs/R20260711-0001"),
    )

    assert result.warnings == ()
    assert len(result.artifacts) == 1
    assert result.artifacts[0].path == (
        "runs/R20260711-0001/analysis/figures/surface.png"
    )
    assert result.artifacts[0].source_index == (
        "runs/R20260711-0001/analysis/artifacts.toml"
    )
