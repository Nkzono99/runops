"""Tests for derived experiment readiness projections."""

from __future__ import annotations

from pathlib import Path

import tomli_w

from runops.application.research.experiments import (
    check_experiments,
    list_experiment_projections,
    project_experiment,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as stream:
        tomli_w.dump(payload, stream)  # type: ignore[arg-type]


def _candidate(candidate_id: str, cost: float) -> dict[str, object]:
    return {
        "id": candidate_id,
        "information_gain": "gain",
        "falsification": "criterion",
        "estimated_core_hours": cost,
        "operational_risk": "low",
    }


def _project(tmp_path: Path, *, proposal: bool = True) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "runops.toml").write_text('[project]\nname = "test"\n', encoding="utf-8")
    if proposal:
        path = root / "research" / "proposals" / "E1.md"
        path.parent.mkdir(parents=True)
        path.write_text("# E1\n", encoding="utf-8")
    _write(
        root / "research" / "experiments.toml",
        {
            "schema_version": 2,
            "experiments": [
                {
                    "id": "E1",
                    "title": "Experiment one",
                    "question": "Does it work?",
                    "decision": "WAIT",
                    "proposal": "research/proposals/E1.md",
                    "review": "",
                    "selected_candidate": "C1",
                    "cost_ceiling_core_hours": 20.0,
                    "candidates": [_candidate("C1", 10.0), _candidate("C2", 15.0)],
                }
            ],
        },
    )
    return root


def test_projection_derives_blocked_without_persisting_phase(tmp_path: Path) -> None:
    root = _project(tmp_path, proposal=False)

    projection = project_experiment(root, "E1")

    assert projection.phase == "blocked"
    assert "proposal_missing" in {item.code for item in projection.blockers}
    assert projection.next_actions == ("Create the proposal attachment.",)


def test_projection_derives_full_authorized_from_scope(tmp_path: Path) -> None:
    root = _project(tmp_path)
    review = root / "research" / "reviews" / "E1.md"
    review.parent.mkdir()
    review.write_text("Decision: EXPAND\n", encoding="utf-8")
    survey = root / "runs" / "full-scan"
    _write(
        survey / "survey.toml",
        {
            "survey": {"id": "S1"},
            "research": {"experiment_id": "E1", "stage": "full"},
        },
    )
    ledger_path = root / "research" / "experiments.toml"
    _write(
        ledger_path,
        {
            "schema_version": 2,
            "experiments": [
                {
                    "id": "E1",
                    "title": "Experiment one",
                    "question": "Does it work?",
                    "decision": "EXPAND",
                    "proposal": "research/proposals/E1.md",
                    "review": "research/reviews/E1.md",
                    "selected_candidate": "C1",
                    "cost_ceiling_core_hours": 20.0,
                    "candidates": [_candidate("C1", 10.0), _candidate("C2", 15.0)],
                    "authorization": {
                        "stage": "full",
                        "survey": "runs/full-scan",
                        "review": "research/reviews/E1.md",
                        "max_core_hours": 20.0,
                    },
                }
            ],
        },
    )

    projection = project_experiment(root, "E1")

    assert projection.phase == "full-authorized"
    assert projection.blockers == ()
    assert projection.next_commands == (
        "runo experiment submit E1 --stage full --dry-run",
    )


def test_list_and_check_are_stably_ordered(tmp_path: Path) -> None:
    root = _project(tmp_path, proposal=False)

    projections = list_experiment_projections(root)
    issues = check_experiments(root)

    assert [item.experiment.id for item in projections] == ["E1"]
    assert [item.code for item in issues] == sorted(item.code for item in issues)
