"""Tests for structured survey expansion authorization."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomli_w

from runops.application.research.experiments import validate_bulk_experiment_gate
from runops.core.exceptions import SimctlError


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as stream:
        tomli_w.dump(payload, stream)  # type: ignore[arg-type]


def _project(tmp_path: Path, *, stage: str = "pilot", decision: str = "WAIT") -> Path:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "test"\n', encoding="utf-8"
    )
    survey = tmp_path / "runs" / "scan"
    _write(
        survey / "survey.toml",
        {
            "survey": {"base_case": "base", "simulator": "test", "launcher": "srun"},
            "research": {"experiment_id": "E1", "stage": stage},
        },
    )
    proposal = tmp_path / "research" / "proposals" / "e1.md"
    proposal.parent.mkdir(parents=True, exist_ok=True)
    proposal.write_text("proposal\n", encoding="utf-8")
    review = tmp_path / "research" / "reviews" / "e1.md"
    review.parent.mkdir(parents=True, exist_ok=True)
    review.write_text("Decision: EXPAND\n", encoding="utf-8")
    _write(
        tmp_path / "research" / "experiments.toml",
        {
            "schema_version": 1,
            "experiments": [
                {
                    "id": "E1",
                    "decision": decision,
                    "proposal": "research/proposals/e1.md",
                    "review": "research/reviews/e1.md" if decision == "EXPAND" else "",
                    "selected_candidate": "C1",
                    "candidates": [
                        {
                            "id": "C1",
                            "information_gain": "high",
                            "falsification": "x",
                            "estimated_core_hours": 1.0,
                            "operational_risk": "low",
                        },
                        {
                            "id": "C2",
                            "information_gain": "medium",
                            "falsification": "y",
                            "estimated_core_hours": 2.0,
                            "operational_risk": "medium",
                        },
                    ],
                }
            ],
        },
    )
    return survey


def test_generic_bulk_directory_is_not_governed(tmp_path: Path) -> None:
    assert validate_bulk_experiment_gate(tmp_path) is None


def test_pilot_stage_is_authorized_before_expand(tmp_path: Path) -> None:
    authorization = validate_bulk_experiment_gate(_project(tmp_path))

    assert authorization is not None
    assert authorization.experiment_id == "E1"
    assert authorization.stage == "pilot"


def test_full_stage_requires_expand_and_review(tmp_path: Path) -> None:
    with pytest.raises(SimctlError, match="requires decision EXPAND"):
        validate_bulk_experiment_gate(_project(tmp_path, stage="full"))

    authorization = validate_bulk_experiment_gate(
        _project(tmp_path, stage="full", decision="EXPAND")
    )
    assert authorization is not None
    assert authorization.decision == "EXPAND"


def test_survey_research_table_is_required(tmp_path: Path) -> None:
    survey = _project(tmp_path)
    _write(survey / "survey.toml", {"survey": {"id": "scan"}})

    with pytest.raises(SimctlError, match=r"\[research\]"):
        validate_bulk_experiment_gate(survey)


def test_candidate_comparison_requires_two_complete_unique_candidates(
    tmp_path: Path,
) -> None:
    survey = _project(tmp_path)
    ledger = tmp_path / "research" / "experiments.toml"
    _write(
        ledger,
        {
            "schema_version": 1,
            "experiments": [
                {
                    "id": "E1",
                    "decision": "WAIT",
                    "proposal": "research/proposals/e1.md",
                    "selected_candidate": "C1",
                    "candidates": [{"id": "C1"}],
                }
            ],
        },
    )

    with pytest.raises(SimctlError, match="at least two candidates"):
        validate_bulk_experiment_gate(survey)


def test_selected_candidate_and_project_relative_proposal_are_validated(
    tmp_path: Path,
) -> None:
    survey = _project(tmp_path)
    ledger = tmp_path / "research" / "experiments.toml"
    payload = {
        "schema_version": 1,
        "experiments": [
            {
                "id": "E1",
                "decision": "WAIT",
                "proposal": "/outside/proposal.md",
                "selected_candidate": "missing",
                "candidates": [
                    {
                        "id": "C1",
                        "information_gain": "high",
                        "falsification": "x",
                        "estimated_core_hours": 1,
                        "operational_risk": "low",
                    },
                    {
                        "id": "C2",
                        "information_gain": "low",
                        "falsification": "y",
                        "estimated_core_hours": 2,
                        "operational_risk": "low",
                    },
                ],
            }
        ],
    }
    _write(ledger, payload)

    with pytest.raises(SimctlError, match="selected_candidate"):
        validate_bulk_experiment_gate(survey)
