"""CLI tests for typed experiment workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from runops.cli.main import app

if TYPE_CHECKING:
    from pytest import MonkeyPatch

runner = CliRunner()


def _project(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    root = tmp_path / "project"
    (root / "research").mkdir(parents=True)
    (root / "runops.toml").write_text('[project]\nname = "test"\n', encoding="utf-8")
    (root / "research" / "experiments.toml").write_text(
        "schema_version = 2\n", encoding="utf-8"
    )
    monkeypatch.chdir(root)
    return root


def _spec(tmp_path: Path) -> Path:
    path = tmp_path / "experiment.json"
    path.write_text(
        json.dumps(
            {
                "title": "Ion depletion pilot",
                "question": "Does vti widen the depletion cone?",
                "selected_candidate": "C1",
                "cost_ceiling_core_hours": 128.0,
                "candidates": [
                    {
                        "id": "C1",
                        "information_gain": "thermal scaling",
                        "falsification": "no response",
                        "estimated_core_hours": 32.0,
                        "operational_risk": "low",
                    },
                    {
                        "id": "C2",
                        "information_gain": "resolution sensitivity",
                        "falsification": "trend changes",
                        "estimated_core_hours": 64.0,
                        "operational_risk": "medium",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_experiment_new_json_without_yes_returns_non_mutating_plan(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = _project(tmp_path, monkeypatch)

    result = runner.invoke(
        app, ["experiment", "new", "E1", "--from", str(_spec(tmp_path)), "--json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "planned"
    assert payload["data"]["dry_run"] is True
    assert not (root / "research" / "proposals" / "E1.md").exists()


def test_experiment_new_from_spec_and_show_json(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _project(tmp_path, monkeypatch)

    created = runner.invoke(
        app,
        [
            "experiment",
            "new",
            "E1",
            "--from",
            str(_spec(tmp_path)),
            "--json",
            "--yes",
        ],
    )

    assert created.exit_code == 0
    payload = json.loads(created.stdout)
    assert payload["schema_version"] == 1
    assert payload["status"] == "success"
    shown = runner.invoke(app, ["experiment", "show", "E1", "--json"])
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)["data"]["experiment"]["id"] == "E1"


def test_experiment_check_returns_one_for_errors(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = _project(tmp_path, monkeypatch)
    created = runner.invoke(
        app,
        [
            "experiment",
            "new",
            "E1",
            "--from",
            str(_spec(tmp_path)),
            "--yes",
        ],
    )
    assert created.exit_code == 0
    (root / "research" / "proposals" / "E1.md").unlink()

    result = runner.invoke(app, ["experiment", "check", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "blocked"
