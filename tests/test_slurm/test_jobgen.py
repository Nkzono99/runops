"""Tests for job script generation."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

import pytest

from runops.jobgen.generator import (
    JobScriptError,
    generate_job_script,
    write_job_script,
)


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    """Create a minimal run directory with work/ subdirectory."""
    rd = tmp_path / "R20260327-0001"
    rd.mkdir()
    (rd / "work").mkdir()
    return rd


@pytest.fixture()
def job_config() -> dict[str, object]:
    """Return a valid minimal standard-mode job config."""
    return {
        "partition": "debug",
        "nodes": 1,
        "ntasks": 4,
        "walltime": "00:10:00",
    }


@pytest.fixture()
def rsc_job_config() -> dict[str, object]:
    """Return a valid rsc-mode job config."""
    return {
        "partition": "gr10451a",
        "walltime": "120:00:00",
        "ntasks": 800,
        "threads_per_process": 1,
        "cores_per_thread": 1,
    }


# ---------------------------------------------------------------------------
# Standard mode tests
# ---------------------------------------------------------------------------


class TestGenerateJobScript:
    """Tests for generate_job_script in standard mode."""

    def test_basic_generation(
        self, run_dir: Path, job_config: dict[str, object]
    ) -> None:
        path = generate_job_script(run_dir, job_config, "srun ./solver input.toml")
        assert path.exists()
        assert path.name == "job.sh"
        assert path.parent.name == "submit"

        content = path.read_text()
        assert content.startswith("#!/bin/bash\n")
        assert "#SBATCH -p debug" in content
        assert "#SBATCH --nodes=1" in content
        assert "#SBATCH --ntasks=4" in content
        assert "#SBATCH -t 00:10:00" in content
        assert "srun ./solver input.toml" in content

    def test_job_name_from_run_id(
        self, run_dir: Path, job_config: dict[str, object]
    ) -> None:
        path = generate_job_script(
            run_dir, job_config, "srun ./solver", run_id="R20260327-0001"
        )
        content = path.read_text()
        assert "#SBATCH -J R20260327-0001" in content

    def test_custom_job_name(
        self, run_dir: Path, job_config: dict[str, object]
    ) -> None:
        job_config["job_name"] = "my-custom-name"
        path = generate_job_script(run_dir, job_config, "srun ./solver")
        content = path.read_text()
        assert "#SBATCH -J my-custom-name" in content

    def test_default_job_name(
        self, run_dir: Path, job_config: dict[str, object]
    ) -> None:
        path = generate_job_script(run_dir, job_config, "srun ./solver")
        content = path.read_text()
        assert "#SBATCH -J runops-job" in content

    def test_output_and_error_paths(
        self, run_dir: Path, job_config: dict[str, object]
    ) -> None:
        path = generate_job_script(run_dir, job_config, "srun ./solver")
        content = path.read_text()
        work = str(run_dir / "work")
        assert f"#SBATCH --output={work}" in content
        assert f"#SBATCH --error={work}" in content

    def test_extra_sbatch_directives(
        self, run_dir: Path, job_config: dict[str, object]
    ) -> None:
        path = generate_job_script(
            run_dir,
            job_config,
            "srun ./solver",
            extra_sbatch=["--mem=8G", "--exclusive"],
        )
        content = path.read_text()
        assert "#SBATCH --mem=8G" in content
        assert "#SBATCH --exclusive" in content

    def test_module_loads(self, run_dir: Path, job_config: dict[str, object]) -> None:
        path = generate_job_script(
            run_dir,
            job_config,
            "srun ./solver",
            modules=["gcc/12.0", "openmpi/4.1"],
        )
        content = path.read_text()
        assert "module load gcc/12.0 openmpi/4.1" in content

    def test_extra_env_vars(self, run_dir: Path, job_config: dict[str, object]) -> None:
        path = generate_job_script(
            run_dir,
            job_config,
            "srun ./solver",
            extra_env={"OMP_NUM_THREADS": "4"},
        )
        content = path.read_text()
        assert "export OMP_NUM_THREADS=4" in content

    def test_cd_to_run_dir(self, run_dir: Path, job_config: dict[str, object]) -> None:
        path = generate_job_script(run_dir, job_config, "srun ./solver")
        content = path.read_text()
        assert f"cd {run_dir}" in content

    def test_shell_fragments_are_quoted(self, tmp_path: Path) -> None:
        """Generated shell fragments quote values that may contain spaces."""
        run_dir = tmp_path / "project with spaces" / "R20260327-0001"
        (run_dir / "work").mkdir(parents=True)

        path = generate_job_script(
            run_dir,
            {
                "partition": "debug",
                "nodes": 1,
                "ntasks": 4,
                "walltime": "00:10:00",
            },
            "srun ./solver",
            modules=["gcc/12.0", "my module/1"],
            extra_env={"RUNOPS_LABEL": "hello world"},
        )
        content = path.read_text()

        assert "module load gcc/12.0 'my module/1'" in content
        assert "export RUNOPS_LABEL='hello world'" in content
        assert f"cd {shlex.quote(str(run_dir))}" in content

    def test_invalid_env_name_raises(
        self, run_dir: Path, job_config: dict[str, object]
    ) -> None:
        """Environment variable names are identifiers, not raw shell text."""
        with pytest.raises(JobScriptError, match="Invalid environment variable"):
            generate_job_script(
                run_dir,
                job_config,
                "srun ./solver",
                extra_env={"BAD-NAME": "value"},
            )

    def test_executable_bit(self, run_dir: Path, job_config: dict[str, object]) -> None:
        path = generate_job_script(run_dir, job_config, "srun ./solver")
        if os.name == "nt":
            pytest.skip("Windows does not expose POSIX execute bits reliably")
        assert path.stat().st_mode & 0o100  # owner execute bit

    def test_missing_walltime_raises(self, run_dir: Path) -> None:
        with pytest.raises(JobScriptError, match="walltime"):
            generate_job_script(
                run_dir,
                {"partition": "debug", "ntasks": 4},
                "srun ./solver",
            )

    def test_no_partition_omits_directive(self, run_dir: Path) -> None:
        """Partition is optional (can be set at submit time with -qn)."""
        path = generate_job_script(
            run_dir,
            {"walltime": "01:00:00", "ntasks": 4},
            "srun ./solver",
        )
        content = path.read_text()
        assert "#SBATCH -p" not in content

    def test_creates_submit_dir(
        self, tmp_path: Path, job_config: dict[str, object]
    ) -> None:
        rd = tmp_path / "new_run"
        rd.mkdir()
        path = generate_job_script(rd, job_config, "srun ./solver")
        assert path.parent.is_dir()
        assert path.parent.name == "submit"

    def test_setup_commands(self, run_dir: Path, job_config: dict[str, object]) -> None:
        """Setup commands appear before the exec line."""
        path = generate_job_script(
            run_dir,
            job_config,
            "srun ./solver",
            setup_commands=["cp input/* .", "preinp"],
        )
        content = path.read_text()
        assert "cp input/* ." in content
        assert "preinp" in content
        # Setup should come before exec
        setup_idx = content.index("cp input/*")
        exec_idx = content.index("srun ./solver")
        assert setup_idx < exec_idx

    def test_version_commands(
        self, run_dir: Path, job_config: dict[str, object]
    ) -> None:
        """Version capture commands appear before the exec line."""
        path = generate_job_script(
            run_dir,
            job_config,
            "srun ./solver",
            version_commands=[
                "( solver --version ) > SIMULATOR_VERSION.txt 2>&1 || true",
            ],
        )
        content = path.read_text()
        assert "# Runtime metadata" in content
        assert "SIMULATOR_VERSION.txt" in content
        version_idx = content.index("SIMULATOR_VERSION.txt")
        exec_idx = content.index("srun ./solver")
        assert version_idx < exec_idx

    def test_post_commands(self, run_dir: Path, job_config: dict[str, object]) -> None:
        """Post commands appear after the main command, without exec prefix."""
        path = generate_job_script(
            run_dir,
            job_config,
            "srun ./solver",
            post_commands=["date", "echo done"],
        )
        content = path.read_text()
        assert "date" in content
        assert "echo done" in content
        # Main command should NOT have exec prefix when post_commands exist
        assert "exec srun" not in content

    def test_optional_nodes_ntasks(self, run_dir: Path) -> None:
        """nodes and ntasks are optional and omitted from SBATCH if absent."""
        config = {"partition": "debug", "walltime": "01:00:00"}
        path = generate_job_script(run_dir, config, "srun ./solver")
        content = path.read_text()
        assert "#SBATCH -p debug" in content
        assert "--nodes" not in content
        assert "--ntasks" not in content

    def test_rsc_resource_style(self, run_dir: Path) -> None:
        """resource_style='rsc' emits --rsc instead of --ntasks."""
        config = {"partition": "gr10451a", "walltime": "120:00:00", "ntasks": 32}
        path = generate_job_script(
            run_dir,
            config,
            "srun ./mpiemses3D plasma.inp",
            resource_style="rsc",
            stdout_format="stdout.%J.log",
            stderr_format="stderr.%J.log",
        )
        content = path.read_text()
        assert "#SBATCH --rsc p=32:t=1:c=1" in content
        assert "#SBATCH --ntasks" not in content
        assert "#SBATCH -o stdout.%J.log" in content
        assert "#SBATCH -e stderr.%J.log" in content


# ---------------------------------------------------------------------------
# RSC mode tests
# ---------------------------------------------------------------------------


class TestRscModeJobScript:
    """Tests for generate_job_script in rsc mode."""

    def test_rsc_directive(
        self, run_dir: Path, rsc_job_config: dict[str, object]
    ) -> None:
        path = generate_job_script(
            run_dir,
            rsc_job_config,
            "srun ./mpiemses3D plasma.inp",
            resource_style="rsc",
        )
        content = path.read_text()
        assert "#SBATCH --rsc p=800:t=1:c=1" in content
        assert "--nodes" not in content

    def test_rsc_partition_and_walltime(
        self, run_dir: Path, rsc_job_config: dict[str, object]
    ) -> None:
        path = generate_job_script(
            run_dir,
            rsc_job_config,
            "srun ./solver",
            resource_style="rsc",
        )
        content = path.read_text()
        assert "#SBATCH -p gr10451a" in content
        assert "#SBATCH -t 120:00:00" in content

    def test_rsc_with_threads_and_cores(self, run_dir: Path) -> None:
        config: dict[str, object] = {
            "partition": "gr10451a",
            "ntasks": 400,
            "threads_per_process": 2,
            "cores_per_thread": 2,
            "walltime": "24:00:00",
        }
        path = generate_job_script(
            run_dir,
            config,
            "srun ./solver",
            resource_style="rsc",
        )
        content = path.read_text()
        assert "#SBATCH --rsc p=400:t=2:c=2" in content

    def test_rsc_cores_gt_threads(self, run_dir: Path) -> None:
        """c > t for more memory per process."""
        config: dict[str, object] = {
            "partition": "gr10451a",
            "ntasks": 200,
            "threads_per_process": 1,
            "cores_per_thread": 4,
            "walltime": "48:00:00",
        }
        path = generate_job_script(
            run_dir,
            config,
            "srun ./solver",
            resource_style="rsc",
        )
        content = path.read_text()
        assert "#SBATCH --rsc p=200:t=1:c=4" in content

    def test_rsc_with_memory(self, run_dir: Path) -> None:
        """memory (m=) appears in --rsc directive when specified."""
        config: dict[str, object] = {
            "partition": "gr10451a",
            "ntasks": 4,
            "threads_per_process": 8,
            "cores_per_thread": 8,
            "memory": "8G",
            "walltime": "24:00:00",
        }
        path = generate_job_script(
            run_dir,
            config,
            "srun ./solver",
            resource_style="rsc",
        )
        content = path.read_text()
        assert "#SBATCH --rsc p=4:t=8:c=8:m=8G" in content

    def test_rsc_with_gpus(self, run_dir: Path) -> None:
        """GPU (g=) appears in --rsc directive when specified."""
        config: dict[str, object] = {
            "partition": "gr10451a",
            "ntasks": 4,
            "threads_per_process": 1,
            "cores_per_thread": 1,
            "gpus": 2,
            "walltime": "24:00:00",
        }
        path = generate_job_script(
            run_dir,
            config,
            "srun ./solver",
            resource_style="rsc",
        )
        content = path.read_text()
        assert "#SBATCH --rsc p=4:t=1:c=1:g=2" in content

    def test_rsc_with_memory_and_gpus(self, run_dir: Path) -> None:
        """Both m= and g= appear when both specified."""
        config: dict[str, object] = {
            "partition": "gr10451a",
            "ntasks": 8,
            "threads_per_process": 4,
            "cores_per_thread": 4,
            "memory": "16G",
            "gpus": 1,
            "walltime": "48:00:00",
        }
        path = generate_job_script(
            run_dir,
            config,
            "srun ./solver",
            resource_style="rsc",
        )
        content = path.read_text()
        assert "#SBATCH --rsc p=8:t=4:c=4:m=16G:g=1" in content

    def test_rsc_no_memory_no_gpus(
        self, run_dir: Path, rsc_job_config: dict[str, object]
    ) -> None:
        """Without memory/gpus, --rsc stays p:t:c only."""
        path = generate_job_script(
            run_dir,
            rsc_job_config,
            "srun ./solver",
            resource_style="rsc",
        )
        content = path.read_text()
        assert "#SBATCH --rsc p=800:t=1:c=1\n" in content

    def test_rsc_with_modules(
        self, run_dir: Path, rsc_job_config: dict[str, object]
    ) -> None:
        path = generate_job_script(
            run_dir,
            rsc_job_config,
            "srun ./solver",
            modules=["intel/2023.2", "intelmpi/2023.2"],
            resource_style="rsc",
        )
        content = path.read_text()
        assert "module load intel/2023.2 intelmpi/2023.2" in content


# ---------------------------------------------------------------------------
# Pre/post commands tests
# ---------------------------------------------------------------------------


class TestPrePostCommands:
    """Tests for setup_commands and post_commands."""

    def test_setup_commands(self, run_dir: Path, job_config: dict[str, object]) -> None:
        path = generate_job_script(
            run_dir,
            job_config,
            "srun ./solver input.toml",
            setup_commands=["echo 'starting'", "rm -f *.h5"],
        )
        content = path.read_text()
        assert "echo 'starting'" in content
        assert "rm -f *.h5" in content
        # Setup commands should appear before exec
        setup_idx = content.index("rm -f")
        exec_idx = content.index("srun ./solver")
        assert setup_idx < exec_idx

    def test_post_commands(self, run_dir: Path, job_config: dict[str, object]) -> None:
        path = generate_job_script(
            run_dir,
            job_config,
            "srun ./solver input.toml",
            post_commands=["mypython plot.py ./", "mypython plot_hole.py ./"],
        )
        content = path.read_text()
        assert "mypython plot.py ./" in content
        assert "mypython plot_hole.py ./" in content
        # exec should not be used when post_commands exist
        assert "exec srun" not in content
        # Main command still present
        assert "srun ./solver input.toml" in content

    def test_modules_from_job_config(self, run_dir: Path) -> None:
        config: dict[str, object] = {
            "partition": "debug",
            "nodes": 1,
            "ntasks": 4,
            "walltime": "00:10:00",
            "modules": ["intel/2023.2", "hdf5/1.12"],
        }
        path = generate_job_script(run_dir, config, "srun ./solver")
        content = path.read_text()
        assert "module load intel/2023.2 hdf5/1.12" in content

    def test_pre_commands_from_job_config(self, run_dir: Path) -> None:
        config: dict[str, object] = {
            "partition": "debug",
            "nodes": 1,
            "ntasks": 4,
            "walltime": "00:10:00",
            "pre_commands": [
                "if [ -f ./plasma.preinp ]; then\n    preinp\nfi",
            ],
        }
        path = generate_job_script(run_dir, config, "srun ./solver")
        content = path.read_text()
        assert "preinp" in content

    def test_full_emses_style(self, run_dir: Path) -> None:
        """Test generating a script similar to the user's real EMSES setup."""
        config: dict[str, object] = {
            "partition": "gr10451a",
            "walltime": "120:00:00",
            "ntasks": 800,
            "threads_per_process": 1,
            "cores_per_thread": 1,
            "modules": [
                "intel/2023.2",
                "intelmpi/2023.2",
                "hdf5/1.12.2_intel-2023.2-impi",
                "fftw/3.3.10_intel-2022.3-impi",
            ],
            "pre_commands": [
                "if [ -f ./plasma.preinp ]; then\n    preinp\nfi",
                "export EMSES_DEBUG=no",
                "rm -f *_0000.h5",
            ],
            "post_commands": [
                "mypython plot.py ./",
                "mypython plot_hole.py ./",
            ],
        }
        path = generate_job_script(
            run_dir,
            config,
            "srun ./mpiemses3D plasma.inp",
            run_id="R20260327-0001",
            resource_style="rsc",
        )
        content = path.read_text()
        # SBATCH directives
        assert "#SBATCH --rsc p=800:t=1:c=1" in content
        assert "#SBATCH -p gr10451a" in content
        assert "#SBATCH -t 120:00:00" in content
        # Modules
        assert "module load intel/2023.2" in content
        assert "module load" in content
        # Pre-commands (merged from job_config into setup_commands)
        assert "preinp" in content
        assert "EMSES_DEBUG=no" in content
        assert "rm -f *_0000.h5" in content
        # Main command (no exec because post_commands exist)
        assert "srun ./mpiemses3D plasma.inp" in content
        # Post-commands
        assert "mypython plot.py ./" in content
        assert "mypython plot_hole.py ./" in content


# ---------------------------------------------------------------------------
# write_job_script
# ---------------------------------------------------------------------------


class TestWriteJobScript:
    """Tests for write_job_script."""

    def test_writes_content(self, run_dir: Path) -> None:
        content = "#!/bin/bash\necho hello\n"
        path = write_job_script(run_dir, content)
        assert path.read_text() == content

    def test_creates_submit_dir(self, tmp_path: Path) -> None:
        rd = tmp_path / "R0001"
        rd.mkdir()
        path = write_job_script(rd, "#!/bin/bash\n")
        assert path.exists()
        assert path.parent.name == "submit"

    def test_overwrites_existing(self, run_dir: Path) -> None:
        write_job_script(run_dir, "old content")
        path = write_job_script(run_dir, "new content")
        assert path.read_text() == "new content"
