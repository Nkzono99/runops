"""Tests for runops runs list command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import tomli_w
from typer.testing import CliRunner

from runops.application.execution.readiness import RunReadiness, write_readiness_cache
from runops.cli.main import app

runner = CliRunner()


def _cache_incomplete_readiness(run_dir: Path, run_id: str) -> None:
    write_readiness_cache(
        run_dir,
        RunReadiness(
            run_id=run_id,
            execution_status="completed",
            adapter="fake_sim",
            simulator_status="completed",
            analysis_status="incomplete",
            analysis_ready=False,
            checks=(),
            warnings=("Missing required output.",),
            reason_codes=("missing_required_output:result",),
            recommended_action="review_outputs",
            evaluation_mode="bounded",
        ),
    )


def _create_run(
    parent: Path,
    run_id: str,
    *,
    status: str = "created",
    display_name: str = "",
    tags: list[str] | None = None,
    experiment_id: str = "",
    purpose: str = "",
    review_status: str = "",
    storage_tier: str = "",
    storage_form: str = "",
) -> Path:
    """Create a minimal run directory with manifest.toml."""
    run_dir = parent / run_id
    run_dir.mkdir(parents=True)
    for sub in ("input", "submit", "work", "analysis", "status"):
        (run_dir / sub).mkdir()

    manifest: dict[str, Any] = {
        "run": {
            "id": run_id,
            "display_name": display_name,
            "status": status,
        },
    }
    if tags:
        manifest["classification"] = {"tags": tags}
    if experiment_id or purpose:
        manifest["intent"] = {
            "experiment_id": experiment_id,
            "purpose": purpose,
        }
    if review_status:
        manifest["curation"] = (
            {
                "review_status": "reviewed",
                "reviewed_at": "2026-09-01T00:00:00+00:00",
                "reviewed_by": "human",
                "reason": "checked for list filtering",
            }
            if review_status == "reviewed"
            else {"review_status": review_status}
        )
    if storage_tier or storage_form:
        manifest["storage"] = {
            "tier": storage_tier,
            "form": storage_form,
        }

    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(manifest, f)
    return run_dir


def test_list_no_runs(tmp_path: Path) -> None:
    result = runner.invoke(app, ["runs", "list", str(tmp_path)])
    assert result.exit_code == 0
    assert "No runs found" in result.output


def test_list_discovers_runs(tmp_path: Path) -> None:
    _create_run(tmp_path, "R20260327-0001", status="created", display_name="run_a")
    _create_run(tmp_path, "R20260327-0002", status="completed", display_name="run_b")

    result = runner.invoke(app, ["runs", "list", str(tmp_path)])
    assert result.exit_code == 0
    assert "R20260327-0001" in result.output
    assert "R20260327-0002" in result.output
    assert "run_a" in result.output
    assert "run_b" in result.output


def test_list_hides_archived_and_purged_runs_by_default(tmp_path: Path) -> None:
    _create_run(tmp_path, "R20260327-0001", status="created")
    _create_run(tmp_path, "R20260327-0002", status="archived")
    _create_run(tmp_path, "R20260327-0003", status="purged")

    result = runner.invoke(app, ["runs", "list", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "R20260327-0001" in result.output
    assert "R20260327-0002" not in result.output
    assert "R20260327-0003" not in result.output


def test_list_include_archived_shows_inactive_runs(tmp_path: Path) -> None:
    _create_run(tmp_path, "R20260327-0001", status="created")
    _create_run(tmp_path, "R20260327-0002", status="archived")
    _create_run(tmp_path, "R20260327-0003", status="purged")

    result = runner.invoke(app, ["runs", "list", str(tmp_path), "--include-archived"])

    assert result.exit_code == 0, result.output
    assert "R20260327-0001" in result.output
    assert "R20260327-0002" in result.output
    assert "R20260327-0003" in result.output


def test_list_hides_runs_in_archived_bundle_by_default(tmp_path: Path) -> None:
    bundle = tmp_path / "runs" / "_archive" / "scan"
    _create_run(bundle, "R20260327-0001", status="cancelled")
    (bundle / ".runops-archive.toml").write_text(
        '[bundle]\narchived_from = "/original/scan"\n'
    )

    hidden = runner.invoke(app, ["runs", "list", str(tmp_path / "runs")])
    shown = runner.invoke(
        app,
        ["runs", "list", str(tmp_path / "runs"), "--include-archived"],
    )

    assert hidden.exit_code == 0
    assert "R20260327-0001" not in hidden.output
    assert shown.exit_code == 0
    assert "R20260327-0001" in shown.output


def test_list_explicit_archived_status_does_not_require_include_flag(
    tmp_path: Path,
) -> None:
    _create_run(tmp_path, "R20260327-0001", status="created")
    _create_run(tmp_path, "R20260327-0002", status="archived")

    result = runner.invoke(app, ["runs", "list", str(tmp_path), "--status", "archived"])

    assert result.exit_code == 0, result.output
    assert "R20260327-0001" not in result.output
    assert "R20260327-0002" in result.output


def test_list_failed_filter_does_not_leak_archived_bundle(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    _create_run(runs_dir, "R20260327-0001", status="failed")
    bundle = runs_dir / "_archive" / "old-survey"
    _create_run(bundle, "R20260327-0002", status="failed")
    (bundle / ".runops-archive.toml").write_text(
        '[bundle]\narchived_from = "runs/old-survey"\n', encoding="utf-8"
    )

    result = runner.invoke(
        app,
        ["runs", "list", str(runs_dir), "--status", "failed"],
    )

    assert result.exit_code == 0, result.output
    assert "R20260327-0001" in result.output
    assert "R20260327-0002" not in result.output


def test_list_project_root_is_scoped_to_runs_tree(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "safe-scope"\n', encoding="utf-8"
    )
    _create_run(tmp_path / "runs", "R20260327-0001")
    _create_run(tmp_path / "research" / "results", "R0001-fake-result")

    result = runner.invoke(app, ["runs", "list", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "R20260327-0001" in result.output
    assert "R0001-fake-result" not in result.output


def test_list_fails_when_formal_run_subtree_is_a_symlink(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "unsafe-scope"\n', encoding="utf-8"
    )
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (runs_dir / "hidden").symlink_to(outside, target_is_directory=True)

    result = runner.invoke(app, ["runs", "list", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error discovering runs" in result.output
    assert "symbolic link" in result.output


@pytest.mark.parametrize("scope_kind", ["project", "runs", "survey"])
def test_list_keeps_malformed_formal_run_visible_without_filters(
    tmp_path: Path,
    scope_kind: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "runops.toml").write_text(
        '[project]\nname = "malformed-visible"\n',
        encoding="utf-8",
    )
    survey = project / "runs" / "scan"
    broken = survey / "broken"
    broken.mkdir(parents=True)
    (broken / "manifest.toml").write_text("[run\ninvalid", encoding="utf-8")
    scope = {"project": project, "runs": project / "runs", "survey": survey}[scope_kind]

    unfiltered = runner.invoke(app, ["runs", "list", str(scope)])
    filtered = runner.invoke(
        app,
        ["runs", "list", str(scope), "--status", "created"],
    )

    assert unfiltered.exit_code == 0, unfiltered.output
    assert "???" in unfiltered.output
    assert "unknown" in unfiltered.output
    assert str(broken) in unfiltered.output
    assert filtered.exit_code == 0, filtered.output
    assert "No runs match" in filtered.output
    assert str(broken) not in filtered.output


def test_list_surfaces_cached_readiness_without_deep_evaluation(tmp_path: Path) -> None:
    run_id = "R20260327-0004"
    run_dir = _create_run(tmp_path, run_id, status="completed")
    _cache_incomplete_readiness(run_dir, run_id)

    result = runner.invoke(app, ["runs", "list", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "ANALYSIS" in result.output
    assert "NEXT" in result.output
    assert "incomplete" in result.output
    assert "review_outputs" in result.output


def test_list_filter_by_status(tmp_path: Path) -> None:
    _create_run(tmp_path, "R20260327-0001", status="created")
    _create_run(tmp_path, "R20260327-0002", status="failed")

    result = runner.invoke(app, ["runs", "list", str(tmp_path), "--status", "failed"])
    assert result.exit_code == 0
    assert "R20260327-0002" in result.output
    assert "R20260327-0001" not in result.output


def test_list_filter_by_tag(tmp_path: Path) -> None:
    _create_run(tmp_path, "R20260327-0001", tags=["production"])
    _create_run(tmp_path, "R20260327-0002", tags=["test"])

    result = runner.invoke(
        app,
        ["runs", "list", str(tmp_path), "--tag", "production"],
    )
    assert result.exit_code == 0
    assert "R20260327-0001" in result.output
    assert "R20260327-0002" not in result.output


def test_list_combines_experiment_intent_curation_and_storage_filters(
    tmp_path: Path,
) -> None:
    common = {
        "experiment_id": "E20260901-0001",
        "purpose": "validate",
        "review_status": "reviewed",
        "storage_tier": "cold",
    }
    _create_run(
        tmp_path,
        "R20260327-0001",
        **common,
        storage_form="compacted",
    )
    _create_run(
        tmp_path,
        "R20260327-0002",
        **common,
        storage_form="full",
    )
    _create_run(
        tmp_path,
        "R20260327-0003",
        experiment_id="E20260901-0002",
        purpose="validate",
        review_status="reviewed",
        storage_tier="cold",
        storage_form="compacted",
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "list",
            str(tmp_path),
            "--experiment",
            "E20260901-0001",
            "--purpose",
            "validate",
            "--review-status",
            "reviewed",
            "--storage-tier",
            "cold",
            "--storage-form",
            "compacted",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "R20260327-0001" in result.output
    assert "R20260327-0002" not in result.output
    assert "R20260327-0003" not in result.output


def test_list_treats_incomplete_review_record_as_unreviewed(tmp_path: Path) -> None:
    run_dir = _create_run(tmp_path, "R20260327-0001")
    with (run_dir / "manifest.toml").open("wb") as stream:
        tomli_w.dump(
            {
                "run": {"id": "R20260327-0001", "status": "completed"},
                "curation": {"review_status": "reviewed"},
            },
            stream,
        )

    reviewed = runner.invoke(
        app,
        ["runs", "list", str(tmp_path), "--review-status", "reviewed"],
    )
    unreviewed = runner.invoke(
        app,
        ["runs", "list", str(tmp_path), "--review-status", "unreviewed"],
    )

    assert reviewed.exit_code == 0
    assert "No runs match" in reviewed.output
    assert unreviewed.exit_code == 0
    assert "R20260327-0001" in unreviewed.output


def test_storage_form_filter_includes_inactive_runs(tmp_path: Path) -> None:
    _create_run(
        tmp_path,
        "R20260327-0001",
        status="purged",
        storage_form="metadata_only",
    )

    result = runner.invoke(
        app,
        ["runs", "list", str(tmp_path), "--storage-form", "metadata_only"],
    )

    assert result.exit_code == 0, result.output
    assert "R20260327-0001" in result.output


def test_list_no_match(tmp_path: Path) -> None:
    _create_run(tmp_path, "R20260327-0001", status="created")

    result = runner.invoke(app, ["runs", "list", str(tmp_path), "--status", "failed"])
    assert result.exit_code == 0
    assert "No runs match" in result.output


def test_list_sorted_by_run_id(tmp_path: Path) -> None:
    _create_run(tmp_path, "R20260327-0003")
    _create_run(tmp_path, "R20260327-0001")
    _create_run(tmp_path, "R20260327-0002")

    result = runner.invoke(app, ["runs", "list", str(tmp_path)])
    assert result.exit_code == 0
    lines = result.output.strip().split("\n")
    # Skip header rows (header + separator)
    data_lines = lines[2:]
    assert "R20260327-0001" in data_lines[0]
    assert "R20260327-0002" in data_lines[1]
    assert "R20260327-0003" in data_lines[2]


def test_list_nonexistent_dir() -> None:
    result = runner.invoke(app, ["runs", "list", "/nonexistent/path"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_list_multiple_paths(tmp_path: Path) -> None:
    """Multiple positional path arguments are merged."""
    survey_a = tmp_path / "series_a"
    survey_b = tmp_path / "series_b"
    survey_a.mkdir()
    survey_b.mkdir()
    _create_run(survey_a, "R20260327-0001")
    _create_run(survey_a, "R20260327-0002")
    _create_run(survey_b, "R20260327-0003")

    result = runner.invoke(app, ["runs", "list", str(survey_a), str(survey_b)])
    assert result.exit_code == 0
    assert "R20260327-0001" in result.output
    assert "R20260327-0002" in result.output
    assert "R20260327-0003" in result.output


def test_list_multiple_paths_dedup(tmp_path: Path) -> None:
    """Overlapping paths are deduplicated; runs appear only once."""
    survey = tmp_path / "series_a"
    survey.mkdir()
    _create_run(survey, "R20260327-0001")

    result = runner.invoke(app, ["runs", "list", str(survey), str(survey)])
    assert result.exit_code == 0
    # Count data rows (lines starting with the run id, after the header)
    lines = result.output.strip().split("\n")
    data_lines = [line for line in lines[2:] if line.startswith("R20260327-0001")]
    assert len(data_lines) == 1
