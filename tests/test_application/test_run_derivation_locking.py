"""Lock-order regression tests for formal Run derivation workflows."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import tomli_w

from runops.application import run_derivation as derivation
from runops.application.experiments import create_experiment
from runops.application.run_creation import workflow as run_creation_workflow
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, write_manifest
from runops.core.run import RunInfo


class _StopAfterLockObservationError(RuntimeError):
    """Stop a derivation once both relevant locks are observable."""


def _create_source_run(project_root: Path | None, parent: Path) -> Path:
    if project_root is not None:
        (project_root / "runops.toml").write_text(
            '[project]\nname = "demo"\n', encoding="utf-8"
        )
    source = parent / "R20260901-0001"
    source.mkdir(parents=True)
    with (source / "manifest.toml").open("wb") as stream:
        tomli_w.dump(
            {
                "run": {
                    "id": "R20260901-0001",
                    "display_name": "source",
                    "status": "completed",
                },
                "origin": {"case": "demo", "survey": "", "parent_run": ""},
                "simulator": {"name": "demo", "adapter": "demo"},
                "intent": {"experiment_id": "", "purpose": "confirm"},
                "job": {"nodes": 1, "ntasks": 1, "walltime": "00:01:00"},
                "params_snapshot": {"value": 1},
            },
            stream,
        )
    return source


def _create_regeneration_project(
    project_root: Path,
    *,
    require_experiment: bool,
) -> Path:
    """Create a destination project whose case/runtime choices are observable."""
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "runops.toml").write_text(
        "[project]\n"
        f'name = "{project_root.name}"\n\n'
        "[experiments.policy]\n"
        f"require_experiment = {'true' if require_experiment else 'false'}\n",
        encoding="utf-8",
    )
    (project_root / "simulators.toml").write_text(
        "[simulators.demo]\n"
        'adapter = "generic"\n'
        'executable = "echo"\n'
        'resolver_mode = "package"\n',
        encoding="utf-8",
    )
    (project_root / "launchers.toml").write_text(
        "[launchers.slurm_srun]\n"
        'kind = "srun"\n'
        'command = "srun"\n'
        "use_slurm_ntasks = true\n",
        encoding="utf-8",
    )
    case_dir = project_root / "cases" / "demo"
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text(
        "[case]\n"
        'name = "demo"\n'
        'simulator = "demo"\n'
        'launcher = "slurm_srun"\n\n'
        "[job]\n"
        'partition = "destination"\n'
        "nodes = 1\n"
        "ntasks = 1\n"
        'walltime = "00:02:00"\n\n'
        "[params]\n"
        "value = 0\n",
        encoding="utf-8",
    )
    (project_root / "runs").mkdir()
    return project_root


def _create_reusable_managed_source(project_root: Path) -> tuple[Path, Path]:
    """Create a completed Run and matching durable identity sequence ledger."""
    date_key = date.today().strftime("%Y%m%d")
    run_id = f"R{date_key}-0001"
    (project_root / "runops.toml").write_text(
        '[project]\nname = "demo"\n', encoding="utf-8"
    )
    source = project_root / "runs" / run_id
    for name in ("input", "submit", "work", "analysis", "status"):
        (source / name).mkdir(parents=True, exist_ok=True)
    (source / "input" / "params.txt").write_text("value=1\n", encoding="utf-8")
    (source / "submit" / "job.sh").write_text(
        f"#!/bin/bash\n#SBATCH --job-name={run_id}\ncd {source}\n",
        encoding="utf-8",
    )
    manifest = ManifestData(
        run={
            "id": run_id,
            "display_name": "source",
            "status": "completed",
        },
        path={"run_dir": str(source)},
        origin={"case": "demo", "survey": "", "parent_run": ""},
        simulator={"name": "demo", "adapter": "demo"},
        simulator_source={
            "resolver_mode": "local_executable",
            "executable": "/opt/demo/bin/solver",
            "exe_hash": "sha256:" + "a" * 64,
        },
        launcher={"name": "slurm_srun"},
        job={"nodes": 1, "ntasks": 1, "walltime": "00:01:00"},
        params_snapshot={"value": 1},
        intent={"experiment_id": "", "purpose": "confirm"},
    )
    derivation.finalize_manifest_metadata(manifest, source, None)
    write_manifest(source, manifest)

    ledger = project_root / ".runops" / "run-id-sequence.toml"
    ledger.parent.mkdir(parents=True)
    with ledger.open("wb") as stream:
        tomli_w.dump(
            {"schema_version": 1, "dates": {date_key: 1}},
            stream,
        )
    return source, ledger


def _recording_context(events: list[str], label: str) -> Any:
    @contextlib.contextmanager
    def guard(_path: Path) -> Iterator[object]:
        events.append(f"enter:{label}")
        try:
            yield object()
        finally:
            events.append(f"exit:{label}")

    return guard


def _stop_after_both_locks(events: list[str]) -> Any:
    def stop(*_args: object, **_kwargs: object) -> dict[str, dict[str, str]]:
        events.append("derive")
        raise _StopAfterLockObservationError

    return stop


def test_managed_copy_clone_uses_experiment_then_source_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _create_source_run(tmp_path, tmp_path / "runs")
    events: list[str] = []
    monkeypatch.setattr(
        derivation,
        "experiment_lock",
        _recording_context(events, "experiment"),
    )
    monkeypatch.setattr(
        derivation,
        "submission_guard",
        _recording_context(events, "source"),
    )
    monkeypatch.setattr(
        derivation,
        "build_standalone_manifest_metadata",
        _stop_after_both_locks(events),
    )

    with pytest.raises(_StopAfterLockObservationError):
        derivation.clone_run(source)

    assert events == [
        "enter:experiment",
        "enter:source",
        "derive",
        "exit:source",
        "exit:experiment",
    ]


def test_extend_uses_experiment_then_source_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _create_source_run(tmp_path, tmp_path / "runs")
    events: list[str] = []
    monkeypatch.setattr(
        derivation,
        "experiment_lock",
        _recording_context(events, "experiment"),
    )
    monkeypatch.setattr(
        derivation,
        "submission_guard",
        _recording_context(events, "source"),
    )
    monkeypatch.setattr(derivation, "_load_adapter", lambda *_args: object())
    monkeypatch.setattr(
        derivation,
        "build_standalone_manifest_metadata",
        _stop_after_both_locks(events),
    )

    with pytest.raises(_StopAfterLockObservationError):
        derivation.extend_run(source)

    assert events == [
        "enter:experiment",
        "enter:source",
        "derive",
        "exit:source",
        "exit:experiment",
    ]


def test_managed_clone_reuse_keeps_sequence_ledger_byte_for_byte(
    tmp_path: Path,
) -> None:
    source, ledger = _create_reusable_managed_source(tmp_path)
    before = ledger.read_bytes()

    result = derivation.clone_run(source)

    assert result.reused is True
    assert result.run_info.run_id == source.name
    assert result.run_info.run_dir == source
    assert ledger.read_bytes() == before
    assert list((tmp_path / "runs").glob("**/manifest.toml")) == [
        source / "manifest.toml"
    ]


def test_managed_extend_reuse_keeps_sequence_ledger_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, ledger = _create_reusable_managed_source(tmp_path)
    before = ledger.read_bytes()
    monkeypatch.setattr(derivation, "_load_adapter", lambda *_args: object())

    result = derivation.extend_run(source)

    assert result.reused is True
    assert result.run_info.run_id == source.name
    assert result.run_info.run_dir == source
    assert ledger.read_bytes() == before
    assert list((tmp_path / "runs").glob("**/manifest.toml")) == [
        source / "manifest.toml"
    ]


def test_managed_clone_revalidates_parent_immediately_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _ledger = _create_reusable_managed_source(tmp_path)
    destination = tmp_path / "runs" / "concurrent-clone-parent"
    real_write_manifest = derivation.write_manifest
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
                    run={"id": "R20260831-9998", "status": "created"},
                ),
            )

    monkeypatch.setattr(derivation, "write_manifest", publish_ancestor_after_preflight)

    with pytest.raises(SimctlError, match="inside existing formal Run"):
        derivation.clone_run(
            source,
            dest_dir=destination,
            purpose="reproduce",
        )

    assert (destination / "manifest.toml").is_file()
    assert not list(destination.glob("R*"))
    assert not list(destination.glob(".tmp-*"))


def test_managed_extend_revalidates_parent_immediately_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _ledger = _create_reusable_managed_source(tmp_path)
    destination = tmp_path / "runs" / "concurrent-extend-parent"
    real_write_manifest = derivation.write_manifest
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
                    run={"id": "R20260831-9997", "status": "created"},
                ),
            )

    monkeypatch.setattr(derivation, "write_manifest", publish_ancestor_after_preflight)
    monkeypatch.setattr(derivation, "_load_adapter", lambda *_args: object())

    with pytest.raises(SimctlError, match="inside existing formal Run"):
        derivation.extend_run(
            source,
            dest_dir=destination,
            purpose="reproduce",
        )

    assert (destination / "manifest.toml").is_file()
    assert not list(destination.glob("R*"))
    assert not list(destination.glob(".tmp-*"))


def test_clone_with_overrides_releases_source_before_case_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _create_source_run(tmp_path, tmp_path / "runs")
    events: list[str] = []
    monkeypatch.setattr(
        derivation,
        "submission_guard",
        _recording_context(events, "source"),
    )

    run_info = RunInfo(
        run_id="R20260901-0002",
        run_dir=tmp_path / "runs" / "R20260901-0002",
        display_name="clone",
        params={"value": 2},
        created_at="2026-09-01T00:00:00+00:00",
    )

    def create_case_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        events.append("create")
        return SimpleNamespace(run_info=run_info, reused=False, warnings=())

    monkeypatch.setattr(derivation, "create_case_run", create_case_run)

    result = derivation.clone_run(source, overrides={"value": "2"})

    assert result.run_info == run_info
    assert events == ["enter:source", "exit:source", "create"]


def test_standalone_copy_clone_uses_only_source_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _create_source_run(None, tmp_path / "standalone")
    events: list[str] = []
    monkeypatch.setattr(
        derivation,
        "submission_guard",
        _recording_context(events, "source"),
    )

    run_info = RunInfo(
        run_id="R20260901-0002",
        run_dir=source.parent / "R20260901-0002",
        display_name="clone",
        params={"value": 1},
        created_at="2026-09-01T00:00:00+00:00",
    )

    def clone_standalone(**_kwargs: object) -> derivation.CloneRunResult:
        events.append("derive")
        return derivation.CloneRunResult(
            source_run_id="R20260901-0001",
            run_info=run_info,
        )

    def fail_experiment_lock(_path: Path) -> contextlib.AbstractContextManager[None]:
        raise AssertionError("standalone clone must not acquire Experiment lock")

    monkeypatch.setattr(derivation, "_clone_standalone_by_copy", clone_standalone)
    monkeypatch.setattr(derivation, "experiment_lock", fail_experiment_lock)

    result = derivation.clone_run(source)

    assert result.run_info == run_info
    assert events == ["enter:source", "derive", "exit:source"]


def test_external_source_to_managed_destination_obeys_experiment_policy(
    tmp_path: Path,
) -> None:
    source = _create_source_run(None, tmp_path / "external")
    project = tmp_path / "managed"
    (project / "runs").mkdir(parents=True)
    (project / "runops.toml").write_text(
        "[project]\n"
        'name = "managed"\n\n'
        "[experiments.policy]\n"
        "require_experiment = true\n",
        encoding="utf-8",
    )

    with pytest.raises(SimctlError, match="requires --experiment"):
        derivation.clone_run(source, dest_dir=project / "runs")

    assert list((project / "runs").iterdir()) == []


def test_external_source_to_managed_destination_uses_managed_publication(
    tmp_path: Path,
) -> None:
    source = _create_source_run(None, tmp_path / "external")
    project = tmp_path / "managed"
    (project / "runs").mkdir(parents=True)
    (project / "runops.toml").write_text(
        "[project]\n"
        'name = "managed"\n\n'
        "[experiments.policy]\n"
        "require_experiment = false\n",
        encoding="utf-8",
    )

    result = derivation.clone_run(source, dest_dir=project / "runs")

    assert result.run_info.run_dir.parent == project / "runs"
    assert result.run_info.run_id != source.name
    assert result.run_info.run_id.endswith("-0002")
    assert result.run_info.run_dir.is_dir()
    assert (project / ".runops" / "run-id-sequence.toml").is_file()


def test_cross_project_copy_clone_uses_destination_admission_and_namespace(
    tmp_path: Path,
) -> None:
    source_project = tmp_path / "source-project"
    (source_project / "runs").mkdir(parents=True)
    source = _create_source_run(source_project, source_project / "runs")
    # This source-side policy would reject an ownerless clone if it were still
    # (incorrectly) treated as the admission owner.
    (source_project / "runops.toml").write_text(
        "[project]\n"
        'name = "source"\n\n'
        "[experiments.policy]\n"
        "require_experiment = true\n",
        encoding="utf-8",
    )
    destination = _create_regeneration_project(
        tmp_path / "destination-project",
        require_experiment=False,
    )

    result = derivation.clone_run(source, dest_dir=destination / "runs")

    assert result.run_info.run_dir.parent == destination / "runs"
    assert result.run_info.run_id != source.name
    assert (destination / ".runops" / "run-id-sequence.toml").is_file()
    assert not (source_project / ".runops" / "run-id-sequence.toml").exists()


def test_cross_project_override_clone_regenerates_from_destination_project(
    tmp_path: Path,
) -> None:
    source_project = tmp_path / "source-project"
    (source_project / "runs").mkdir(parents=True)
    source = _create_source_run(source_project, source_project / "runs")
    # There is deliberately no source-side case/simulator/launcher config.
    destination = _create_regeneration_project(
        tmp_path / "destination-project",
        require_experiment=False,
    )

    result = derivation.clone_run(
        source,
        dest_dir=destination / "runs",
        overrides={"value": "7"},
    )

    assert result.run_info.run_dir.parent == destination / "runs"
    manifest = derivation.read_manifest(result.run_info.run_dir)
    assert manifest.params_snapshot == {"value": "7"}
    assert manifest.job["partition"] == "destination"
    assert manifest.origin["parent_run"] == source.name
    assert (destination / ".runops" / "run-id-sequence.toml").is_file()
    assert not (source_project / ".runops" / "run-id-sequence.toml").exists()


def test_external_override_clone_uses_destination_experiment_gate(
    tmp_path: Path,
) -> None:
    source = _create_source_run(None, tmp_path / "external")
    destination = _create_regeneration_project(
        tmp_path / "destination-project",
        require_experiment=True,
    )

    with pytest.raises(SimctlError, match="requires --experiment"):
        derivation.clone_run(
            source,
            dest_dir=destination / "runs",
            overrides={"value": "9"},
        )

    admitted = create_experiment(
        destination,
        title="External regenerated clone",
        question="Can an external snapshot be regenerated under destination policy?",
        intent="confirm",
        baseline_reason="The external Run is the baseline snapshot.",
        max_planned_points=1,
        max_materialized_runs=1,
        max_active_runs=1,
        max_core_hours=1.0,
        max_unreviewed_runs=1,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Stop after the regenerated clone is inspected.",),
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    result = derivation.clone_run(
        source,
        dest_dir=destination / "runs",
        overrides={"value": "9"},
        experiment_id=admitted.experiment.id,
    )

    manifest = derivation.read_manifest(result.run_info.run_dir)
    assert result.run_info.run_dir.parent == destination / "runs"
    assert manifest.intent["experiment_id"] == admitted.experiment.id
    assert manifest.intent["purpose"] == "confirm"


def test_override_clone_rolls_back_when_destination_experiment_changes_on_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _create_source_run(None, tmp_path / "external")
    destination = _create_regeneration_project(
        tmp_path / "destination-project",
        require_experiment=True,
    )
    admitted = create_experiment(
        destination,
        title="Destination publication CAS",
        question="Does the destination Experiment remain stable through publish?",
        intent="confirm",
        baseline_reason="The external Run is the baseline snapshot.",
        max_planned_points=1,
        max_materialized_runs=1,
        max_active_runs=1,
        max_core_hours=1.0,
        max_unreviewed_runs=1,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Stop after checking the publication barrier.",),
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    experiment_file = admitted.experiment.experiment_file
    real_commit = run_creation_workflow.commit_staged_directory
    commit_calls = 0

    def publish_then_edit(source_dir: Path, destination_dir: Path) -> object:
        nonlocal commit_calls
        outcome = real_commit(source_dir, destination_dir)
        commit_calls += 1
        if commit_calls == 1:
            text = experiment_file.read_text(encoding="utf-8")
            experiment_file.write_text(
                text.replace('decision = "pending"', 'decision = "expand"'),
                encoding="utf-8",
            )
        return outcome

    monkeypatch.setattr(
        run_creation_workflow,
        "commit_staged_directory",
        publish_then_edit,
    )

    with pytest.raises(SimctlError, match="changed while the Run was staged"):
        derivation.clone_run(
            source,
            dest_dir=destination / "runs",
            overrides={"value": "11"},
            experiment_id=admitted.experiment.id,
        )

    assert commit_calls == 2
    assert not list((destination / "runs").glob("**/manifest.toml"))
    assert not list((destination / "runs").glob("**/.tmp-*"))


@pytest.mark.parametrize("operation", ["clone", "extend"])
def test_managed_derivation_rolls_back_when_expiry_crosses_publication_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    source, _ledger = _create_reusable_managed_source(tmp_path)
    admitted = create_experiment(
        tmp_path,
        title="Publication barrier",
        question="Can this derivation still be admitted at publication time?",
        intent="reproduce",
        baseline_reason="The source Run is the external baseline.",
        max_planned_points=2,
        max_materialized_runs=2,
        max_active_runs=2,
        max_core_hours=10.0,
        max_unreviewed_runs=2,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Stop after testing the derived Run.",),
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    real_admission = derivation.build_standalone_manifest_metadata
    admission_calls = 0

    def expire_after_publication(*args: object, **kwargs: object) -> object:
        nonlocal admission_calls
        admission_calls += 1
        if admission_calls == 3:
            raise SimctlError("Experiment expired at publication barrier")
        return real_admission(*args, **kwargs)

    monkeypatch.setattr(
        derivation,
        "build_standalone_manifest_metadata",
        expire_after_publication,
    )
    if operation == "extend":
        monkeypatch.setattr(derivation, "_load_adapter", lambda *_args: object())

    with pytest.raises(SimctlError, match="expired at publication barrier"):
        if operation == "clone":
            derivation.clone_run(
                source,
                experiment_id=admitted.experiment.id,
                purpose="reproduce",
            )
        else:
            derivation.extend_run(
                source,
                experiment_id=admitted.experiment.id,
                purpose="reproduce",
            )

    assert admission_calls == 3
    assert list((tmp_path / "runs").glob("**/manifest.toml")) == [
        source / "manifest.toml"
    ]
    assert not list((tmp_path / "runs").glob("**/.tmp-*"))


@pytest.mark.parametrize("operation", ["clone", "extend"])
def test_managed_derivation_rejects_experiment_edit_while_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    source, _ledger = _create_reusable_managed_source(tmp_path)
    admitted = create_experiment(
        tmp_path,
        title="Publication CAS",
        question="Does admission metadata remain stable while staging?",
        intent="reproduce",
        baseline_reason="The source Run is the external baseline.",
        max_planned_points=2,
        max_materialized_runs=2,
        max_active_runs=2,
        max_core_hours=10.0,
        max_unreviewed_runs=2,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Stop after testing the derived Run.",),
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    experiment_file = admitted.experiment.experiment_file
    real_write_manifest = derivation.write_manifest
    edited = False

    def edit_experiment_after_staging(
        run_dir: Path,
        manifest: ManifestData,
        *,
        event_path: Path | None = None,
        log_event: bool = True,
    ) -> None:
        nonlocal edited
        real_write_manifest(
            run_dir,
            manifest,
            event_path=event_path,
            log_event=log_event,
        )
        if not edited and run_dir.name.startswith(".tmp-"):
            edited = True
            text = experiment_file.read_text(encoding="utf-8")
            experiment_file.write_text(
                text.replace('decision = "pending"', 'decision = "stop"'),
                encoding="utf-8",
            )

    monkeypatch.setattr(derivation, "write_manifest", edit_experiment_after_staging)
    if operation == "extend":
        monkeypatch.setattr(derivation, "_load_adapter", lambda *_args: object())

    with pytest.raises(SimctlError, match="decision"):
        if operation == "clone":
            derivation.clone_run(
                source,
                experiment_id=admitted.experiment.id,
                purpose="reproduce",
            )
        else:
            derivation.extend_run(
                source,
                experiment_id=admitted.experiment.id,
                purpose="reproduce",
            )

    assert edited is True
    assert list((tmp_path / "runs").glob("**/manifest.toml")) == [
        source / "manifest.toml"
    ]
    assert not list((tmp_path / "runs").glob("**/.tmp-*"))


def test_derivation_retains_ambiguous_paths_when_publication_rollback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _ledger = _create_reusable_managed_source(tmp_path)
    admitted = create_experiment(
        tmp_path,
        title="Rollback retention",
        question="Can an ambiguous publication be retained for recovery?",
        intent="reproduce",
        baseline_reason="The source Run is the external baseline.",
        max_planned_points=2,
        max_materialized_runs=2,
        max_active_runs=2,
        max_core_hours=10.0,
        max_unreviewed_runs=2,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Stop after testing rollback retention.",),
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    real_admission = derivation.build_standalone_manifest_metadata
    admission_calls = 0

    def expire_after_publication(*args: object, **kwargs: object) -> object:
        nonlocal admission_calls
        admission_calls += 1
        if admission_calls == 3:
            raise SimctlError("Experiment expired after publication")
        return real_admission(*args, **kwargs)

    real_commit = derivation.commit_staged_directory
    commit_calls = 0

    def fail_rollback(source_dir: Path, destination_dir: Path) -> object:
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 2:
            destination_dir.mkdir()
            (destination_dir / "concurrent-owner.txt").write_text(
                "retain me\n",
                encoding="utf-8",
            )
            raise OSError("rollback destination was concurrently replaced")
        return real_commit(source_dir, destination_dir)

    monkeypatch.setattr(
        derivation,
        "build_standalone_manifest_metadata",
        expire_after_publication,
    )
    monkeypatch.setattr(derivation, "commit_staged_directory", fail_rollback)

    with pytest.raises(SimctlError, match="rollback also failed"):
        derivation.clone_run(
            source,
            experiment_id=admitted.experiment.id,
            purpose="reproduce",
        )

    assert commit_calls == 2
    published = [
        path
        for path in (tmp_path / "runs").glob("R*")
        if path != source and (path / "manifest.toml").is_file()
    ]
    retained_staging = list((tmp_path / "runs").glob(".tmp-*"))
    assert len(published) == 1
    assert len(retained_staging) == 1
    assert (retained_staging[0] / "concurrent-owner.txt").is_file()
