"""Admission and recovery tests for lazy Survey materialization."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import tomli_w

from runops.application.experiments import create_experiment, review_experiment
from runops.application.run_creation import create_case_run
from runops.application.run_creation import workflow as run_creation_module
from runops.application.survey_materialization import (
    SurveyMaterializationError,
    materialize_survey_points,
    preview_survey_plan,
)
from runops.core.exceptions import SimctlError
from runops.core.manifest import (
    ManifestData,
    read_manifest,
    update_manifest,
    write_manifest,
)
from runops.core.project import ProjectConfig, load_project


def _write_project(
    root: Path,
    *,
    require_experiment: bool = True,
    default_materialized: int = 3,
    project_unreviewed: int = 4,
) -> ProjectConfig:
    (root / "runops.toml").write_text(
        "[project]\n"
        'name = "survey-tests"\n\n'
        "[experiments.policy]\n"
        f"require_experiment = {str(require_experiment).lower()}\n"
        "max_active_experiments = 8\n"
        f"default_max_materialized_runs = {default_materialized}\n"
        f"max_unreviewed_completed_runs = {project_unreviewed}\n",
        encoding="utf-8",
    )
    (root / "simulators.toml").write_text(
        "[simulators.test_sim]\n"
        'adapter = "generic"\n'
        'executable = "echo"\n'
        'resolver_mode = "package"\n',
        encoding="utf-8",
    )
    (root / "launchers.toml").write_text(
        "[launchers.slurm_srun]\n"
        'kind = "srun"\n'
        'command = "srun"\n'
        "use_slurm_ntasks = true\n",
        encoding="utf-8",
    )
    case_dir = root / "cases" / "base_case"
    case_dir.mkdir(parents=True)
    (root / "runs").mkdir()
    (case_dir / "case.toml").write_text(
        "[case]\n"
        'name = "base_case"\n'
        'simulator = "test_sim"\n'
        'launcher = "slurm_srun"\n\n'
        "[job]\n"
        'partition = "debug"\n'
        "nodes = 1\n"
        "ntasks = 2\n"
        'walltime = "01:00:00"\n\n'
        "[params]\n"
        "nx = 64\n"
        "ny = 64\n",
        encoding="utf-8",
    )
    return load_project(root)


def _admit_experiment(
    root: Path,
    *,
    planned: int = 20,
    materialized: int = 10,
    active: int = 10,
    core_hours: float = 100.0,
    unreviewed: int = 10,
) -> str:
    created = create_experiment(
        root,
        title="Survey admission",
        question="Which candidate closes the information gap?",
        intent="explore",
        baseline_reason="No compatible baseline is available.",
        max_planned_points=planned,
        max_materialized_runs=materialized,
        max_active_runs=active,
        max_core_hours=core_hours,
        max_unreviewed_runs=unreviewed,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Stop after one candidate closes the gap.",),
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    return created.experiment.id


def _write_survey(
    root: Path,
    *,
    experiment_id: str = "",
    survey_id: str | None = "S20260901-scan",
    phase: str | None = "pilot",
    purpose: str | None = "explore",
    axes: dict[str, list[Any]] | None = None,
    materialized: int | None = 10,
    core_hours: float | None = 100.0,
    name: str = "scan",
    walltime: str | None = None,
) -> Path:
    survey_dir = root / "runs" / name
    survey_dir.mkdir(parents=True, exist_ok=True)
    survey: dict[str, Any] = {
        "name": name,
        "base_case": "base_case",
        "simulator": "test_sim",
        "launcher": "slurm_srun",
    }
    if survey_id is not None:
        survey["id"] = survey_id
    if experiment_id:
        survey["experiment_id"] = experiment_id
    if phase is not None:
        survey["phase"] = phase
    payload: dict[str, Any] = {
        "survey": survey,
        "axes": axes or {"nx": [32, 64], "ny": [32, 64]},
        "naming": {"display_name": "nx{nx}_ny{ny}"},
    }
    if walltime is not None:
        payload["job"] = {"walltime": walltime}
    if purpose is not None:
        payload["intent"] = {
            "purpose": purpose,
            "information_gap": "The stable resolution range is unknown.",
            "created_by": "agent",
        }
    budget: dict[str, Any] = {}
    if materialized is not None:
        budget["max_materialized_runs"] = materialized
    if core_hours is not None:
        budget["max_core_hours"] = core_hours
    if budget:
        payload["budget"] = budget
    with (survey_dir / "survey.toml").open("wb") as stream:
        tomli_w.dump(payload, stream)
    return survey_dir


def _run_dirs(survey_dir: Path) -> list[Path]:
    return sorted(survey_dir.glob("*/manifest.toml"))


def test_preview_is_read_only_and_large_cartesian_product_stays_bounded(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path, require_experiment=False)
    survey_dir = _write_survey(
        tmp_path,
        axes={
            "a": list(range(1000)),
            "b": list(range(1000)),
            "c": list(range(1000)),
        },
        materialized=2,
    )

    preview = preview_survey_plan(project, survey_dir, offset=10, limit=3)

    assert preview.plan.candidate_count == 1_000_000_000
    assert [point.ordinal for point in preview.points] == [11, 12, 13]
    assert len(preview.points) == 3
    assert _run_dirs(survey_dir) == []
    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()


@pytest.mark.parametrize(
    "walltime",
    ["00:00:00", "01:60:00", "01:00:60", "-01:00:00"],
)
def test_survey_walltime_override_cannot_bypass_core_hour_admission(
    tmp_path: Path,
    walltime: str,
) -> None:
    project = _write_project(tmp_path, require_experiment=False)
    survey_dir = _write_survey(
        tmp_path,
        experiment_id="",
        axes={"nx": [32]},
        walltime=walltime,
    )
    preview = preview_survey_plan(project, survey_dir)

    assert preview.plan.estimated_core_hours is None
    with pytest.raises(
        SurveyMaterializationError,
        match=r"job\.walltime is invalid",
    ):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )
    assert _run_dirs(survey_dir) == []


def test_invalid_existing_survey_run_walltime_cannot_undercharge_budget(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path, require_experiment=False)
    survey_dir = _write_survey(
        tmp_path,
        experiment_id="",
        axes={"nx": [32]},
    )
    existing_id = "R20260831-0001"
    write_manifest(
        survey_dir / existing_id,
        ManifestData(
            run={"id": existing_id, "status": "failed"},
            origin={"survey": "S20260901-scan"},
            job={"walltime": "00:00:00", "ntasks": 1},
            intent={"survey_id": "S20260901-scan", "purpose": "explore"},
        ),
    )
    preview = preview_survey_plan(project, survey_dir)

    with pytest.raises(
        SurveyMaterializationError,
        match=r"Run R20260831-0001 has invalid job\.walltime",
    ):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert len(_run_dirs(survey_dir)) == 1


@pytest.mark.parametrize(
    ("missing", "expected_issue"),
    [
        ("survey_id", "explicit survey.id"),
        ("phase", "survey.phase"),
        ("purpose", "intent.purpose"),
        ("experiment", "survey.experiment_id"),
    ],
)
def test_materialization_requires_explicit_admission_fields(
    tmp_path: Path,
    missing: str,
    expected_issue: str,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    kwargs: dict[str, Any] = {"experiment_id": experiment_id}
    if missing == "survey_id":
        kwargs["survey_id"] = None
    elif missing == "phase":
        kwargs["phase"] = None
    elif missing == "purpose":
        kwargs["purpose"] = None
    elif missing == "experiment":
        kwargs["experiment_id"] = ""
    survey_dir = _write_survey(tmp_path, **kwargs)
    preview = preview_survey_plan(project, survey_dir)
    assert any(expected_issue in issue for issue in preview.admission_issues)

    with pytest.raises(SurveyMaterializationError, match=expected_issue):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()


def test_expired_experiment_blocks_preview_admission_and_materialization(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    definition = next((tmp_path / "experiments").glob("*.toml"))
    definition.write_text(
        definition.read_text(encoding="utf-8").replace(
            'expires_at = "2099-01-01T00:00:00+00:00"',
            'expires_at = "2000-01-01T00:00:00+00:00"',
        ),
        encoding="utf-8",
    )
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)

    preview = preview_survey_plan(project, survey_dir)

    assert any("expired at" in issue for issue in preview.admission_issues)
    with pytest.raises(SurveyMaterializationError, match="expired at"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )
    assert _run_dirs(survey_dir) == []
    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()


def test_stale_plan_hash_is_rejected_before_id_allocation(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)

    _write_survey(
        tmp_path,
        experiment_id=experiment_id,
        axes={"nx": [16, 32, 64], "ny": [32, 64]},
    )

    with pytest.raises(SurveyMaterializationError, match="stale"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()


def test_stale_loaded_execution_config_cannot_authorize_materialization(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)
    simulator_file = tmp_path / "simulators.toml"
    simulator_file.write_text(
        simulator_file.read_text(encoding="utf-8") + "\n# changed after load\n",
        encoding="utf-8",
    )

    with pytest.raises(SurveyMaterializationError, match="plan is stale"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()


def test_standalone_create_uses_last_active_wip_slot_exactly_once(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(
        tmp_path,
        materialized=5,
        active=3,
        core_hours=20.0,
    )
    for sequence in (1, 2):
        run_id = f"R20260831-{sequence:04d}"
        run_dir = tmp_path / "runs" / "existing" / run_id
        write_manifest(
            run_dir,
            ManifestData(
                run={"id": run_id, "status": "created"},
                job={"walltime": "01:00:00", "ntasks": 1},
                intent={"experiment_id": experiment_id, "purpose": "explore"},
                identity={"budget_reservation": f"run:{run_id}"},
            ),
        )

    created = create_case_run(
        project,
        "base_case",
        experiment_id=experiment_id,
        purpose="explore",
    )

    assert created.run_info.run_dir.is_dir()
    before = sorted((tmp_path / "runs").rglob("manifest.toml"))
    with pytest.raises(SimctlError, match="active Run WIP limit exceeded"):
        create_case_run(
            project,
            "base_case",
            experiment_id=experiment_id,
            purpose="explore",
        )
    assert sorted((tmp_path / "runs").rglob("manifest.toml")) == before
    assert not list((tmp_path / "runs").rglob(".tmp-*"))


def test_standalone_create_rolls_back_when_expiry_crosses_publication_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    checks = 0

    def expire_after_initial_admission(
        _experiment: object,
        *,
        now: datetime | None = None,
    ) -> bool:
        del now
        nonlocal checks
        checks += 1
        return checks > 2

    monkeypatch.setattr(
        run_creation_module,
        "experiment_is_expired",
        expire_after_initial_admission,
    )

    with pytest.raises(SimctlError, match="expired at"):
        create_case_run(
            project,
            "base_case",
            experiment_id=experiment_id,
            purpose="explore",
        )

    assert checks == 3
    assert not list((tmp_path / "runs").rglob("manifest.toml"))
    assert not list((tmp_path / "runs").rglob(".tmp-*"))


def test_project_unreviewed_cap_blocks_cross_experiment_standalone_create(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path, project_unreviewed=1)
    first_experiment = _admit_experiment(tmp_path)
    second_experiment = _admit_experiment(tmp_path)
    existing_id = "R20260831-0001"
    write_manifest(
        tmp_path / "runs" / "existing" / existing_id,
        ManifestData(
            run={"id": existing_id, "status": "completed"},
            job={"walltime": "01:00:00", "ntasks": 1},
            intent={
                "experiment_id": first_experiment,
                "purpose": "explore",
            },
            identity={"budget_reservation": f"run:{existing_id}"},
            curation={"review_status": "unreviewed"},
        ),
    )

    with pytest.raises(
        SimctlError,
        match="project-wide unreviewed completed Run backlog",
    ):
        create_case_run(
            project,
            "base_case",
            experiment_id=second_experiment,
            purpose="explore",
        )

    assert len(list((tmp_path / "runs").rglob("manifest.toml"))) == 1
    assert not list((tmp_path / "runs").rglob(".tmp-*"))


def test_project_unreviewed_cap_blocks_ownerless_standalone_create(
    tmp_path: Path,
) -> None:
    project = _write_project(
        tmp_path,
        require_experiment=False,
        project_unreviewed=1,
    )
    existing_id = "R20260831-0001"
    write_manifest(
        tmp_path / "runs" / "existing" / existing_id,
        ManifestData(
            run={"id": existing_id, "status": "completed"},
            job={"walltime": "01:00:00", "ntasks": 1},
            intent={"purpose": "explore"},
            identity={"budget_reservation": f"run:{existing_id}"},
            curation={"review_status": "unreviewed"},
        ),
    )

    with pytest.raises(
        SimctlError,
        match="project-wide unreviewed completed Run backlog",
    ):
        create_case_run(project, "base_case", purpose="explore")

    assert len(list((tmp_path / "runs").rglob("manifest.toml"))) == 1
    assert not list((tmp_path / "runs").rglob(".tmp-*"))


@pytest.mark.parametrize("hidden_name", [".tmp-hidden", ".delete-hidden"])
def test_standalone_create_rejects_discovery_pruned_destination(
    tmp_path: Path,
    hidden_name: str,
) -> None:
    project = _write_project(tmp_path, require_experiment=False)
    destination = tmp_path / "runs" / hidden_name

    with pytest.raises(SimctlError, match="transaction directory"):
        create_case_run(
            project,
            "base_case",
            dest_dir=destination,
            purpose="explore",
        )

    assert not destination.exists()


def test_standalone_create_rejects_destination_inside_formal_run(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path, require_experiment=False)
    ancestor_id = "R20260831-0001"
    ancestor = tmp_path / "runs" / "existing" / ancestor_id
    write_manifest(
        ancestor,
        ManifestData(
            run={"id": ancestor_id, "status": "created"},
            job={"walltime": "01:00:00", "ntasks": 1},
        ),
    )

    with pytest.raises(SimctlError, match="inside existing formal Run"):
        create_case_run(
            project,
            "base_case",
            dest_dir=ancestor / "nested",
            purpose="explore",
        )

    assert not (ancestor / "nested").exists()


def test_standalone_create_revalidates_parent_at_publication_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path, require_experiment=False)
    destination = tmp_path / "runs" / "concurrent-parent"

    from runops.application.run_creation import workflow as workflow_module

    real_write_manifest = workflow_module.write_manifest
    injected = False

    def publish_ancestor_after_preflight(
        run_dir: Path,
        manifest: ManifestData,
        *,
        event_path: Path | None = None,
        log_event: bool = True,
    ) -> None:
        nonlocal injected
        real_write_manifest(
            run_dir,
            manifest,
            event_path=event_path,
            log_event=log_event,
        )
        if not injected and run_dir.name.startswith(".tmp-"):
            injected = True
            real_write_manifest(
                destination,
                ManifestData(
                    run={"id": "R20260831-9999", "status": "created"},
                ),
            )

    monkeypatch.setattr(
        workflow_module,
        "write_manifest",
        publish_ancestor_after_preflight,
    )

    with pytest.raises(SimctlError, match="inside existing formal Run"):
        create_case_run(
            project,
            "base_case",
            dest_dir=destination,
            purpose="explore",
        )

    assert (destination / "manifest.toml").is_file()
    assert not list(destination.glob("R*"))
    assert not list(destination.glob(".tmp-*"))


@pytest.mark.parametrize(
    "config_name",
    ["simulators.toml", "launchers.toml", "site.toml"],
)
def test_symlinked_execution_config_cannot_bypass_plan_cas(
    tmp_path: Path,
    config_name: str,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)
    config = tmp_path / config_name
    external = tmp_path / f"external-{config_name}"
    if config.exists():
        external.write_bytes(config.read_bytes())
        config.unlink()
    else:
        external.write_text("[site]\n", encoding="utf-8")
    config.symlink_to(external)

    with pytest.raises(SimctlError, match="single-link regular file"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()


def test_source_change_between_guard_and_publication_rolls_back_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)

    from runops.application.run_creation import workflow as workflow_module

    real_commit = workflow_module.commit_staged_directory
    calls = 0

    def mutate_before_publish(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            case_file = tmp_path / "cases" / "base_case" / "case.toml"
            case_file.write_text(
                case_file.read_text(encoding="utf-8") + "\n# concurrent edit\n",
                encoding="utf-8",
            )
        real_commit(source, destination)

    monkeypatch.setattr(
        workflow_module,
        "commit_staged_directory",
        mutate_before_publish,
    )

    with pytest.raises(SurveyMaterializationError, match="inputs changed"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
    assert not list(survey_dir.glob(".tmp-*"))


def test_sync_between_preflight_and_publication_rechecks_review_backlog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path, project_unreviewed=1)
    first_experiment = _admit_experiment(tmp_path)
    survey_experiment = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=survey_experiment)
    preview = preview_survey_plan(project, survey_dir)
    existing_id = "R20260831-0001"
    existing_dir = tmp_path / "runs" / "existing" / existing_id
    write_manifest(
        existing_dir,
        ManifestData(
            run={"id": existing_id, "status": "running"},
            job={"walltime": "01:00:00", "ntasks": 1},
            intent={
                "experiment_id": first_experiment,
                "purpose": "explore",
            },
            identity={"budget_reservation": f"run:{existing_id}"},
            curation={"review_status": "unreviewed"},
        ),
    )

    from runops.application.run_creation import workflow as workflow_module

    real_commit = workflow_module.commit_staged_directory
    calls = 0

    def sync_existing_before_publish(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            update_manifest(existing_dir, {"run": {"status": "completed"}})
        real_commit(source, destination)

    monkeypatch.setattr(
        workflow_module,
        "commit_staged_directory",
        sync_existing_before_publish,
    )

    with pytest.raises(
        SurveyMaterializationError,
        match="project-wide unreviewed completed Run backlog",
    ):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert read_manifest(existing_dir).run["status"] == "completed"
    assert sorted((tmp_path / "runs").rglob("manifest.toml")) == [
        existing_dir / "manifest.toml"
    ]
    assert not list(survey_dir.glob(".tmp-*"))


def test_project_policy_change_during_publication_is_reloaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path, project_unreviewed=4)
    first_experiment = _admit_experiment(tmp_path)
    survey_experiment = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=survey_experiment)
    preview = preview_survey_plan(project, survey_dir)
    existing_id = "R20260831-0001"
    existing_dir = tmp_path / "runs" / "existing" / existing_id
    write_manifest(
        existing_dir,
        ManifestData(
            run={"id": existing_id, "status": "completed"},
            job={"walltime": "01:00:00", "ntasks": 1},
            intent={
                "experiment_id": first_experiment,
                "purpose": "explore",
            },
            identity={"budget_reservation": f"run:{existing_id}"},
            curation={"review_status": "unreviewed"},
        ),
    )

    from runops.application.run_creation import workflow as workflow_module

    real_commit = workflow_module.commit_staged_directory
    calls = 0

    def tighten_policy_before_publish(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            project_file = tmp_path / "runops.toml"
            project_file.write_text(
                project_file.read_text(encoding="utf-8").replace(
                    "max_unreviewed_completed_runs = 4",
                    "max_unreviewed_completed_runs = 1",
                ),
                encoding="utf-8",
            )
        real_commit(source, destination)

    monkeypatch.setattr(
        workflow_module,
        "commit_staged_directory",
        tighten_policy_before_publish,
    )

    with pytest.raises(
        SurveyMaterializationError,
        match="Survey inputs changed",
    ):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert sorted((tmp_path / "runs").rglob("manifest.toml")) == [
        existing_dir / "manifest.toml"
    ]
    assert not list(survey_dir.glob(".tmp-*"))


def test_symlinked_current_survey_definition_cannot_materialize(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path, require_experiment=False)
    survey_dir = _write_survey(tmp_path, experiment_id="")
    preview = preview_survey_plan(project, survey_dir)
    survey_file = survey_dir / "survey.toml"
    external = tmp_path / "external-survey.toml"
    external.write_bytes(survey_file.read_bytes())
    survey_file.unlink()
    survey_file.symlink_to(external)

    with pytest.raises(SimctlError, match="single-link regular file"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()


def test_sibling_duplicate_created_during_publication_rolls_back_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)

    from runops.application.run_creation import workflow as workflow_module

    real_commit = workflow_module.commit_staged_directory
    calls = 0

    def add_duplicate_before_publish(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            _write_survey(
                tmp_path,
                experiment_id=experiment_id,
                survey_id="S20260901-scan",
                name="concurrent-duplicate",
            )
        real_commit(source, destination)

    monkeypatch.setattr(
        workflow_module,
        "commit_staged_directory",
        add_duplicate_before_publish,
    )

    with pytest.raises(SurveyMaterializationError, match=r"duplicate survey\.id"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
    assert not list(survey_dir.glob(".tmp-*"))


def test_only_explicitly_selected_point_is_materialized_and_metadata_is_frozen(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)

    result = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0002",),
    )

    assert result.created_count == 1
    assert result.reused_count == 0
    assert result.points[0].ref == "p0002"
    assert len(_run_dirs(survey_dir)) == 1
    manifest = read_manifest(result.points[0].run_dir)
    assert manifest.intent == {
        "experiment_id": experiment_id,
        "survey_id": "S20260901-scan",
        "purpose": "explore",
        "phase": "pilot",
        "information_gap": "The stable resolution range is unknown.",
        "baseline_runs": [],
        "baseline_reason": "No compatible baseline is available.",
        "created_by": "agent",
    }
    assert manifest.identity["point_id"] == result.points[0].point_id
    assert manifest.identity["plan_hash"] == preview.plan.plan_hash
    for key in (
        "condition_hash",
        "input_hash",
        "execution_hash",
        "provenance_hash",
    ):
        assert manifest.identity[key].startswith("sha256:")
    assert manifest.curation == {
        "review_status": "unreviewed",
        "reason": "",
        "reviewed_at": "",
        "reviewed_by": "",
    }
    assert manifest.storage == {"tier": "hot", "form": "full"}


def test_all_selection_is_still_rejected_by_hard_survey_budget(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(
        tmp_path,
        experiment_id=experiment_id,
        materialized=2,
    )
    preview = preview_survey_plan(project, survey_dir)

    with pytest.raises(SurveyMaterializationError, match="Survey materialization cap"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            all_points=True,
        )

    assert _run_dirs(survey_dir) == []


def test_main_phase_requires_expand_decision(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(
        tmp_path,
        experiment_id=experiment_id,
        phase="main",
    )
    preview = preview_survey_plan(project, survey_dir)

    with pytest.raises(SurveyMaterializationError, match="decision=expand"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    review_experiment(
        tmp_path,
        experiment_id,
        decision="expand",
        reason="Pilot evidence admits the bounded main phase.",
    )
    admitted = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )
    assert admitted.created_count == 1


def test_reapplying_the_same_point_reuses_its_run(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)

    first = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )
    ledger = tmp_path / ".runops" / "run-id-sequence.toml"
    sequence_before = ledger.read_bytes()
    second = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )

    assert second.created_count == 0
    assert second.reused_count == 1
    assert second.points[0].run_id == first.points[0].run_id
    assert len(_run_dirs(survey_dir)) == 1
    assert ledger.read_bytes() == sequence_before


@pytest.mark.parametrize("tamper", ["input", "provenance"])
def test_exact_point_reuse_revalidates_materialized_scientific_identity(
    tmp_path: Path,
    tamper: str,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)
    first = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )
    run_dir = first.points[0].run_dir
    if tamper == "input":
        (run_dir / "input" / "params.json").write_text(
            '{"nx": 65, "ny": 64}\n',
            encoding="utf-8",
        )
    else:
        update_manifest(
            run_dir,
            {"simulator_source": {"exe_hash": "sha256:" + "f" * 64}},
        )

    with pytest.raises(SurveyMaterializationError, match="scientific identity"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert len(_run_dirs(survey_dir)) == 1


def test_exact_point_retry_reuses_same_weakly_provenanced_materialization(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    (tmp_path / "simulators.toml").write_text(
        "[simulators.test_sim]\n"
        'adapter = "generic"\n'
        'executable = "definitely-missing-runops-solver"\n'
        'resolver_mode = "package"\n',
        encoding="utf-8",
    )
    project = load_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)
    first = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )
    first_manifest = read_manifest(first.points[0].run_dir)
    assert first_manifest.simulator_source["exe_hash"] == ""

    retried = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )

    assert retried.points[0].reused is True
    assert retried.points[0].run_id == first.points[0].run_id
    assert len(_run_dirs(survey_dir)) == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"origin": {"survey": "S20260901-other"}},
        {"intent": {"survey_id": "S20260901-other"}},
        {"intent": {"experiment_id": "E20260901-9999"}},
    ],
)
def test_reuse_fails_closed_on_inconsistent_survey_ownership(
    tmp_path: Path,
    updates: dict[str, dict[str, str]],
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)
    first = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )
    update_manifest(first.points[0].run_dir, updates)

    with pytest.raises(SurveyMaterializationError, match="inconsistent Survey owner"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert len(_run_dirs(survey_dir)) == 1


def test_exact_point_reuse_is_allowed_at_materialization_budget_limit(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path, default_materialized=1)
    experiment_id = _admit_experiment(
        tmp_path,
        materialized=1,
        active=1,
    )
    survey_dir = _write_survey(
        tmp_path,
        experiment_id=experiment_id,
        axes={"nx": [32]},
        materialized=1,
    )
    preview = preview_survey_plan(project, survey_dir)
    first = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )

    reused = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )

    assert reused.created_count == 0
    assert reused.reused_count == 1
    assert reused.points[0].run_id == first.points[0].run_id


def test_materialization_fails_closed_on_an_invalid_existing_run(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)
    invalid = tmp_path / "runs" / "legacy-broken"
    invalid.mkdir()
    (invalid / "manifest.toml").write_text("not = [valid", encoding="utf-8")

    with pytest.raises(
        SurveyMaterializationError,
        match="cannot safely account existing formal Runs",
    ):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()


def test_materialization_fails_closed_on_an_invalid_sibling_survey(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)
    invalid = tmp_path / "runs" / "broken-survey"
    invalid.mkdir()
    (invalid / "survey.toml").write_text("[survey\nnot-toml", encoding="utf-8")

    with pytest.raises(
        SurveyMaterializationError,
        match=r"cannot verify survey\.id uniqueness",
    ):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()


def test_survey_discovery_prunes_run_payload_and_transaction_trees(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    payload_run = tmp_path / "runs" / "legacy" / "R20260801-0001"
    (payload_run / "input").mkdir(parents=True)
    (payload_run / "input" / "survey.toml").write_text(
        "[not-a-managed-survey",
        encoding="utf-8",
    )
    write_manifest(
        payload_run,
        ManifestData(run={"id": "R20260801-0001", "status": "created"}),
    )
    for name in (".tmp-pending", ".delete-pending"):
        transaction = tmp_path / "runs" / name
        transaction.mkdir()
        (transaction / "survey.toml").write_text(
            "[not-a-published-survey",
            encoding="utf-8",
        )

    preview = preview_survey_plan(project, survey_dir)
    materialized = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )

    assert materialized.created_count == 1
    assert materialized.points[0].run_id.startswith("R")


def test_partial_failure_can_be_retried_without_duplicate_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(tmp_path, experiment_id=experiment_id)
    preview = preview_survey_plan(project, survey_dir)

    from runops.application import survey_materialization as module

    real_create = module.create_prepared_run
    calls = 0

    def _fail_second(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SimctlError("injected failure after the first committed Run")
        return real_create(*args, **kwargs)

    monkeypatch.setattr(module, "create_prepared_run", _fail_second)
    with pytest.raises(SimctlError, match="injected failure"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001", "p0002"),
        )

    recovered = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001", "p0002"),
    )
    assert recovered.reused_count == 1
    assert recovered.created_count == 1
    assert len(_run_dirs(survey_dir)) == 2
    sequences = sorted(
        int(point.run_id.rsplit("-", 1)[1]) for point in recovered.points
    )
    assert sequences[1] - sequences[0] == 2  # the failed reservation stays burned


def test_duplicate_effective_parameters_are_rejected(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(tmp_path)
    survey_dir = _write_survey(
        tmp_path,
        experiment_id=experiment_id,
        axes={"nx": [32, 32]},
    )
    preview = preview_survey_plan(project, survey_dir)
    assert preview.points[0].point_id == preview.points[1].point_id

    with pytest.raises(SurveyMaterializationError, match="duplicate effective"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            all_points=True,
        )

    assert _run_dirs(survey_dir) == []


def test_experiment_planned_point_cap_blocks_even_one_selection(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(
        tmp_path,
        planned=1,
        materialized=1,
        active=1,
    )
    survey_dir = _write_survey(
        tmp_path,
        experiment_id=experiment_id,
        axes={"nx": [32, 64]},
    )
    preview = preview_survey_plan(project, survey_dir)

    with pytest.raises(SurveyMaterializationError, match="max_planned_points"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )


@pytest.mark.parametrize(
    ("cap_kind", "message"),
    [
        ("survey", "Survey materialization cap"),
        ("experiment", "Experiment materialization cap"),
        ("active", "active Run WIP limit"),
    ],
)
def test_materialized_and_active_caps_include_existing_runs(
    tmp_path: Path,
    cap_kind: str,
    message: str,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(
        tmp_path,
        materialized=1 if cap_kind == "experiment" else 4,
        active=1 if cap_kind in {"experiment", "active"} else 4,
    )
    survey_dir = _write_survey(
        tmp_path,
        experiment_id=experiment_id,
        axes={"nx": [32, 64]},
        materialized=1 if cap_kind == "survey" else 4,
    )
    preview = preview_survey_plan(project, survey_dir)
    materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )

    with pytest.raises(SurveyMaterializationError, match=message):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0002",),
        )


@pytest.mark.parametrize("cap_kind", ["survey", "experiment"])
def test_core_hour_caps_are_checked_before_creation(
    tmp_path: Path,
    cap_kind: str,
) -> None:
    project = _write_project(tmp_path)
    experiment_id = _admit_experiment(
        tmp_path,
        core_hours=1.0 if cap_kind == "experiment" else 100.0,
    )
    survey_dir = _write_survey(
        tmp_path,
        experiment_id=experiment_id,
        axes={"nx": [32]},
        core_hours=1.0 if cap_kind == "survey" else 100.0,
    )
    preview = preview_survey_plan(project, survey_dir)

    with pytest.raises(SurveyMaterializationError, match="core-hour budget"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )
    assert _run_dirs(survey_dir) == []


def test_unreviewed_completed_backlog_blocks_new_materialization(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path, project_unreviewed=1)
    experiment_id = _admit_experiment(tmp_path, unreviewed=1)
    survey_dir = _write_survey(
        tmp_path,
        experiment_id=experiment_id,
        axes={"nx": [32, 64]},
    )
    preview = preview_survey_plan(project, survey_dir)
    first = materialize_survey_points(
        project,
        survey_dir,
        expected_plan_hash=preview.plan.plan_hash,
        point_refs=("p0001",),
    )
    update_manifest(first.points[0].run_dir, {"run": {"status": "completed"}})

    with pytest.raises(SurveyMaterializationError, match="unreviewed completed"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0002",),
        )


def test_project_unreviewed_cap_blocks_cross_experiment_materialization(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path, project_unreviewed=1)
    first_experiment = _admit_experiment(tmp_path)
    second_experiment = _admit_experiment(tmp_path)
    existing_id = "R20260831-0001"
    write_manifest(
        tmp_path / "runs" / "existing" / existing_id,
        ManifestData(
            run={"id": existing_id, "status": "completed"},
            job={"walltime": "01:00:00", "ntasks": 1},
            intent={
                "experiment_id": first_experiment,
                "purpose": "explore",
            },
            identity={"budget_reservation": f"run:{existing_id}"},
            curation={"review_status": "unreviewed"},
        ),
    )
    survey_dir = _write_survey(
        tmp_path,
        experiment_id=second_experiment,
        axes={"nx": [32]},
    )
    preview = preview_survey_plan(project, survey_dir)

    with pytest.raises(
        SurveyMaterializationError,
        match="project-wide unreviewed completed Run backlog",
    ):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
    assert len(list((tmp_path / "runs").rglob("manifest.toml"))) == 1


def test_project_unreviewed_cap_blocks_ownerless_materialization(
    tmp_path: Path,
) -> None:
    project = _write_project(
        tmp_path,
        require_experiment=False,
        project_unreviewed=1,
    )
    existing_id = "R20260831-0001"
    write_manifest(
        tmp_path / "runs" / "existing" / existing_id,
        ManifestData(
            run={"id": existing_id, "status": "completed"},
            job={"walltime": "01:00:00", "ntasks": 1},
            intent={"purpose": "explore"},
            identity={"budget_reservation": f"run:{existing_id}"},
            curation={"review_status": "unreviewed"},
        ),
    )
    survey_dir = _write_survey(
        tmp_path,
        experiment_id="",
        axes={"nx": [32]},
    )
    preview = preview_survey_plan(project, survey_dir)

    with pytest.raises(
        SurveyMaterializationError,
        match="project-wide unreviewed completed Run backlog",
    ):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
    assert len(list((tmp_path / "runs").rglob("manifest.toml"))) == 1


@pytest.mark.parametrize("hidden_name", [".tmp-survey", ".delete-survey"])
def test_materialization_rejects_discovery_pruned_survey_target(
    tmp_path: Path,
    hidden_name: str,
) -> None:
    project = _write_project(tmp_path, require_experiment=False)
    survey_dir = _write_survey(
        tmp_path,
        experiment_id="",
        axes={"nx": [32]},
        name=hidden_name,
    )
    preview = preview_survey_plan(project, survey_dir)

    with pytest.raises(SurveyMaterializationError, match="active project runs"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []


def test_materialization_rejects_survey_inside_formal_run(tmp_path: Path) -> None:
    project = _write_project(tmp_path, require_experiment=False)
    ancestor_id = "R20260831-0001"
    ancestor = tmp_path / "runs" / "existing" / ancestor_id
    write_manifest(
        ancestor,
        ManifestData(
            run={"id": ancestor_id, "status": "created"},
            job={"walltime": "01:00:00", "ntasks": 1},
        ),
    )
    survey_dir = _write_survey(
        tmp_path,
        experiment_id="",
        axes={"nx": [32]},
        name=f"existing/{ancestor_id}/nested-survey",
    )
    preview = preview_survey_plan(project, survey_dir)

    with pytest.raises(SurveyMaterializationError, match="active project runs"):
        materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=preview.plan.plan_hash,
            point_refs=("p0001",),
        )

    assert _run_dirs(survey_dir) == []
