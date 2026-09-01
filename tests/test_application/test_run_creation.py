"""Tests for run_creation helpers (focused on the case→render plumbing).

These regression tests guard against the field-name mismatch between the
user-facing case.toml fields (``processes/threads/cores`` for RSC sites,
``nodes/ntasks`` for standard sites) and the renderer-internal field names
consumed by ``runops.jobgen.generator._render_script``
(``ntasks/threads_per_process/cores_per_thread`` for RSC sites).
"""

from __future__ import annotations

import errno
import json
import os
import shlex
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft7Validator

from runops.adapters.generic import GenericAdapter
from runops.application.run_creation import (
    _build_job_config,
    _build_manifest,
    _build_manifest_job,
    _merge_classification,
    _merge_job,
    create_case_run,
    create_prepared_run,
    create_survey_runs,
    find_equivalent_completed_run,
    plan_survey_runs,
)
from runops.application.run_creation import staging as staging_module
from runops.application.run_creation import workflow as run_creation_module
from runops.core.case import CaseData, ClassificationData, JobData
from runops.core.exceptions import SimctlError
from runops.core.manifest import (
    ManifestData,
    read_manifest,
    update_manifest,
    write_manifest,
)
from runops.core.project import ProjectConfig, load_project
from runops.core.run import RunInfo
from runops.core.site import SiteProfile
from runops.jobgen.generator import generate_job_script
from runops.launchers.srun import SrunLauncher


def _rsc_site() -> SiteProfile:
    return SiteProfile(name="rsc-site", resource_style="rsc")


def _standard_site() -> SiteProfile:
    return SiteProfile(name="standard-site", resource_style="standard")


def _transactional_project(root: Path) -> ProjectConfig:
    return ProjectConfig(
        name="test-project",
        description="",
        root_dir=root,
        simulators={
            "generic": {
                "adapter": "generic",
                "executable": "echo",
                "resolver_mode": "local_executable",
            }
        },
        launchers={},
    )


def _transactional_case(case_dir: Path) -> CaseData:
    case_dir.mkdir(parents=True, exist_ok=True)
    return CaseData(
        name="base_case",
        simulator="generic",
        launcher="srun",
        job=JobData(partition="debug", nodes=1, ntasks=1, walltime="00:10:00"),
        params={"nx": 64},
        case_dir=case_dir,
        raw={
            "case": {
                "name": "base_case",
                "simulator": "generic",
                "launcher": "srun",
            }
        },
    )


def _transactional_launcher() -> SrunLauncher:
    return SrunLauncher("srun", "srun", use_slurm_ntasks=True)


def _assert_no_run_or_staging_dirs(parent_dir: Path) -> None:
    assert sorted(path.name for path in parent_dir.iterdir()) == []


def _identity_manifest(
    run_dir: Path,
    run_id: str,
    *,
    experiment_id: str = "E20260901-0001",
    survey_id: str = "",
    point_id: str = "",
    resolver_mode: str = "local_executable",
    executable: str = "/opt/simulator/bin/solver",
    exe_hash: str = "sha256:" + "a" * 64,
    git_commit: str = "",
    git_dirty: Any = False,
    git_state_observed: Any = False,
) -> ManifestData:
    input_dir = run_dir / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "config.toml").write_text("value = 1\n", encoding="utf-8")
    manifest = ManifestData(
        run={"id": run_id, "status": "created"},
        path={"run_dir": str(run_dir)},
        simulator={"name": "generic", "adapter": "generic"},
        launcher={"name": "srun", "config": {"kind": "srun"}},
        simulator_source={
            "resolver_mode": resolver_mode,
            "executable": executable,
            "exe_hash": exe_hash,
            "git_commit": git_commit,
            "git_dirty": git_dirty,
            "git_state_observed": git_state_observed,
            "package_version": "",
        },
        job={
            "scheduler": "slurm",
            "job_id": "",
            "submitted_at": "",
            "partition": "debug",
            "nodes": 1,
            "ntasks": 1,
            "walltime": "00:10:00",
        },
        params_snapshot={"nx": 64},
        intent={
            "experiment_id": experiment_id,
            "survey_id": survey_id,
            "purpose": "explore",
        },
    )
    metadata = {"identity": {"point_id": point_id}} if point_id else None
    run_creation_module.finalize_manifest_metadata(
        manifest,
        run_dir,
        metadata,
        site=_standard_site(),
    )
    return manifest


def test_equivalent_reuse_requires_the_same_durable_owner(tmp_path: Path) -> None:
    existing_dir = tmp_path / "runs" / "R20260901-0001"
    existing = _identity_manifest(
        existing_dir,
        "R20260901-0001",
        experiment_id="E20260901-0001",
    )
    existing.run["status"] = "completed"
    write_manifest(existing_dir, existing)
    candidate = _identity_manifest(
        tmp_path / "candidate",
        "R20260901-0002",
        experiment_id="E20260901-0002",
    )

    with pytest.raises(SimctlError, match="different Experiment/Survey owner"):
        find_equivalent_completed_run(tmp_path, candidate)

    candidate.intent["purpose"] = "validate"
    assert find_equivalent_completed_run(tmp_path, candidate) is None


def test_survey_reuse_requires_the_same_point_edge(tmp_path: Path) -> None:
    existing_dir = tmp_path / "runs" / "survey-a" / "R20260901-0001"
    point_id = "sha256:" + "b" * 64
    existing = _identity_manifest(
        existing_dir,
        "R20260901-0001",
        survey_id="S20260901-a",
        point_id=point_id,
    )
    existing.run["status"] = "completed"
    write_manifest(existing_dir, existing)
    candidate = _identity_manifest(
        tmp_path / "candidate",
        "R20260901-0002",
        survey_id="S20260901-a",
        point_id=point_id,
    )

    equivalent = find_equivalent_completed_run(tmp_path, candidate)

    assert equivalent is not None
    assert equivalent[0] == existing_dir


