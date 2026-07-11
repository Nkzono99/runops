"""Tests for project-state migrations."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.application.operator.migrations import (
    get_migration,
    normalize_number,
    normalize_version,
    parse_migration_reference,
    run_migration,
)


def test_migration_normalization_accepts_common_forms() -> None:
    assert normalize_version("v0") == "v0"
    assert normalize_version("0.7.0") == "v0"
    assert normalize_number("1", version="v0") == "0001"
    assert normalize_number("M0-0001", version="v0") == "0001"
    assert get_migration("0.7.0", "1").migration_id == "M0-0001"
    assert parse_migration_reference("M0-0001") == ("v0", "0001")
    assert parse_migration_reference("0.7.0", "1") == ("v0", "0001")


def test_analysis_artifact_migration_creates_indexes(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "angle_scan" / "R20260508-0001"
    analysis_dir = run_dir / "analysis"
    figure_path = analysis_dir / "figures" / "density.png"
    figure_path.parent.mkdir(parents=True)
    figure_path.write_bytes(b"png")
    (run_dir / "manifest.toml").write_text(
        """
[run]
id = "R20260508-0001"
display_name = "angle=10"
status = "completed"
""".lstrip(),
        encoding="utf-8",
    )
    (analysis_dir / "summary.json").write_text(
        json.dumps(
            {
                "density_peak": 1.25,
                "figures": [
                    {
                        "path": "figures/density.png",
                        "caption": "Density slice",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    summary_dir = tmp_path / "runs" / "angle_scan" / "summary"
    summary_dir.mkdir()
    (summary_dir / "survey_summary.csv").write_text(
        "run_id,density_peak\n", encoding="utf-8"
    )
    (summary_dir / "survey_summary.json").write_text("{}\n", encoding="utf-8")

    result = run_migration("v0", "0001", project_root=tmp_path)

    assert result.status == "applied"
    assert (
        Path("runs/angle_scan/R20260508-0001/analysis/artifacts.toml") in result.created
    )
    assert Path("runs/angle_scan/summary/artifacts.toml") in result.created

    with open(analysis_dir / "artifacts.toml", "rb") as f:
        run_index = tomllib.load(f)
    assert run_index["scope"] == "run"
    assert run_index["artifacts"][0]["path"] == "figures/density.png"

    with open(summary_dir / "artifacts.toml", "rb") as f:
        survey_index = tomllib.load(f)
    assert survey_index["scope"] == "survey"
    assert survey_index["artifacts"][0]["path"] == "survey_summary.csv"


def test_analysis_artifact_migration_dry_run_does_not_write(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "R20260508-0001"
    analysis_dir = run_dir / "analysis"
    analysis_dir.mkdir(parents=True)
    (run_dir / "manifest.toml").write_text(
        """
[run]
id = "R20260508-0001"
status = "completed"
""".lstrip(),
        encoding="utf-8",
    )
    (analysis_dir / "summary.json").write_text("{}\n", encoding="utf-8")

    result = run_migration("v0", "0001", project_root=tmp_path, dry_run=True)

    assert result.status == "planned"
    assert Path("runs/R20260508-0001/analysis/artifacts.toml") in result.planned
    assert not (analysis_dir / "artifacts.toml").exists()


def test_research_scaffold_migration_backfills_missing_files(tmp_path: Path) -> None:
    result = run_migration("0.7.0", "M0-0002", project_root=tmp_path)

    assert result.status == "applied"
    assert (tmp_path / "research" / "README.md").is_file()
    assert (tmp_path / "research" / "agenda.md").is_file()
    assert (tmp_path / "research" / "proposals" / ".gitkeep").is_file()
    assert (tmp_path / "research" / "reviews" / ".gitkeep").is_file()


def test_research_scaffold_migration_does_not_overwrite_agenda(tmp_path: Path) -> None:
    agenda_path = tmp_path / "research" / "agenda.md"
    agenda_path.parent.mkdir()
    agenda_path.write_text("# Custom Agenda\n", encoding="utf-8")

    run_migration("v0", "0002", project_root=tmp_path)

    assert agenda_path.read_text(encoding="utf-8") == "# Custom Agenda\n"


def test_remove_legacy_figure_index_migration_deletes_json_and_updates_artifacts(
    tmp_path: Path,
) -> None:
    summary_dir = tmp_path / "runs" / "angle_scan" / "summary"
    summary_dir.mkdir(parents=True)
    (summary_dir / "figures_index.json").write_text(
        '{"figures": []}\n',
        encoding="utf-8",
    )
    (summary_dir / "artifacts.toml").write_text(
        """
schema_version = 1
scope = "survey"
generated_by = "test"

[[artifacts]]
kind = "table"
path = "survey_summary.csv"
title = "Survey summary CSV"

[[artifacts]]
kind = "data"
path = "figures_index.json"
title = "Legacy figure index"
""".lstrip(),
        encoding="utf-8",
    )

    result = run_migration("v0", "0003", project_root=tmp_path)

    assert result.status == "applied"
    assert Path("runs/angle_scan/summary/figures_index.json") in result.deleted
    assert Path("runs/angle_scan/summary/artifacts.toml") in result.updated
    assert not (summary_dir / "figures_index.json").exists()

    with open(summary_dir / "artifacts.toml", "rb") as f:
        artifact_index = tomllib.load(f)
    paths = [item["path"] for item in artifact_index["artifacts"]]
    assert paths == ["survey_summary.csv"]


def test_experiment_v2_migration_preserves_unknown_fields_and_blocks_missing_science(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "research" / "experiments.toml"
    ledger.parent.mkdir()
    with open(ledger, "wb") as stream:
        tomli_w.dump(
            {
                "schema_version": 1,
                "experiments": [
                    {
                        "id": "E1",
                        "decision": "WAIT",
                        "proposal": "research/proposals/E1.md",
                        "review": "",
                        "selected_candidate": "C1",
                        "private_note": "keep",
                        "candidates": [
                            {
                                "id": "C1",
                                "information_gain": "gain",
                                "falsification": "criterion",
                                "estimated_core_hours": 1.0,
                                "operational_risk": "low",
                            },
                            {
                                "id": "C2",
                                "information_gain": "other",
                                "falsification": "other criterion",
                                "estimated_core_hours": 2.0,
                                "operational_risk": "medium",
                            },
                        ],
                    }
                ],
            },
            stream,
        )

    result = run_migration("v0", "0004", project_root=tmp_path, yes=True)

    with open(ledger, "rb") as stream:
        raw = tomllib.load(stream)
    assert result.status == "applied"
    assert raw["schema_version"] == 2
    assert raw["experiments"][0]["private_note"] == "keep"
    assert set(raw["experiments"][0]["migration_blockers"]) == {
        "title",
        "question",
        "cost_ceiling_core_hours",
    }


def test_experiment_v2_migration_is_dry_run_and_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / "research" / "experiments.toml"
    ledger.parent.mkdir()
    ledger.write_text("schema_version = 1\n", encoding="utf-8")

    planned = run_migration("v0", "0004", project_root=tmp_path, dry_run=True)
    assert planned.status == "planned"
    assert planned.planned == (Path("research/experiments.toml"),)
    assert ledger.read_text(encoding="utf-8") == "schema_version = 1\n"

    applied = run_migration("v0", "0004", project_root=tmp_path, yes=True)
    repeated = run_migration("v0", "0004", project_root=tmp_path, yes=True)
    assert applied.status == "applied"
    assert repeated.status == "skipped"
