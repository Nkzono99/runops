"""CLI tests for the read-only ``runo triage`` report."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from runops.application.triage import (
    ActiveExperimentTriage,
    TriageDiagnostic,
    TriageReport,
)
from runops.cli.main import app

runner = CliRunner()


def _report(root: Path) -> TriageReport:
    return TriageReport(
        project_root=root,
        generated_at="2026-09-01T12:00:00+00:00",
        test_attempt_age_days=14,
        active_experiments=(
            ActiveExperimentTriage(
                experiment_id="E20260901-0001",
                title="Question",
                decision="pending",
                expires_at="2099-01-01T00:00:00+00:00",
                expired=False,
                run_count=2,
                run_status_counts={"completed": 1, "running": 1},
            ),
        ),
        active_experiment_count=1,
        pending_decision_count=1,
        active_formal_run_count=2,
        run_status_counts={"completed": 1, "running": 1},
        run_experiment_counts={"E20260901-0001": 2},
        run_experiment_status_counts={"E20260901-0001": {"completed": 1, "running": 1}},
        unreviewed_completed_count=1,
        test_attempt_count=3,
        test_attempt_state_counts={"passed": 2, "prepared": 1},
        old_test_attempt_count=2,
        old_terminal_test_attempt_count=1,
        old_active_test_attempt_count=1,
        active_result_count=2,
        archived_result_count=1,
        result_status_counts={"draft": 1, "sealed": 1},
        diagnostics=(
            TriageDiagnostic(
                section="runs",
                code="run.manifest_invalid",
                path="runs/broken/manifest.toml",
                message="invalid TOML",
            ),
        ),
        suggested_actions=(
            "Review pending Experiment E20260901-0001: runo experiments review "
            "E20260901-0001 --decision DECISION --reason WHY",
            "Resolve 1 invalid project record listed in diagnostics before "
            "creating new state.",
        ),
    )


def test_triage_json_emits_stable_machine_readable_report(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "demo"\n',
        encoding="utf-8",
    )
    expected = _report(tmp_path.resolve())

    with patch("runops.cli.triage.build_triage_report", return_value=expected):
        result = runner.invoke(app, ["triage", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == expected.to_dict()


def test_triage_text_leads_with_attention_and_actions(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "demo"\n',
        encoding="utf-8",
    )

    with patch(
        "runops.cli.triage.build_triage_report",
        return_value=_report(tmp_path.resolve()),
    ):
        result = runner.invoke(app, ["triage", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "ACTIVE EXPERIMENTS (1; pending decision: 1)" in result.output
    assert "ACTIVE FORMAL RUNS (2)" in result.output
    assert "Unreviewed completed Runs: 1" in result.output
    assert "Old TestAttempts (>=" in result.output
    assert "RESULTS (active: 2; archived: 1)" in result.output
    assert "DIAGNOSTICS (1)" in result.output
    assert "SUGGESTED ACTIONS" in result.output
    assert "runo experiments review" in result.output


def test_triage_renders_unavailable_run_namespace_as_null_and_not_zero(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "unsafe-runs"\n',
        encoding="utf-8",
    )
    runs = tmp_path / "runs"
    runs.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (runs / "hidden").symlink_to(outside, target_is_directory=True)

    json_result = runner.invoke(app, ["triage", str(tmp_path), "--json"])
    text_result = runner.invoke(app, ["triage", str(tmp_path)])

    assert json_result.exit_code == 0, json_result.output
    payload = json.loads(json_result.stdout)
    assert payload["runs"]["namespace_available"] is False
    assert payload["runs"]["active_formal_count"] is None
    assert payload["runs"]["by_status"] is None
    assert text_result.exit_code == 0, text_result.output
    assert "ACTIVE FORMAL RUNS (unavailable)" in text_result.output
    assert "ACTIVE FORMAL RUNS (0)" not in text_result.output


def test_triage_corrupt_manifest_renders_every_run_aggregate_as_unavailable(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "corrupt-runs"\n',
        encoding="utf-8",
    )
    broken = tmp_path / "runs" / "broken"
    broken.mkdir(parents=True)
    (broken / "manifest.toml").write_text("[run\n", encoding="utf-8")

    result = runner.invoke(app, ["triage", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["runs"] == {
        "namespace_available": False,
        "active_formal_count": None,
        "by_status": None,
        "by_experiment": None,
        "unreviewed_completed_count": None,
    }


def test_triage_missing_project_is_an_explicit_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["triage", str(tmp_path), "--json"])

    assert result.exit_code == 2
    assert "Error:" in result.output
