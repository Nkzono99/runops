"""Tests for cross-run comparison workspace scaffolding."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import tomli_w

from runops.application.analysis import (
    create_comparison_workspace,
    slugify_comparison_id,
)
from runops.core.exceptions import SimctlError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def _write_manifest(run_dir: Path, run_id: str) -> None:
    run_dir.mkdir(parents=True)
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(
            {
                "run": {
                    "id": run_id,
                    "status": "completed",
                },
                "simulator": {
                    "name": "generic",
                    "adapter": "generic",
                },
            },
            f,
        )


def test_slugify_comparison_id() -> None:
    assert slugify_comparison_id("Landau Model / no_plate") == "landau-model-no-plate"


def test_create_comparison_workspace_records_sources(tmp_path: Path) -> None:
    project = tmp_path
    survey_dir = project / "runs" / "survey-a"
    (survey_dir / "survey.toml").parent.mkdir(parents=True)
    (survey_dir / "survey.toml").write_text("[survey]\nname = 'A'\n", encoding="utf-8")
    _write_manifest(survey_dir / "R20260501-0001", "R20260501-0001")

    result = create_comparison_workspace(
        project,
        name="Landau comparison",
        comparison_id="landau-a",
        sources=(survey_dir,),
    )

    assert result.comparison_id == "landau-a"
    assert result.source_count == 1
    assert result.comparison_dir.name == "R0001-landau-a"
    assert (result.comparison_dir / "artifacts/scripts").is_dir()
    assert (result.comparison_dir / "artifacts/data").is_dir()
    assert (result.comparison_dir / "artifacts/figures").is_dir()
    with open(result.manifest_path, "rb") as f:
        manifest = tomllib.load(f)

    assert manifest["comparison"]["id"] == "landau-a"
    assert manifest["comparison"]["name"] == "Landau comparison"
    assert manifest["sources"][0]["kind"] == "survey"
    assert manifest["sources"][0]["path"] == "runs/survey-a"
    assert manifest["sources"][0]["run_ids"] == ["R20260501-0001"]
    assert manifest["paths"] == {
        "scripts": "artifacts/scripts",
        "data": "artifacts/data",
        "figures": "artifacts/figures",
    }


def test_create_comparison_workspace_rejects_duplicate(tmp_path: Path) -> None:
    create_comparison_workspace(tmp_path, name="Comparison", comparison_id="same")

    with pytest.raises(SimctlError, match="already exists"):
        create_comparison_workspace(tmp_path, name="Comparison", comparison_id="same")


def test_create_comparison_workspace_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(SimctlError, match="source not found"):
        create_comparison_workspace(
            tmp_path,
            name="Comparison",
            sources=(tmp_path / "missing",),
        )
