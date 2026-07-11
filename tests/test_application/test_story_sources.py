"""Tests for typed Story source collection."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomli_w

from runops.application.analysis.story.models import ArtifactEvidence, StorySource
from runops.application.analysis.story.sources import (
    artifact_record,
    collect_source_artifacts,
    detect_source_kind,
    display_path,
    resolve_source_path,
    source_from_path,
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


@pytest.mark.parametrize(
    ("tags", "expected"),
    [("surface", ("surface",)), ({"bad": "shape"}, ())],
)
def test_artifact_record_normalizes_alternate_tag_shapes(
    tags: object,
    expected: tuple[str, ...],
) -> None:
    assert artifact_record({"tags": tags}).tags == expected


def test_source_path_helpers_handle_relative_absolute_and_external_paths(
    tmp_path: Path,
) -> None:
    missing = source_from_path(tmp_path, Path("runs/missing"))

    assert missing == StorySource(kind="path", path="runs/missing")
    assert resolve_source_path(tmp_path, "runs/missing") == tmp_path / "runs/missing"
    assert resolve_source_path(tmp_path, "/outside/run") == Path("/outside/run")
    assert display_path(Path("/outside/run"), base=tmp_path) == "/outside/run"


def _write_index(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as stream:
        tomli_w.dump(
            {
                "schema_version": 1,
                "scope": "story-test",
                "generated_by": "test",
                "artifacts": [
                    {
                        "kind": "data",
                        "path": "tables/density.csv",
                        "status": "accepted",
                        "quantity": "density",
                    }
                ],
            },
            stream,
        )


def test_collect_path_source_reads_root_artifact_index(tmp_path: Path) -> None:
    source_dir = tmp_path / "analysis" / "external"
    _write_index(source_dir / "artifacts.toml")

    result = collect_source_artifacts(
        tmp_path,
        StorySource(kind="path", path="analysis/external"),
    )

    assert result.warnings == ()
    assert result.artifacts[0].path == "analysis/external/tables/density.csv"


def test_collect_survey_source_reads_summary_index(tmp_path: Path) -> None:
    survey_dir = tmp_path / "runs" / "scan"
    survey_dir.mkdir(parents=True)
    (survey_dir / "survey.toml").write_text("[survey]\n", encoding="utf-8")
    _write_index(survey_dir / "summary" / "artifacts.toml")

    result = collect_source_artifacts(
        tmp_path,
        StorySource(kind="survey", path="runs/scan"),
    )

    assert result.warnings == ()
    assert result.artifacts[0].source_scope == "runs/scan"


@pytest.mark.parametrize("kind", ["run", "comparison"])
def test_collect_structured_source_warns_when_artifacts_are_absent(
    tmp_path: Path,
    kind: str,
) -> None:
    source_dir = tmp_path / kind
    source_dir.mkdir()
    manifest = (
        {"run": {"id": "R20260711-0002"}}
        if kind == "run"
        else {"comparison": {"id": "comparison"}, "artifacts": {}}
    )
    with open(source_dir / "manifest.toml", "wb") as stream:
        tomli_w.dump(manifest, stream)

    result = collect_source_artifacts(
        tmp_path,
        StorySource(kind=kind, path=kind),  # type: ignore[arg-type]
    )

    assert result.artifacts == ()
    assert result.warnings == (f"No artifact index found for source: {kind}",)


def test_collect_empty_path_source_warns_about_missing_index(tmp_path: Path) -> None:
    source_dir = tmp_path / "empty"
    source_dir.mkdir()

    result = collect_source_artifacts(
        tmp_path,
        StorySource(kind="path", path="empty"),
    )

    assert result.warnings == ("No artifact index found for source: empty",)


def test_detect_source_kind_recognizes_survey_and_plain_path(tmp_path: Path) -> None:
    survey = tmp_path / "survey"
    survey.mkdir()
    (survey / "survey.toml").write_text("[survey]\n", encoding="utf-8")
    plain = tmp_path / "plain"
    plain.mkdir()

    assert detect_source_kind(survey) == "survey"
    assert detect_source_kind(plain) == "path"


def test_collect_source_translates_malformed_manifest(tmp_path: Path) -> None:
    source_dir = tmp_path / "broken"
    source_dir.mkdir()
    (source_dir / "manifest.toml").write_text("[broken", encoding="utf-8")

    with pytest.raises(SimctlError, match="Failed to read TOML"):
        collect_source_artifacts(
            tmp_path,
            StorySource(kind="path", path="broken"),
        )


@pytest.mark.parametrize(
    "artifacts",
    [
        [],
        {"figures": "not-an-array"},
        {"figures": [{}]},
        {"figures": [1]},
    ],
)
def test_collect_comparison_rejects_invalid_artifact_shapes(
    tmp_path: Path,
    artifacts: object,
) -> None:
    comparison = tmp_path / "comparison"
    comparison.mkdir()
    with open(comparison / "manifest.toml", "wb") as stream:
        tomli_w.dump(
            {"comparison": {"id": "comparison"}, "artifacts": artifacts},
            stream,
        )

    with pytest.raises(SimctlError, match="comparison artifacts"):
        collect_source_artifacts(
            tmp_path,
            StorySource(kind="comparison", path="comparison"),
        )
