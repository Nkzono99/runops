"""Tests for run_creation helpers (focused on the case→render plumbing).

These regression tests guard against the field-name mismatch between the
user-facing case.toml fields (``processes/threads/cores`` for RSC sites,
``nodes/ntasks`` for standard sites) and the renderer-internal field names
consumed by ``runops.jobgen.generator._render_script``
(``ntasks/threads_per_process/cores_per_thread`` for RSC sites).
"""

from __future__ import annotations

from pathlib import Path

from runops.core.case import ClassificationData, JobData
from runops.core.run_creation import (
    _build_job_config,
    _build_manifest_job,
    _merge_classification,
    _merge_job,
)
from runops.core.site import SiteProfile
from runops.jobgen.generator import generate_job_script


def _rsc_site() -> SiteProfile:
    return SiteProfile(name="rsc-site", resource_style="rsc")


def _standard_site() -> SiteProfile:
    return SiteProfile(name="standard-site", resource_style="standard")


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
