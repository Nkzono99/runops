"""Tests for derived experiment readiness projections."""

from __future__ import annotations

import sys
from pathlib import Path

import tomli_w

from runops.application.research.experiments import (
    check_experiments,
    list_experiment_projections,
    project_experiment,
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


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
    root.mkdir(parents=True)
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


def _update_experiment(root: Path, **updates: object) -> None:
    ledger = root / "research" / "experiments.toml"
    with open(ledger, "rb") as stream:
        payload = tomllib.load(stream)
    experiment = payload["experiments"][0]
    experiment.update(updates)
    _write(ledger, payload)


def _survey(root: Path, stage: str = "pilot") -> Path:
    path = root / "runs" / f"{stage}-scan"
    _write(
        path / "survey.toml",
        {
            "survey": {"id": f"S-{stage}"},
            "research": {"experiment_id": "E1", "stage": stage},
        },
    )
    return path


def _run(
    survey: Path,
    *,
    stage: str,
    state: str,
    artifact: str = "none",
) -> Path:
    run = survey / "R1"
    _write(
        run / "manifest.toml",
        {
            "run": {"id": "R1", "status": state},
            "origin": {"survey": f"S-{stage}"},
        },
    )
    if artifact == "valid":
        _write(
            run / "analysis" / "artifacts.toml",
            {"schema_version": 1, "artifacts": [{"path": "result.json"}]},
        )
    elif artifact == "invalid":
        index = run / "analysis" / "artifacts.toml"
        index.parent.mkdir(exist_ok=True)
        index.write_text("not = [valid", encoding="utf-8")
    return run


def test_projection_phase_priority_covers_lifecycle_states(tmp_path: Path) -> None:
    stopped = _project(tmp_path / "stopped")
    _update_experiment(stopped, decision="STOP")
    assert project_experiment(stopped, "E1").phase == "stopped"

    revising = _project(tmp_path / "revising")
    _update_experiment(revising, decision="REVISE")
    assert project_experiment(revising, "E1").phase == "revising"

    planned = _project(tmp_path / "planned")
    _survey(planned)
    assert project_experiment(planned, "E1").phase == "pilot-planned"

    ready = _project(tmp_path / "ready")
    ready_survey = _survey(ready)
    _run(ready_survey, stage="pilot", state="created")
    assert project_experiment(ready, "E1").phase == "pilot-ready"

    active = _project(tmp_path / "active")
    active_survey = _survey(active)
    _run(active_survey, stage="pilot", state="running")
    assert project_experiment(active, "E1").phase == "pilot-active"

    review = _project(tmp_path / "review")
    review_survey = _survey(review)
    _run(review_survey, stage="pilot", state="completed")
    assert project_experiment(review, "E1").phase == "review-pending"

    full_active = _project(tmp_path / "full-active")
    full_survey = _survey(full_active, "full")
    _run(full_survey, stage="full", state="submitted")
    assert project_experiment(full_active, "E1").phase == "full-active"

    completed = _project(tmp_path / "completed")
    completed_survey = _survey(completed, "full")
    _run(completed_survey, stage="full", state="completed", artifact="valid")
    projection = project_experiment(completed, "E1")
    assert projection.phase == "completed"
    assert projection.required_artifacts == projection.present_artifacts == 1


def test_projection_reports_invalid_surveys_runs_and_artifacts(tmp_path: Path) -> None:
    root = _project(tmp_path)
    survey = _survey(root)
    _run(survey, stage="pilot", state="mystery", artifact="invalid")
    invalid_survey = root / "runs" / "broken" / "survey.toml"
    invalid_survey.parent.mkdir()
    invalid_survey.write_text("broken = [", encoding="utf-8")
    invalid_run = root / "runs" / "broken-run" / "manifest.toml"
    invalid_run.parent.mkdir()
    invalid_run.write_text("broken = [", encoding="utf-8")

    projection = project_experiment(root, "E1")

    warning_codes = {item.code for item in projection.warnings}
    assert "survey_invalid" in warning_codes
    assert "manifest_invalid" in warning_codes
    assert "run_state_unknown" in warning_codes

    _run(survey, stage="pilot", state="completed", artifact="invalid")
    projection = project_experiment(root, "E1")
    assert "artifact_index_invalid" in {item.code for item in projection.warnings}


def test_projection_reports_migration_review_stage_and_authorization_blockers(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    _update_experiment(
        root,
        title="",
        migration_blockers=["title"],
        decision="EXPAND",
        review="research/reviews/missing.md",
        authorization={
            "stage": "full",
            "survey": "runs/other",
            "review": "research/reviews/missing.md",
            "max_core_hours": 20.0,
        },
    )
    invalid = root / "runs" / "bad-stage"
    _write(
        invalid / "survey.toml",
        {
            "survey": {"id": "bad"},
            "research": {"experiment_id": "E1", "stage": "production"},
        },
    )
    _survey(root, "full")

    projection = project_experiment(root, "E1")

    assert projection.phase == "blocked"
    assert {
        "migration_incomplete",
        "review_missing",
        "survey_stage_invalid",
        "authorization_invalid",
    } <= {item.code for item in projection.blockers}
