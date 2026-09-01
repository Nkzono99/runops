"""Application tests for bounded Experiment admission and review."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import tomli_w

from runops.application import experiments as experiments_module
from runops.application.experiments import (
    ExperimentWorkflowError,
    close_experiment,
    create_experiment,
    review_experiment,
)
from runops.application.run_creation.workflow import (
    build_standalone_manifest_metadata,
)
from runops.core.exceptions import ExperimentConfigError, SimctlError
from runops.core.project import load_project


def _write_project(root: Path, *, max_active: int = 2) -> None:
    (root / "runops.toml").write_text(
        "[project]\n"
        'name = "experiment-tests"\n\n'
        "[experiments.policy]\n"
        "require_experiment = true\n"
        f"max_active_experiments = {max_active}\n"
        "default_max_materialized_runs = 3\n"
        "max_unreviewed_completed_runs = 4\n",
        encoding="utf-8",
    )


def _create(
    root: Path,
    *,
    title: str = "Question one",
    expires_at: str = "2026-10-01T00:00:00+00:00",
):
    return create_experiment(
        root,
        title=title,
        question="Does the response converge?",
        intent="explore",
        baseline_reason="No prior compatible run exists.",
        max_planned_points=12,
        max_materialized_runs=4,
        max_active_runs=2,
        max_core_hours=20.0,
        max_unreviewed_runs=2,
        expires_at=expires_at,
        exit_criteria=("Stop after the convergence trend is resolved.",),
        review_due="2026-09-15",
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


def _write_baseline(root: Path, run_id: str, *, status: str) -> None:
    run_dir = root / "runs" / "baseline" / run_id
    run_dir.mkdir(parents=True)
    with (run_dir / "manifest.toml").open("wb") as stream:
        tomli_w.dump({"run": {"id": run_id, "status": status}}, stream)


@pytest.mark.parametrize(
    ("baseline_run_ids", "baseline_reason"),
    [
        ((), ""),
        (("R20260901-0001",), "A reason as well"),
    ],
)
def test_create_requires_exactly_one_baseline_and_leaves_no_definition(
    tmp_path: Path,
    baseline_run_ids: tuple[str, ...],
    baseline_reason: str,
) -> None:
    _write_project(tmp_path)

    with pytest.raises(ExperimentWorkflowError, match="exactly one"):
        create_experiment(
            tmp_path,
            title="Invalid admission",
            question="Should this be admitted?",
            intent="explore",
            baseline_run_ids=baseline_run_ids,
            baseline_reason=baseline_reason,
            max_planned_points=4,
            max_materialized_runs=2,
            max_active_runs=1,
            max_core_hours=4.0,
            max_unreviewed_runs=1,
            expires_at="2099-01-01T00:00:00+00:00",
            exit_criteria=("Reach a decision.",),
        )

    assert not (tmp_path / "experiments").exists()
    assert list((tmp_path / ".runops").glob("*.tmp")) == []


def test_create_baseline_resolution_never_uses_current_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    (project / "runs").mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    external_run_id = "R20260901-0001"
    external_run = cwd / external_run_id
    external_run.mkdir()
    with (external_run / "manifest.toml").open("wb") as stream:
        tomli_w.dump(
            {"run": {"id": external_run_id, "status": "completed"}},
            stream,
        )
    monkeypatch.chdir(cwd)

    with pytest.raises(ExperimentWorkflowError, match="not resolvable"):
        create_experiment(
            project,
            title="Project-local baseline",
            question="Can a CWD run satisfy the baseline?",
            intent="explore",
            baseline_run_ids=(external_run_id,),
            max_planned_points=2,
            max_materialized_runs=1,
            max_active_runs=1,
            max_core_hours=2.0,
            max_unreviewed_runs=1,
            expires_at="2099-01-01T00:00:00+00:00",
            exit_criteria=("Reject external baseline resolution.",),
        )

    assert not (project / "experiments").exists()


@pytest.mark.parametrize(
    ("planned", "materialized", "active", "core_hours", "unreviewed"),
    [
        (0, 1, 1, 1.0, 0),
        (1, 2, 1, 1.0, 0),
        (2, 1, 2, 1.0, 0),
        (2, 1, 1, 0.0, 0),
        (2, 1, 1, 1.0, -1),
    ],
)
def test_create_rejects_invalid_budget_without_persisting_a_draft(
    tmp_path: Path,
    planned: int,
    materialized: int,
    active: int,
    core_hours: float,
    unreviewed: int,
) -> None:
    _write_project(tmp_path)

    with pytest.raises(ExperimentWorkflowError):
        create_experiment(
            tmp_path,
            title="Invalid budget",
            question="Can an invalid budget be admitted?",
            intent="explore",
            baseline_reason="No baseline needed.",
            max_planned_points=planned,
            max_materialized_runs=materialized,
            max_active_runs=active,
            max_core_hours=core_hours,
            max_unreviewed_runs=unreviewed,
            expires_at="2099-01-01T00:00:00+00:00",
            exit_criteria=("Never reached.",),
        )

    assert not (tmp_path / "experiments").exists()


@pytest.mark.parametrize(
    "expires_at",
    [
        "",
        "2026-10-01T00:00:00",
        "2026-09-01T00:00:00+00:00",
        "2026-08-31T23:59:59+00:00",
    ],
)
def test_create_rejects_invalid_or_nonfuture_expiry_before_allocating_id(
    tmp_path: Path,
    expires_at: str,
) -> None:
    _write_project(tmp_path)

    with pytest.raises(ExperimentWorkflowError, match="expires_at"):
        _create(tmp_path, expires_at=expires_at)

    assert not (tmp_path / "experiments").exists()
    assert not (tmp_path / ".runops" / "experiment-id-sequence.toml").exists()


def test_expired_experiment_blocks_formal_run_admission_at_deadline(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    created = _create(tmp_path, expires_at="2026-09-02T00:00:00+00:00")

    with pytest.raises(SimctlError, match="expired at"):
        build_standalone_manifest_metadata(
            load_project(tmp_path),
            experiment_id=created.experiment.id,
            purpose="explore",
            created_by="agent",
            now=datetime(2026, 9, 2, tzinfo=timezone.utc),
        )


def test_create_accepts_rfc3339_utc_designator(tmp_path: Path) -> None:
    _write_project(tmp_path)

    created = _create(tmp_path, expires_at="2026-10-01T00:00:00Z")

    assert created.experiment.budget.expires_at == "2026-10-01T00:00:00Z"


def test_baseline_run_ids_must_resolve_uniquely_to_completed_runs(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    run_id = "R20260901-0001"
    _write_baseline(tmp_path, run_id, status="created")

    common = {
        "title": "Baseline contract",
        "question": "Is this baseline admissible?",
        "intent": "validate",
        "baseline_run_ids": (run_id,),
        "max_planned_points": 2,
        "max_materialized_runs": 1,
        "max_active_runs": 1,
        "max_core_hours": 2.0,
        "max_unreviewed_runs": 1,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "exit_criteria": ("Compare against the completed baseline.",),
    }
    with pytest.raises(ExperimentWorkflowError, match="must be completed"):
        create_experiment(tmp_path, **common)

    baseline_path = tmp_path / "runs" / "baseline" / run_id / "manifest.toml"
    with baseline_path.open("wb") as stream:
        tomli_w.dump({"run": {"id": run_id, "status": "completed"}}, stream)
    created = create_experiment(tmp_path, **common)
    assert created.experiment.baseline.run_ids == (run_id,)

    duplicate = tmp_path / "runs" / "duplicate" / run_id
    duplicate.mkdir(parents=True)
    with (duplicate / "manifest.toml").open("wb") as stream:
        tomli_w.dump({"run": {"id": run_id, "status": "completed"}}, stream)
    with pytest.raises(ExperimentWorkflowError, match="not resolvable"):
        create_experiment(tmp_path, **common)


@pytest.mark.parametrize("status", ["completed", "archived", "purged"])
def test_completed_equivalent_baseline_states_are_admissible(
    tmp_path: Path,
    status: str,
) -> None:
    _write_project(tmp_path)
    run_id = "R20260901-0001"
    _write_baseline(tmp_path, run_id, status=status)

    created = create_experiment(
        tmp_path,
        title=f"Baseline {status}",
        question="Can completed-equivalent evidence be reused?",
        intent="validate",
        baseline_run_ids=(run_id,),
        max_planned_points=2,
        max_materialized_runs=1,
        max_active_runs=1,
        max_core_hours=2.0,
        max_unreviewed_runs=1,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Compare one candidate against the baseline.",),
    )

    assert created.experiment.baseline.run_ids == (run_id,)


def test_failed_definition_commit_burns_experiment_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_project(tmp_path)
    real_write = experiments_module._write_new_toml

    def _fail_write(_path: Path, _payload: dict[str, object]) -> None:
        raise ExperimentWorkflowError("injected definition write failure")

    monkeypatch.setattr(experiments_module, "_write_new_toml", _fail_write)
    with pytest.raises(ExperimentWorkflowError, match="injected"):
        _create(tmp_path)
    assert list((tmp_path / "experiments").glob("*.toml")) == []

    monkeypatch.setattr(experiments_module, "_write_new_toml", real_write)
    created = _create(tmp_path)
    assert created.experiment.id == "E20260901-0002"


def test_deleted_experiment_id_is_not_reused(tmp_path: Path) -> None:
    _write_project(tmp_path)
    first = _create(tmp_path)
    first.path.unlink()

    second = _create(tmp_path, title="Replacement question")

    assert first.experiment.id == "E20260901-0001"
    assert second.experiment.id == "E20260901-0002"


def test_active_experiment_wip_limit_is_enforced_before_new_file(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path, max_active=1)
    first = _create(tmp_path)

    with pytest.raises(ExperimentWorkflowError, match="WIP limit"):
        _create(tmp_path, title="Question two")

    assert [path.name for path in (tmp_path / "experiments").glob("*.toml")] == [
        first.path.name
    ]


def test_symlinked_active_definition_cannot_bypass_wip_limit(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path, max_active=1)
    first = _create(tmp_path)
    ledger = tmp_path / ".runops" / "experiment-id-sequence.toml"
    before = ledger.read_bytes()
    external = tmp_path / "external-active-experiment.toml"
    external.write_bytes(first.path.read_bytes())
    first.path.unlink()
    first.path.symlink_to(external)

    with pytest.raises(ExperimentConfigError, match="single-link regular file"):
        _create(tmp_path, title="Question two")

    assert ledger.read_bytes() == before
    assert first.path.is_symlink()
    assert len(list((tmp_path / "experiments").glob("*.toml"))) == 1


def test_create_review_and_close_keep_decision_separate_from_outcome(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    created = _create(tmp_path)

    reviewed = review_experiment(
        tmp_path,
        created.experiment.id,
        decision="expand",
        outcome="unknown",
        reason="The pilot is stable enough for the main phase.",
        now=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    assert reviewed.experiment.lifecycle == "active"
    assert reviewed.experiment.decision == "expand"
    assert reviewed.experiment.outcome == "unknown"

    closed = close_experiment(
        tmp_path,
        created.experiment.id,
        decision="accept",
        outcome="supported",
        reason="The predeclared convergence criterion was met.",
        now=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    assert closed.experiment.lifecycle == "closed"
    assert closed.experiment.decision == "accept"
    assert closed.experiment.outcome == "supported"

    with pytest.raises(ExperimentWorkflowError, match="expected 'active'"):
        review_experiment(
            tmp_path,
            created.experiment.id,
            decision="revise",
            reason="A closed Experiment is immutable to normal review.",
        )


def test_atomic_review_preserves_unknown_sections(tmp_path: Path) -> None:
    _write_project(tmp_path)
    created = _create(tmp_path)
    raw = created.experiment.raw
    raw["extension"] = {"owner": "lab", "priority": 7}
    with created.path.open("wb") as stream:
        tomli_w.dump(raw, stream)

    reviewed = review_experiment(
        tmp_path,
        created.experiment.id,
        decision="revise",
        reason="The extension data must survive a structured update.",
    )

    assert reviewed.experiment.raw["extension"] == {"owner": "lab", "priority": 7}
    assert list(created.path.parent.glob(f".{created.path.name}.*.tmp")) == []
