"""CLI contract tests for Experiment admission and review."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


def _write_project(root: Path) -> None:
    (root / "runops.toml").write_text(
        "[project]\n"
        'name = "experiment-cli"\n\n'
        "[experiments.policy]\n"
        "require_experiment = true\n"
        "max_active_experiments = 2\n"
        "default_max_materialized_runs = 3\n"
        "max_unreviewed_completed_runs = 4\n",
        encoding="utf-8",
    )


def _create_args(root: Path) -> list[str]:
    return [
        "experiments",
        "create",
        "Convergence study",
        "--question",
        "Does the response converge?",
        "--intent",
        "explore",
        "--baseline-reason",
        "No compatible prior run exists.",
        "--exit",
        "Stop after the trend is resolved.",
        "--max-planned-points",
        "8",
        "--max-materialized-runs",
        "4",
        "--max-active-runs",
        "2",
        "--max-core-hours",
        "20",
        "--max-unreviewed-runs",
        "2",
        "--expires-at",
        "2099-01-01T00:00:00+00:00",
        "--path",
        str(root),
    ]


def test_experiment_cli_create_list_and_inspect_json(tmp_path: Path) -> None:
    _write_project(tmp_path)

    created = runner.invoke(app, _create_args(tmp_path))
    assert created.exit_code == 0, created.output
    assert "Created Experiment E" in created.output
    experiment_file = next((tmp_path / "experiments").glob("*.toml"))
    experiment_id = experiment_file.name.split("--", maxsplit=1)[0]

    listed = runner.invoke(
        app,
        ["experiments", "list", str(tmp_path), "--json"],
    )
    assert listed.exit_code == 0, listed.output
    list_payload = json.loads(listed.output)
    assert [(item["id"], item["lifecycle"]) for item in list_payload] == [
        (experiment_id, "active")
    ]

    inspected = runner.invoke(
        app,
        [
            "experiments",
            "inspect",
            experiment_id,
            "--path",
            str(tmp_path),
            "--json",
        ],
    )
    assert inspected.exit_code == 0, inspected.output
    payload = json.loads(inspected.output)
    assert payload["question"] == "Does the response converge?"
    assert payload["baseline_reason"] == "No compatible prior run exists."
    assert payload["budget"]["max_materialized_runs"] == 4
    assert payload["budget"]["expires_at"] == "2099-01-01T00:00:00+00:00"
    assert payload["exit_criteria"] == ["Stop after the trend is resolved."]

    inspected_text = runner.invoke(
        app,
        ["experiments", "inspect", experiment_id, "--path", str(tmp_path)],
    )
    assert inspected_text.exit_code == 0, inspected_text.output
    assert "expires_at=2099-01-01T00:00:00+00:00" in inspected_text.output


def test_experiment_cli_review_then_close(tmp_path: Path) -> None:
    _write_project(tmp_path)
    created = runner.invoke(app, _create_args(tmp_path))
    assert created.exit_code == 0, created.output
    experiment_id = next((tmp_path / "experiments").glob("*.toml")).name.split(
        "--", maxsplit=1
    )[0]

    reviewed = runner.invoke(
        app,
        [
            "experiments",
            "review",
            experiment_id,
            "--decision",
            "expand",
            "--reason",
            "Pilot passed its stability check.",
            "--path",
            str(tmp_path),
        ],
    )
    assert reviewed.exit_code == 0, reviewed.output
    assert "decision=expand" in reviewed.output

    closed = runner.invoke(
        app,
        [
            "experiments",
            "close",
            experiment_id,
            "--decision",
            "accept",
            "--outcome",
            "supported",
            "--reason",
            "Exit criterion was met.",
            "--path",
            str(tmp_path),
        ],
    )
    assert closed.exit_code == 0, closed.output
    assert "outcome=supported" in closed.output


def test_experiment_cli_rejects_unbounded_definition_without_file(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    args = _create_args(tmp_path)
    baseline_index = args.index("--baseline-reason")
    del args[baseline_index : baseline_index + 2]

    result = runner.invoke(app, args)

    assert result.exit_code == 2, result.output
    assert "exactly one" in result.output
    assert not (tmp_path / "experiments").exists()