def test_scientific_reuse_requires_content_addressed_executable_provenance(
    tmp_path: Path,
) -> None:
    existing_dir = tmp_path / "runs" / "R20260901-0001"
    existing = _identity_manifest(
        existing_dir,
        "R20260901-0001",
        executable="/a/solver",
        exe_hash="",
    )
    existing.run["status"] = "completed"
    write_manifest(existing_dir, existing)
    same_path = _identity_manifest(
        tmp_path / "same-path-candidate",
        "R20260901-0002",
        executable="/a/solver",
        exe_hash="",
    )
    same_basename = _identity_manifest(
        tmp_path / "other-path-candidate",
        "R20260901-0003",
        executable="/b/solver",
        exe_hash="",
    )

    assert existing.identity["scientific_hash"] == same_path.identity["scientific_hash"]
    assert (
        existing.identity["scientific_hash"]
        != same_basename.identity["scientific_hash"]
    )
    assert not run_creation_module.materialized_scientific_identity_is_valid(
        existing_dir,
        existing,
    )
    assert find_equivalent_completed_run(tmp_path, same_path) is None
    assert find_equivalent_completed_run(tmp_path, same_basename) is None


def test_scientific_reuse_rejects_unidentified_dirty_local_source(
    tmp_path: Path,
) -> None:
    existing_dir = tmp_path / "runs" / "R20260901-0001"
    existing = _identity_manifest(
        existing_dir,
        "R20260901-0001",
        resolver_mode="local_source",
        git_commit="abc1234",
        git_dirty=True,
        git_state_observed=True,
    )
    existing.run["status"] = "completed"
    write_manifest(existing_dir, existing)
    candidate = _identity_manifest(
        tmp_path / "candidate",
        "R20260901-0002",
        resolver_mode="local_source",
        git_commit="abc1234",
        git_dirty=True,
        git_state_observed=True,
    )

    assert find_equivalent_completed_run(tmp_path, candidate) is None


