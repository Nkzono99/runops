"""Tests for run_creation helpers (focused on the case→render plumbing).

These regression tests guard against the field-name mismatch between the
user-facing case.toml fields (``processes/threads/cores`` for RSC sites,
``nodes/ntasks`` for standard sites) and the renderer-internal field names
consumed by ``runops.jobgen.generator._render_script``
(``ntasks/threads_per_process/cores_per_thread`` for RSC sites).
"""

from __future__ import annotations

import shlex
from datetime import date
from pathlib import Path

import pytest

from runops.adapters.generic import GenericAdapter
from runops.application.run_creation import (
    _build_job_config,
    _build_manifest,
    _build_manifest_job,
    _merge_classification,
    _merge_job,
    create_prepared_run,
    plan_survey_runs,
)
from runops.application.run_creation import workflow as run_creation_module
from runops.core.case import CaseData, ClassificationData, JobData
from runops.core.project import ProjectConfig
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
        GenericAdapter(),
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
        project = ProjectConfig(
            name="test-project",
            description="",
            root_dir=tmp_path,
            simulators={
                "generic": {
                    "adapter": "generic",
                    "executable": "echo",
                    "resolver_mode": "package",
                }
            },
            launchers={"srun": {"type": "srun"}},
        )
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