def test_scientific_reuse_rejects_unobserved_clean_local_source_candidate(
    tmp_path: Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate = _identity_manifest(
        candidate_dir,
        "R20260901-0002",
        resolver_mode="local_source",
        git_commit="abc1234",
        git_dirty=False,
        git_state_observed=False,
    )

    assert not run_creation_module.materialized_scientific_identity_is_valid(
        candidate_dir,
        candidate,
    )
    assert find_equivalent_completed_run(tmp_path, candidate) is None


def test_scientific_reuse_rejects_existing_unobserved_local_source(
    tmp_path: Path,
) -> None:
    existing_dir = tmp_path / "runs" / "R20260901-0001"
    existing = _identity_manifest(
        existing_dir,
        "R20260901-0001",
        resolver_mode="local_source",
        git_commit="abc1234",
        git_dirty=False,
        git_state_observed=True,
    )
    existing.run["status"] = "completed"
    existing.simulator_source["git_state_observed"] = False
    write_manifest(existing_dir, existing)
    candidate = _identity_manifest(
        tmp_path / "candidate",
        "R20260901-0002",
        resolver_mode="local_source",
        git_commit="abc1234",
        git_dirty=False,
        git_state_observed=True,
    )

    assert find_equivalent_completed_run(tmp_path, candidate) is None


def test_scientific_reuse_allows_observed_clean_local_source(tmp_path: Path) -> None:
    existing_dir = tmp_path / "runs" / "R20260901-0001"
    existing = _identity_manifest(
        existing_dir,
        "R20260901-0001",
        resolver_mode="local_source",
        git_commit="abc1234",
        git_dirty=False,
        git_state_observed=True,
    )
    existing.run["status"] = "completed"
    write_manifest(existing_dir, existing)
    candidate = _identity_manifest(
        tmp_path / "candidate",
        "R20260901-0002",
        resolver_mode="local_source",
        git_commit="abc1234",
        git_dirty=False,
        git_state_observed=True,
    )

    equivalent = find_equivalent_completed_run(tmp_path, candidate)

    assert equivalent is not None
    assert equivalent[0] == existing_dir


@pytest.mark.parametrize(
    ("git_dirty", "git_state_observed"),
    [
        (False, "true"),
        ("false", True),
    ],
)
def test_scientific_reuse_rejects_non_boolean_git_observation_state(
    tmp_path: Path,
    git_dirty: Any,
    git_state_observed: Any,
) -> None:
    run_dir = tmp_path / "candidate"
    manifest = _identity_manifest(
        run_dir,
        "R20260901-0001",
        resolver_mode="local_source",
        git_commit="abc1234",
        git_dirty=git_dirty,
        git_state_observed=git_state_observed,
    )

    assert not run_creation_module.materialized_scientific_identity_is_valid(
        run_dir,
        manifest,
    )


def test_scientific_reuse_rejects_conflicting_resolver_modes(tmp_path: Path) -> None:
    run_dir = tmp_path / "candidate"
    manifest = _identity_manifest(
        run_dir,
        "R20260901-0001",
        resolver_mode="package",
    )
    manifest.simulator["resolver_mode"] = "local_source"

    assert not run_creation_module.materialized_scientific_identity_is_valid(
        run_dir,
        manifest,
    )


@pytest.mark.parametrize("tamper", ["input", "params", "provenance"])
def test_scientific_reuse_revalidates_existing_materialized_identity(
    tmp_path: Path,
    tamper: str,
) -> None:
    project = ProjectConfig(
        name="reuse-integrity",
        description="",
        root_dir=tmp_path,
        simulators={
            "generic": {
                "adapter": "generic",
                "executable": "/bin/echo",
                "resolver_mode": "local_executable",
            }
        },
        launchers={
            "srun": {
                "kind": "srun",
                "command": "srun",
                "use_slurm_ntasks": True,
            }
        },
    )
    case_dir = tmp_path / "cases" / "base_case"
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text(
        "[case]\n"
        'name = "base_case"\n'
        'simulator = "generic"\n'
        'launcher = "srun"\n\n'
        "[job]\n"
        'partition = "debug"\n'
        "nodes = 1\n"
        "ntasks = 1\n"
        'walltime = "00:10:00"\n\n'
        "[params]\n"
        "nx = 64\n",
        encoding="utf-8",
    )
    first = create_case_run(project, "base_case")
    update_manifest(first.run_info.run_dir, {"run": {"status": "completed"}})

    if tamper == "input":
        (first.run_info.run_dir / "input" / "params.json").write_text(
            '{"nx": 65}\n', encoding="utf-8"
        )
    elif tamper == "params":
        update_manifest(first.run_info.run_dir, {"params_snapshot": {"nx": 65}})
    else:
        update_manifest(
            first.run_info.run_dir,
            {"simulator_source": {"exe_hash": "sha256:" + "f" * 64}},
        )

    second = create_case_run(project, "base_case")

    assert second.reused is False
    assert second.run_info.run_id != first.run_info.run_id
    assert len(list((tmp_path / "runs").glob("**/manifest.toml"))) == 2


def test_manifest_metadata_cannot_override_derived_identity(tmp_path: Path) -> None:
    run_dir = tmp_path / "staging"
    (run_dir / "input").mkdir(parents=True)
    manifest = ManifestData(
        simulator={"name": "generic"},
        simulator_source={"exe_hash": "sha256:" + "a" * 64},
        launcher={"name": "srun"},
        job={"scheduler": "slurm"},
        params_snapshot={"nx": 64},
    )

    with pytest.raises(SimctlError, match="cannot override derived identity"):
        run_creation_module.finalize_manifest_metadata(
            manifest,
            run_dir,
            {"identity": {"scientific_hash": "sha256:" + "0" * 64}},
            site=_standard_site(),
        )


def test_manifest_metadata_cannot_pre_review_a_new_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "staging"
    (run_dir / "input").mkdir(parents=True)
    manifest = ManifestData(
        simulator={"name": "generic"},
        simulator_source={"exe_hash": "sha256:" + "a" * 64},
        launcher={"name": "srun"},
        job={"scheduler": "slurm"},
        params_snapshot={"nx": 64},
        curation={
            "review_status": "reviewed",
            "reviewed_at": "2026-09-01T00:00:00+00:00",
            "reviewed_by": "caller",
            "reason": "pre-authorized",
        },
    )

    run_creation_module.finalize_manifest_metadata(
        manifest,
        run_dir,
        {
            "curation": {
                "review_status": "reviewed",
                "reviewed_at": "2026-09-01T00:00:00+00:00",
                "reviewed_by": "caller",
                "reason": "pre-authorized",
            }
        },
        site=_standard_site(),
    )

    assert manifest.curation == {
        "review_status": "unreviewed",
        "reviewed_at": "",
        "reviewed_by": "",
        "reason": "",
    }


def test_execution_hash_is_independent_of_run_paths_and_output_paths(
    tmp_path: Path,
) -> None:
    site_a = SiteProfile(
        name="same-site",
        resource_style="standard",
        modules=["compiler/1", "mpi/1"],
        stdout_format=str(tmp_path / "first" / "%j.out"),
        stderr_format=str(tmp_path / "first" / "%j.err"),
    )
    site_b = SiteProfile(
        name="same-site",
        resource_style="standard",
        modules=["compiler/1", "mpi/1"],
        stdout_format=str(tmp_path / "second" / "%j.out"),
        stderr_format=str(tmp_path / "second" / "%j.err"),
    )
    first = _identity_manifest(tmp_path / "first", "R20260901-0001")
    second = _identity_manifest(tmp_path / "second", "R20260901-0002")
    first.simulator_source["executable"] = "/opt/first/bin/solver"
    second.simulator_source["executable"] = "/different/root/bin/solver"
    (tmp_path / "first" / "submit").mkdir()
    (tmp_path / "second" / "submit").mkdir()
    (tmp_path / "first" / "submit" / "job.sh").write_text(
        f"cd {tmp_path / 'first'}\n#SBATCH -o {tmp_path / 'first' / '%j.out'}\n",
        encoding="utf-8",
    )
    (tmp_path / "second" / "submit" / "job.sh").write_text(
        f"cd {tmp_path / 'second'}\n#SBATCH -o {tmp_path / 'second' / '%j.out'}\n",
        encoding="utf-8",
    )

    run_creation_module.finalize_manifest_metadata(
        first,
        tmp_path / "first",
        None,
        site=site_a,
    )
    run_creation_module.finalize_manifest_metadata(
        second, tmp_path / "second", None, site=site_b
    )

    assert first.identity["scientific_hash"] == second.identity["scientific_hash"]
    assert first.identity["execution_hash"] == second.identity["execution_hash"]


@pytest.mark.parametrize("changed", ["site", "job", "launcher"])
def test_execution_hash_changes_with_canonical_execution_conditions(
    tmp_path: Path,
    changed: str,
) -> None:
    base_dir = tmp_path / "base"
    changed_dir = tmp_path / changed
    base = _identity_manifest(base_dir, "R20260901-0001")
    candidate = _identity_manifest(changed_dir, "R20260901-0002")
    base_site = SiteProfile(name="site-a", modules=["mpi/1"])
    candidate_site = base_site
    if changed == "site":
        candidate_site = SiteProfile(name="site-b", modules=["mpi/1"])
    elif changed == "job":
        candidate.job["partition"] = "production"
    else:
        candidate.launcher["config"] = {
            "kind": "srun",
            "extra_options": ["--cpu-bind=cores"],
        }

    run_creation_module.finalize_manifest_metadata(
        base,
        base_dir,
        None,
        site=base_site,
    )
    run_creation_module.finalize_manifest_metadata(
        candidate,
        changed_dir,
        None,
        site=candidate_site,
    )

    assert base.identity["scientific_hash"] == candidate.identity["scientific_hash"]
    assert base.identity["execution_hash"] != candidate.identity["execution_hash"]


def test_standalone_scientific_reuse_does_not_advance_sequence(
    tmp_path: Path,
) -> None:
    project = ProjectConfig(
        name="reuse",
        description="",
        root_dir=tmp_path,
        simulators={
            "generic": {
                "adapter": "generic",
                "executable": "/bin/echo",
                "resolver_mode": "local_executable",
            }
        },
        launchers={
            "srun": {
                "kind": "srun",
                "command": "srun",
                "use_slurm_ntasks": True,
            }
        },
    )
    case_dir = tmp_path / "cases" / "base_case"
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text(
        "[case]\n"
        'name = "base_case"\n'
        'simulator = "generic"\n'
        'launcher = "srun"\n\n'
        "[job]\n"
        'partition = "debug"\n'
        "nodes = 1\n"
        "ntasks = 1\n"
        'walltime = "00:10:00"\n\n'
        "[params]\n"
        "nx = 64\n",
        encoding="utf-8",
    )

    first = create_case_run(project, "base_case")
    update_manifest(first.run_info.run_dir, {"run": {"status": "completed"}})
    ledger = tmp_path / ".runops" / "run-id-sequence.toml"
    before = ledger.read_bytes()

    second = create_case_run(project, "base_case")

    assert second.reused is True
    assert second.run_info.run_id == first.run_info.run_id
    assert ledger.read_bytes() == before
    assert len(list((tmp_path / "runs").glob("**/manifest.toml"))) == 1


def test_case_creation_does_not_hard_reuse_unresolved_executable(
    tmp_path: Path,
) -> None:
    project = ProjectConfig(
        name="weak-provenance",
        description="",
        root_dir=tmp_path,
        simulators={
            "generic": {
                "adapter": "generic",
                "executable": "/compute-only/bin/solver",
                "resolver_mode": "local_executable",
            }
        },
        launchers={
            "srun": {
                "kind": "srun",
                "command": "srun",
                "use_slurm_ntasks": True,
            }
        },
    )
    case_dir = tmp_path / "cases" / "base_case"
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text(
        "[case]\n"
        'name = "base_case"\n'
        'simulator = "generic"\n'
        'launcher = "srun"\n\n'
        "[job]\n"
        'partition = "debug"\n'
        "nodes = 1\n"
        "ntasks = 1\n"
        'walltime = "00:10:00"\n\n'
        "[params]\n"
        "nx = 64\n",
        encoding="utf-8",
    )

    first = create_case_run(project, "base_case")
    update_manifest(first.run_info.run_dir, {"run": {"status": "completed"}})
    second = create_case_run(project, "base_case")

    first_manifest = read_manifest(first.run_info.run_dir)
    assert first_manifest.simulator_source["exe_hash"] == ""
    assert second.reused is False
    assert second.run_info.run_id != first.run_info.run_id
    assert len(list((tmp_path / "runs").glob("**/manifest.toml"))) == 2


def _scandir_path(target: int | str | bytes | os.PathLike[str]) -> Path:
    if isinstance(target, int):
        return Path(os.readlink(f"/proc/self/fd/{target}"))
    return Path(target)


def test_directory_content_hash_rejects_file_path_replacement_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "input"
    root.mkdir()
    target = root / "config.toml"
    target.write_text("value = 1\n", encoding="utf-8")
    replacement = tmp_path / "replacement.toml"
    replacement.write_text("value = 2\n", encoding="utf-8")
    real_read = run_creation_module.os.read
    replaced = False

    def replace_at_eof(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        chunk = real_read(descriptor, size)
        if not chunk and not replaced:
            replacement.replace(target)
            replaced = True
        return chunk

    monkeypatch.setattr(run_creation_module.os, "read", replace_at_eof)

    with pytest.raises(SimctlError, match="changed while being hashed"):
        run_creation_module.directory_content_hash(root)


@pytest.mark.parametrize("change", ["add", "remove"])
def test_directory_content_hash_rejects_entry_set_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    root = tmp_path / "input"
    root.mkdir()
    (root / "first.toml").write_text("value = 1\n", encoding="utf-8")
    removable = root / "second.toml"
    if change == "remove":
        removable.write_text("value = 2\n", encoding="utf-8")
    real_scandir = run_creation_module.os.scandir
    root_scans = 0

    def mutate_before_rescan(
        target: int | str | bytes | os.PathLike[str],
    ) -> os.ScandirIterator[str]:
        nonlocal root_scans
        if _scandir_path(target) == root:
            root_scans += 1
            if root_scans == 2:
                if change == "add":
                    (root / "added.toml").write_text("added = true\n", encoding="utf-8")
                else:
                    removable.unlink()
        return real_scandir(target)

    monkeypatch.setattr(run_creation_module.os, "scandir", mutate_before_rescan)

    with pytest.raises(SimctlError, match="entry set changed"):
        run_creation_module.directory_content_hash(root)


def test_directory_content_hash_rejects_directory_identity_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "input"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (nested / "config.toml").write_text("value = 1\n", encoding="utf-8")
    displaced = tmp_path / "displaced"
    real_scandir = run_creation_module.os.scandir
    nested_scans = 0

    def replace_before_rescan(
        target: int | str | bytes | os.PathLike[str],
    ) -> os.ScandirIterator[str]:
        nonlocal nested_scans
        if _scandir_path(target) == nested:
            nested_scans += 1
            if nested_scans == 2:
                nested.rename(displaced)
                nested.mkdir()
                (nested / "config.toml").write_text("value = 1\n", encoding="utf-8")
        return real_scandir(target)

    monkeypatch.setattr(run_creation_module.os, "scandir", replace_before_rescan)

    with pytest.raises(SimctlError, match="directory changed"):
        run_creation_module.directory_content_hash(root)


def test_staged_directory_commit_is_noreplace_and_fsyncs_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = tmp_path / ".tmp-R20260901-0001"
    staging.mkdir()
    (staging / "manifest.toml").write_text("[run]\n", encoding="utf-8")
    final = tmp_path / "R20260901-0001"
    fsynced: list[Path] = []
    monkeypatch.setattr(staging_module, "_fsync_directory", fsynced.append)

    staging_module.commit_staged_directory(staging, final)

    assert final.is_dir()
    assert not staging.exists()
    assert fsynced == [tmp_path]

    second_staging = tmp_path / ".tmp-R20260901-0002"
    second_staging.mkdir()
    with pytest.raises(FileExistsError):
        staging_module.commit_staged_directory(second_staging, final)
    assert second_staging.is_dir()
    assert (final / "manifest.toml").is_file()


def test_staged_directory_commit_rolls_back_when_parent_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = tmp_path / ".tmp-R20260901-0001"
    staging.mkdir()
    (staging / "manifest.toml").write_text("[run]\n", encoding="utf-8")
    final = tmp_path / "R20260901-0001"

    def fail_fsync(_path: Path) -> None:
        raise OSError("injected parent fsync failure")

    monkeypatch.setattr(staging_module, "_fsync_directory", fail_fsync)

    with pytest.raises(SimctlError, match="rename was rolled back"):
        staging_module.commit_staged_directory(staging, final)

    assert staging.is_dir()
    assert (staging / "manifest.toml").is_file()
    assert not final.exists()


def test_staged_directory_commit_reports_destination_owned_durability_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = tmp_path / ".tmp-R20260901-0001"
    staging.mkdir()
    (staging / "manifest.toml").write_text("[run]\n", encoding="utf-8")
    final = tmp_path / "R20260901-0001"
    real_rename = staging_module._rename_noreplace
    rename_calls = 0

    def fail_fsync(_path: Path) -> None:
        raise OSError("injected parent fsync failure")

    def fail_rollback(source: Path, destination: Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError("injected rollback failure")
        real_rename(source, destination)

    monkeypatch.setattr(staging_module, "_fsync_directory", fail_fsync)
    monkeypatch.setattr(staging_module, "_rename_noreplace", fail_rollback)

    with pytest.warns(staging_module.MoveDurabilityWarning):
        outcome = staging_module.commit_staged_directory(staging, final)

    assert outcome.durability_confirmed is False
    assert "durability is unconfirmed" in outcome.warning
    assert final.is_dir()
    assert (final / "manifest.toml").is_file()
    assert not staging.exists()


def test_directory_move_rejects_cross_filesystem_copy_delete_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"

    class CrossDeviceRename:
        argtypes: object = None
        restype: object = None

        def __call__(self, *_args: object) -> int:
            staging_module.ctypes.set_errno(errno.EXDEV)
            return -1

    class FakeLibc:
        renameat2 = CrossDeviceRename()

    monkeypatch.setattr(
        staging_module.ctypes, "CDLL", lambda *_args, **_kwargs: FakeLibc()
    )

    with pytest.raises(SimctlError, match="same filesystem"):
        staging_module.move_directory_noreplace(source, destination)

    assert source.is_dir()
    assert not destination.exists()


def test_legacy_create_survey_runs_fails_closed(tmp_path: Path) -> None:
    """Old agent integrations cannot silently materialize every candidate."""
    with pytest.raises(SimctlError, match="no longer expands every candidate"):
        create_survey_runs(_transactional_project(tmp_path), tmp_path / "survey")


class TestBuildJobConfigRsc:
    """``_build_job_config`` translates JobData → renderer dict for RSC sites."""

    def test_emits_renderer_field_names(self) -> None:
        job = JobData(
            partition="hpa",
            walltime="120:00:00",
            processes=1600,
            threads=2,
            cores=4,
        )
        config = _build_job_config(job, _rsc_site())
        assert config["partition"] == "hpa"
        assert config["walltime"] == "120:00:00"
        # The renderer (RSC mode) reads these exact key names.
        assert config["ntasks"] == 1600
        assert config["threads_per_process"] == 2
        assert config["cores_per_thread"] == 4
        # Standard-mode keys must NOT leak through in RSC mode.
        assert "nodes" not in config

    def test_includes_optional_memory_and_gpus(self) -> None:
        job = JobData(
            partition="hpa",
            walltime="120:00:00",
            processes=8,
            memory="8G",
            gpus=2,
        )
        config = _build_job_config(job, _rsc_site())
        assert config["memory"] == "8G"
        assert config["gpus"] == 2

    def test_omits_unset_memory_and_gpus(self) -> None:
        job = JobData(partition="hpa", walltime="01:00:00", processes=1)
        config = _build_job_config(job, _rsc_site())
        assert "memory" not in config
        assert "gpus" not in config


class TestBuildJobConfigStandard:
    """``_build_job_config`` keeps the standard ``nodes``/``ntasks`` shape."""

    def test_emits_nodes_and_ntasks(self) -> None:
        job = JobData(
            partition="debug",
            walltime="00:30:00",
            nodes=2,
            ntasks=8,
        )
        config = _build_job_config(job, _standard_site())
        assert config["nodes"] == 2
        assert config["ntasks"] == 8
        # RSC-only keys must not leak into standard mode.
        assert "threads_per_process" not in config
        assert "cores_per_thread" not in config

    def test_none_site_falls_back_to_standard(self) -> None:
        job = JobData(partition="debug", walltime="00:30:00", nodes=1, ntasks=4)
        config = _build_job_config(job, None)
        assert config["nodes"] == 1
        assert config["ntasks"] == 4


class TestBuildManifestJob:
    """``_build_manifest_job`` records user-facing field names per site mode."""

    def test_rsc_site_uses_user_facing_fields(self) -> None:
        job = JobData(
            partition="hpa",
            walltime="120:00:00",
            processes=1600,
            threads=2,
            cores=4,
            memory="8G",
            gpus=1,
        )
        result = _build_manifest_job(job, _rsc_site())
        assert result["scheduler"] == "slurm"
        assert result["job_id"] == ""
        assert result["partition"] == "hpa"
        assert result["walltime"] == "120:00:00"
        assert result["processes"] == 1600
        assert result["threads"] == 2
        assert result["cores"] == 4
        assert result["memory"] == "8G"
        assert result["gpus"] == 1
        # Don't pollute the manifest with standard-mode keys.
        assert "nodes" not in result
        assert "ntasks" not in result

    def test_standard_site_uses_nodes_and_ntasks(self) -> None:
        job = JobData(partition="debug", walltime="00:30:00", nodes=2, ntasks=8)
        result = _build_manifest_job(job, _standard_site())
        assert result["nodes"] == 2
        assert result["ntasks"] == 8
        assert "processes" not in result


class EmptyProvenanceAdapter(GenericAdapter):
    """Valid adapter that has no provenance values to report."""

    def collect_provenance(self, runtime_info: dict[str, Any]) -> dict[str, Any]:
        return {}


class InvalidGitObservationAdapter(GenericAdapter):
    """Adapter returning truthy strings instead of observed boolean state."""

    def collect_provenance(self, runtime_info: dict[str, Any]) -> dict[str, Any]:
        return {
            "git_commit": "abc1234",
            "git_dirty": "false",
            "git_state_observed": "true",
        }


def test_build_manifest_emits_canonical_required_contract(tmp_path: Path) -> None:
    run_info = RunInfo(
        run_id="R20260710-0001",
        run_dir=tmp_path / "runs" / "R20260710-0001",
        display_name="baseline",
        created_at="2026-07-10T12:00:00+09:00",
        params={"nx": 64},
    )
    manifest = _build_manifest(
        run_info,
        _transactional_case(tmp_path / "cases" / "base_case"),
        _transactional_project(tmp_path),
        {
            "resolver_mode": "local_executable",
            "executable": "/nonexistent/solver",
        },
        EmptyProvenanceAdapter(),
        _standard_site(),
    )

    raw = manifest.to_dict()

    assert set(raw) == {
        "run",
        "path",
        "origin",
        "classification",
        "simulator",
        "launcher",
        "simulator_source",
        "job",
        "variation",
        "params_snapshot",
        "files",
    }
    assert raw["origin"]["case"] == "base_case"
    assert raw["simulator"]["name"] == "generic"
    assert raw["launcher"]["name"] == "srun"
    assert raw["job"]["scheduler"] == "slurm"
    assert raw["job"]["job_id"] == ""
    assert raw["job"]["submitted_at"] == ""
    assert raw["simulator_source"] == {
        "resolver_mode": "local_executable",
        "source_repo": "",
        "git_commit": "",
        "git_dirty": False,
        "git_state_observed": False,
        "build_command": "",
        "executable": "/nonexistent/solver",
        "exe_hash": "",
        "package_version": "",
    }

    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "manifest.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft7Validator(schema).validate(raw)


def test_build_manifest_normalizes_invalid_git_observation_types(
    tmp_path: Path,
) -> None:
    run_info = RunInfo(
        run_id="R20260710-0001",
        run_dir=tmp_path / "runs" / "R20260710-0001",
        display_name="baseline",
        created_at="2026-07-10T12:00:00+09:00",
        params={"nx": 64},
    )

    manifest = _build_manifest(
        run_info,
        _transactional_case(tmp_path / "cases" / "base_case"),
        _transactional_project(tmp_path),
        {
            "resolver_mode": "local_source",
            "source_repo": "/source",
            "executable": "/source/solver",
        },
        InvalidGitObservationAdapter(),
        _standard_site(),
    )

    assert manifest.simulator_source["git_dirty"] is False
    assert manifest.simulator_source["git_state_observed"] is False


class TestSurveyOverrides:
    """Survey metadata overrides are partial overlays on the base case."""

    def test_classification_tags_only_preserves_model_fields(self) -> None:
        base = ClassificationData(
            model="plasma",
            submodel="beam",
            tags=["baseline"],
        )
        override = ClassificationData(tags=["scan"])
        result = _merge_classification(base, override, {"tags": ["scan"]})
        assert result == ClassificationData(
            model="plasma",
            submodel="beam",
            tags=["scan"],
        )

    def test_classification_explicit_empty_tags_clears_tags(self) -> None:
        base = ClassificationData(model="plasma", tags=["baseline"])
        override = ClassificationData(tags=[])
        result = _merge_classification(base, override, {"tags": []})
        assert result.tags == []
        assert result.model == "plasma"

    def test_job_walltime_only_preserves_partition_and_size(self) -> None:
        base = JobData(
            partition="compute",
            nodes=2,
            ntasks=16,
            walltime="01:00:00",
        )
        override = JobData(walltime="02:30:00")
        result = _merge_job(base, override, {"walltime": "02:30:00"})
        assert result.partition == "compute"
        assert result.nodes == 2
        assert result.ntasks == 16
        assert result.walltime == "02:30:00"

    def test_job_qos_only_preserves_partition(self) -> None:
        base = JobData(partition="compute", walltime="01:00:00")
        override = JobData(qos="debug")
        result = _merge_job(base, override, {"qos": "debug"})
        assert result.partition == "compute"
        assert result.walltime == "01:00:00"
        assert result.qos == "debug"

    def test_job_list_fields_replace_when_present(self) -> None:
        base = JobData(
            partition="compute",
            qos="normal",
            modules=["base"],
            pre_commands=["echo before"],
        )
        override = JobData(
            modules=["extra"],
            pre_commands=[],
        )
        result = _merge_job(
            base,
            override,
            {"modules": ["extra"], "pre_commands": []},
        )
        assert result.partition == "compute"
        assert result.qos == "normal"
        assert result.modules == ["extra"]
        assert result.pre_commands == []

    def test_empty_scalar_values_keep_case_values(self) -> None:
        classification = ClassificationData(
            model="plasma",
            submodel="beam",
            tags=["baseline"],
        )
        job = JobData(
            partition="compute",
            walltime="03:00:00",
            qos="normal",
        )
        assert (
            _merge_classification(
                classification,
                ClassificationData(model="", submodel=""),
                {"model": "", "submodel": ""},
            )
            == classification
        )
        assert (
            _merge_job(
                job,
                JobData(partition="", walltime="", qos=""),
                {"partition": "", "walltime": "", "qos": ""},
            )
            == job
        )

    def test_empty_raw_sections_keep_case_values(self) -> None:
        classification = ClassificationData(
            model="plasma",
            submodel="beam",
            tags=["baseline"],
        )
        job = JobData(partition="compute", walltime="03:00:00")
        assert (
            _merge_classification(
                classification,
                ClassificationData(model="ignored"),
                {},
            )
            == classification
        )
        assert _merge_job(job, JobData(partition="ignored"), {}) == job

    def test_plan_survey_runs_reuses_partial_override_logic(
        self, tmp_path: Path
    ) -> None:
        """Planning and real sweep creation share the same merged case state."""
        (tmp_path / "runops.toml").write_text(
            '[project]\nname = "test-project"\n',
            encoding="utf-8",
        )
        (tmp_path / "simulators.toml").write_text(
            "[simulators.generic]\n"
            'adapter = "generic"\n'
            'executable = "echo"\n'
            'resolver_mode = "package"\n',
            encoding="utf-8",
        )
        (tmp_path / "launchers.toml").write_text(
            '[launchers.srun]\nkind = "srun"\ncommand = "srun"\n',
            encoding="utf-8",
        )
        project = load_project(tmp_path)
        case_dir = tmp_path / "cases" / "base_case"
        case_dir.mkdir(parents=True)
        (case_dir / "case.toml").write_text(
            "[case]\n"
            'name = "base_case"\n'
            'simulator = "generic"\n'
            'launcher = "srun"\n'
            "\n"
            "[classification]\n"
            'model = "base"\n'
            'tags = ["baseline"]\n'
            "\n"
            "[job]\n"
            'partition = "compute"\n'
            "nodes = 2\n"
            "ntasks = 16\n"
            'walltime = "01:00:00"\n'
            "\n"
            "[params]\n"
            "nx = 64\n"
        )
        survey_dir = tmp_path / "runs" / "survey"
        survey_dir.mkdir(parents=True)
        (survey_dir / "survey.toml").write_text(
            "[survey]\n"
            'id = "S20260327-test"\n'
            'base_case = "base_case"\n'
            'simulator = "generic"\n'
            'launcher = "srun"\n'
            "\n"
            "[classification]\n"
            'tags = ["scan"]\n'
            "\n"
            "[axes]\n"
            "nx = [32, 64]\n"
            "\n"
            "[job]\n"
            'walltime = "02:30:00"\n'
        )

        plan = plan_survey_runs(project, survey_dir)

        assert len(plan.combinations) == 2
        assert plan.variation_keys == ("nx",)
        assert plan.effective_case.classification.model == "base"
        assert plan.effective_case.classification.tags == ["scan"]
        assert plan.effective_case.job.partition == "compute"
        assert plan.effective_case.job.nodes == 2
        assert plan.effective_case.job.ntasks == 16
        assert plan.effective_case.job.walltime == "02:30:00"


class RenderFailAdapter(GenericAdapter):
    """Adapter that fails after writing a partial input file."""

    def render_inputs(self, case_data: dict[str, object], run_dir: Path) -> list[str]:
        (run_dir / "input" / "partial.txt").write_text("partial")
        raise RuntimeError("render failed")


class ResolveFailAdapter(GenericAdapter):
    """Adapter that fails after successful input rendering."""

    def resolve_runtime(
        self,
        simulator_config: dict[str, object],
        resolver_mode: str,
    ) -> dict[str, object]:
        raise RuntimeError("resolve failed")


class UnsafeInputAdapter(GenericAdapter):
    """Adapter that attempts to commit an unsafe input-tree entry."""

    def __init__(self, unsafe_kind: str) -> None:
        self.unsafe_kind = unsafe_kind

    def render_inputs(self, case_data: dict[str, object], run_dir: Path) -> list[str]:
        rendered = super().render_inputs(case_data, run_dir)
        nested = run_dir / "input" / "nested"
        nested.mkdir()
        unsafe = nested / "unsafe"
        if self.unsafe_kind == "symlink":
            unsafe.symlink_to("/etc/hosts")
        else:
            os.mkfifo(unsafe)
        return rendered


class TestTransactionalRunCreation:
    """``create_prepared_run`` commits only fully prepared runs."""

    def test_success_commits_final_run_dir_and_rewrites_script_paths(
        self,
        tmp_path: Path,
    ) -> None:
        project = _transactional_project(tmp_path)
        case_data = _transactional_case(tmp_path / "cases" / "base_case")
        parent_dir = tmp_path / "runs" / "base_case"

        result = create_prepared_run(
            parent_dir=parent_dir,
            case_data=case_data,
            project=project,
            adapter=GenericAdapter(),
            launcher=_transactional_launcher(),
            site=_standard_site(),
            existing_ids=set(),
        )

        run_dir = result.run_info.run_dir
        assert run_dir.is_dir()
        assert run_dir.name.startswith("R")
        assert not any(path.name.startswith(".tmp-") for path in parent_dir.iterdir())
        job_sh = (run_dir / "submit" / "job.sh").read_text()
        assert f"cd {shlex.quote(str(run_dir))}" in job_sh
        assert str(run_dir / "input" / "params.json") in job_sh
        assert ".tmp-" not in job_sh

    def test_package_mode_uses_project_venv_executable_for_generated_job(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = _transactional_project(tmp_path)
        project.simulators["generic"]["resolver_mode"] = "package"
        project.simulators["generic"]["executable"] = "solver"
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        venv_executable = venv_bin / "solver"
        venv_executable.write_text("#!/bin/sh\n")
        (venv_bin / "activate").write_text("# activate\n")
        monkeypatch.setattr(
            "runops.adapters.generic.shutil.which",
            lambda _name: "/opt/system/bin/solver",
        )
        case_data = _transactional_case(tmp_path / "cases" / "base_case")
        parent_dir = tmp_path / "runs" / "base_case"

        result = create_prepared_run(
            parent_dir=parent_dir,
            case_data=case_data,
            project=project,
            adapter=GenericAdapter(),
            launcher=_transactional_launcher(),
            site=_standard_site(),
            existing_ids=set(),
        )

        job_sh = (result.run_info.run_dir / "submit" / "job.sh").read_text()
        assert str(venv_executable) in job_sh
        assert "/opt/system/bin/solver" not in job_sh
        assert result.warnings == (
            "package executable 'solver' resolved to /opt/system/bin/solver "
            f"before job setup; using project virtualenv executable {venv_executable} "
            "because job.sh activates .venv.",
        )

    def test_stale_existing_ids_skip_existing_final_dir(
        self,
        tmp_path: Path,
    ) -> None:
        project = _transactional_project(tmp_path)
        case_data = _transactional_case(tmp_path / "cases" / "base_case")
        parent_dir = tmp_path / "runs" / "base_case"
        today = date.today().strftime("%Y%m%d")
        stale_collision = parent_dir / f"R{today}-0001"
        stale_collision.mkdir(parents=True)

        result = create_prepared_run(
            parent_dir=parent_dir,
            case_data=case_data,
            project=project,
            adapter=GenericAdapter(),
            launcher=_transactional_launcher(),
            site=_standard_site(),
            existing_ids=set(),
        )

        assert result.run_info.run_id == f"R{today}-0002"
        assert result.run_info.run_dir.is_dir()
        assert not any(path.name.startswith(".tmp-") for path in parent_dir.iterdir())

    def test_commit_collision_retries_with_next_run_id(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = _transactional_project(tmp_path)
        case_data = _transactional_case(tmp_path / "cases" / "base_case")
        parent_dir = tmp_path / "runs" / "base_case"
        today = date.today().strftime("%Y%m%d")
        collisions: list[str] = []
        real_write_manifest = run_creation_module.write_manifest

        def write_manifest_with_collision(*args: object, **kwargs: object) -> None:
            real_write_manifest(*args, **kwargs)
            manifest = args[1]
            run_id = str(manifest.run["id"])
            if not collisions:
                (parent_dir / run_id).mkdir(parents=True)
                collisions.append(run_id)

        monkeypatch.setattr(
            run_creation_module,
            "write_manifest",
            write_manifest_with_collision,
        )

        result = create_prepared_run(
            parent_dir=parent_dir,
            case_data=case_data,
            project=project,
            adapter=GenericAdapter(),
            launcher=_transactional_launcher(),
            site=_standard_site(),
            existing_ids=set(),
        )

        assert collisions == [f"R{today}-0001"]
        assert result.run_info.run_id == f"R{today}-0002"
        assert result.run_info.run_dir.is_dir()
        assert (parent_dir / f"R{today}-0001").is_dir()
        assert not any(path.name.startswith(".tmp-") for path in parent_dir.iterdir())

    def test_copy_failure_cleans_staging_and_final_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = _transactional_project(tmp_path)
        case_data = _transactional_case(tmp_path / "cases" / "base_case")
        parent_dir = tmp_path / "runs" / "base_case"

        def fail_copy(case_dir: Path, input_dir: Path) -> None:
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "partial.txt").write_text("partial")
            raise RuntimeError("copy failed")

        monkeypatch.setattr(run_creation_module, "_copy_case_files", fail_copy)

        with pytest.raises(RuntimeError, match="copy failed"):
            create_prepared_run(
                parent_dir=parent_dir,
                case_data=case_data,
                project=project,
                adapter=GenericAdapter(),
                launcher=_transactional_launcher(),
                site=_standard_site(),
                existing_ids=set(),
            )

        _assert_no_run_or_staging_dirs(parent_dir)

    def test_render_failure_cleans_staging_and_final_dir(
        self,
        tmp_path: Path,
    ) -> None:
        project = _transactional_project(tmp_path)
        case_data = _transactional_case(tmp_path / "cases" / "base_case")
        parent_dir = tmp_path / "runs" / "base_case"

        with pytest.raises(RuntimeError, match="render failed"):
            create_prepared_run(
                parent_dir=parent_dir,
                case_data=case_data,
                project=project,
                adapter=RenderFailAdapter(),
                launcher=_transactional_launcher(),
                site=_standard_site(),
                existing_ids=set(),
            )

        _assert_no_run_or_staging_dirs(parent_dir)

    def test_resolve_failure_cleans_staging_and_final_dir(
        self,
        tmp_path: Path,
    ) -> None:
        project = _transactional_project(tmp_path)
        case_data = _transactional_case(tmp_path / "cases" / "base_case")
        parent_dir = tmp_path / "runs" / "base_case"

        with pytest.raises(RuntimeError, match="resolve failed"):
            create_prepared_run(
                parent_dir=parent_dir,
                case_data=case_data,
                project=project,
                adapter=ResolveFailAdapter(),
                launcher=_transactional_launcher(),
                site=_standard_site(),
                existing_ids=set(),
            )

        _assert_no_run_or_staging_dirs(parent_dir)

    @pytest.mark.parametrize(
        ("unsafe_kind", "message"),
        [
            ("symlink", "symbolic links"),
            ("fifo", "only regular files"),
        ],
    )
    def test_unsafe_rendered_input_is_rejected_before_publication(
        self,
        tmp_path: Path,
        unsafe_kind: str,
        message: str,
    ) -> None:
        project = _transactional_project(tmp_path)
        case_data = _transactional_case(tmp_path / "cases" / "base_case")
        parent_dir = tmp_path / "runs" / "base_case"

        with pytest.raises(SimctlError, match=message):
            create_prepared_run(
                parent_dir=parent_dir,
                case_data=case_data,
                project=project,
                adapter=UnsafeInputAdapter(unsafe_kind),
                launcher=_transactional_launcher(),
                site=_standard_site(),
                existing_ids=set(),
            )

        _assert_no_run_or_staging_dirs(parent_dir)


class TestEndToEndRsc:
    """End-to-end: case JobData → ``_build_job_config`` → ``generate_job_script``.

    Reproduces the historical regression where ``case.toml`` had
    ``processes = 1600`` but the rendered ``job.sh`` ended up with
    ``--rsc p=1:t=1:c=1`` because the renderer keys never matched the dict.
    """

    def test_rsc_mode_renders_processes_and_threads(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "R20260407-9999"
        (run_dir / "work").mkdir(parents=True)

        job = JobData(
            partition="hpa",
            walltime="120:00:00",
            processes=1600,
            threads=4,
            cores=4,
        )
        site = _rsc_site()
        config = _build_job_config(job, site)

        path = generate_job_script(
            run_dir,
            config,
            "srun ./mpiemses3D plasma.toml",
            site=site,
            run_id="R20260407-9999",
        )
        content = path.read_text()
        assert "#SBATCH -p hpa" in content
        assert "#SBATCH --rsc p=1600:t=4:c=4" in content
        assert "#SBATCH -t 120:00:00" in content
        assert "#SBATCH -J R20260407-9999" in content
        # Make sure the standard-mode directives aren't accidentally emitted.
        assert "#SBATCH --ntasks=" not in content
        assert "#SBATCH --nodes=" not in content

    def test_standard_mode_renders_nodes_and_ntasks(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "R20260407-9998"
        (run_dir / "work").mkdir(parents=True)

        job = JobData(partition="debug", walltime="00:10:00", nodes=2, ntasks=8)
        site = _standard_site()
        config = _build_job_config(job, site)

        path = generate_job_script(
            run_dir,
            config,
            "srun ./solver",
            site=site,
            run_id="R20260407-9998",
        )
        content = path.read_text()
        assert "#SBATCH --nodes=2" in content
        assert "#SBATCH --ntasks=8" in content
        # RSC directive must be absent in standard mode.
        assert "--rsc" not in content
