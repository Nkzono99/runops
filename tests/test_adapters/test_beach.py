"""Tests for the BEACH adapter — contract tests for all abstract methods."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from runops.adapters.contrib.beach import BeachAdapter

SAMPLE_BEACH_TOML = """\
[sim]
dt = 2.0e-8
batch_count = 100
max_step = 10000
field_solver = "fmm"
rng_seed = 12345

[[particles.species]]
source_mode = "reservoir_face"
number_density_cm3 = 5.0
temperature_ev = 10.0

[mesh]
mode = "template"

[[mesh.templates]]
kind = "plane"
size_x = 1.0
size_y = 1.0
nx = 20
ny = 20

[output]
write_files = true
dir = "outputs/latest"
"""


@pytest.fixture()
def adapter() -> BeachAdapter:
    """Return a fresh BeachAdapter instance."""
    return BeachAdapter()


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    """Create a minimal run directory structure."""
    for sub in ("input", "work", "analysis", "status", "submit"):
        (tmp_path / sub).mkdir()
    return tmp_path


@pytest.fixture()
def case_dir(tmp_path: Path) -> Path:
    """Create a case directory with a beach_template.toml."""
    cdir = tmp_path / "case_beach"
    cdir.mkdir()
    (cdir / "beach_template.toml").write_text(SAMPLE_BEACH_TOML)
    return cdir


@pytest.fixture()
def case_data(case_dir: Path) -> dict[str, Any]:
    """Sample BEACH case data."""
    return {
        "case": {
            "name": "periodic2_basic",
            "simulator": "beach",
            "launcher": "srun",
            "case_dir": str(case_dir),
        },
        "params": {
            "sim.batch_count": 200,
            "sim.dt": 1.0e-7,
        },
    }


# ===================================================================
# 1. name
# ===================================================================


class TestName:
    def test_name(self, adapter: BeachAdapter) -> None:
        assert adapter.name == "beach"


class TestKnowledgeSources:
    def test_includes_cookbook_patterns(self) -> None:
        sources = BeachAdapter.knowledge_sources()
        assert "beach" in sources
        patterns = sources["beach"]
        assert "cookbook/index.toml" in patterns
        assert "cookbook/**/*.toml" in patterns
        assert "cookbook/**/*.md" in patterns


# ===================================================================
# 2. render_inputs
# ===================================================================


class TestRenderInputs:
    def test_renders_beach_toml(
        self, adapter: BeachAdapter, run_dir: Path, case_data: dict[str, Any]
    ) -> None:
        created = adapter.render_inputs(case_data, run_dir)
        assert "input/beach.toml" in created
        assert (run_dir / "input" / "beach.toml").exists()

    def test_applies_overrides(
        self, adapter: BeachAdapter, run_dir: Path, case_data: dict[str, Any]
    ) -> None:
        adapter.render_inputs(case_data, run_dir)
        import tomli

        with open(run_dir / "input" / "beach.toml", "rb") as f:
            config = tomli.load(f)
        assert config["sim"]["batch_count"] == 200
        assert config["sim"]["dt"] == 1.0e-7

    def test_sets_output_dir(
        self, adapter: BeachAdapter, run_dir: Path, case_data: dict[str, Any]
    ) -> None:
        adapter.render_inputs(case_data, run_dir)
        import tomli

        with open(run_dir / "input" / "beach.toml", "rb") as f:
            config = tomli.load(f)
        assert config["output"]["dir"] == "work/latest"

    def test_creates_latest_output_dir(
        self, adapter: BeachAdapter, run_dir: Path, case_data: dict[str, Any]
    ) -> None:
        adapter.render_inputs(case_data, run_dir)
        assert (run_dir / "work" / "latest").is_dir()

    def test_no_case_section_raises(self, adapter: BeachAdapter, run_dir: Path) -> None:
        with pytest.raises(ValueError, match="case"):
            adapter.render_inputs({}, run_dir)

    def test_preserves_unmodified_params(
        self, adapter: BeachAdapter, run_dir: Path, case_data: dict[str, Any]
    ) -> None:
        adapter.render_inputs(case_data, run_dir)
        import tomli

        with open(run_dir / "input" / "beach.toml", "rb") as f:
            config = tomli.load(f)
        # These were not overridden
        assert config["sim"]["field_solver"] == "fmm"
        assert config["sim"]["rng_seed"] == 12345


# ===================================================================
# 3. resolve_runtime
# ===================================================================


class TestResolveRuntime:
    def test_package_mode(self, adapter: BeachAdapter) -> None:
        with patch("shutil.which", return_value="/usr/local/bin/beach"):
            rt = adapter.resolve_runtime({"executable": "beach"}, "package")
        assert rt["executable"] == "/usr/local/bin/beach"

    def test_local_source_mode(self, adapter: BeachAdapter) -> None:
        rt = adapter.resolve_runtime(
            {"source_repo": "/src/BEACH", "executable": "beach"},
            "local_source",
        )
        assert rt["source_repo"] == "/src/BEACH"
        assert rt["build_command"] == "make build"

    def test_local_executable_mode(self, adapter: BeachAdapter) -> None:
        rt = adapter.resolve_runtime(
            {"executable": "/opt/beach/beach"}, "local_executable"
        )
        assert rt["executable"] == "/opt/beach/beach"

    def test_unsupported_mode(self, adapter: BeachAdapter) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            adapter.resolve_runtime({}, "spack")


# ===================================================================
# 4. build_program_command
# ===================================================================


class TestBuildProgramCommand:
    def test_basic_command(self, adapter: BeachAdapter, run_dir: Path) -> None:
        cmd = adapter.build_program_command({"executable": "/opt/beach"}, run_dir)
        assert cmd == ["/opt/beach", "input/beach.toml"]


# ===================================================================
# 5. detect_outputs
# ===================================================================


class TestDetectOutputs:
    def test_no_work_dir(self, adapter: BeachAdapter, tmp_path: Path) -> None:
        assert adapter.detect_outputs(tmp_path) == {}

    def test_detects_summary(self, adapter: BeachAdapter, run_dir: Path) -> None:
        out_dir = run_dir / "work" / "latest"
        out_dir.mkdir(parents=True)
        (out_dir / "summary.txt").write_text("mesh_nelem=400\nbatches=100\n")
        (out_dir / "charges.csv").write_text("elem_idx,charge_C\n1,1e-12\n")
        outputs = adapter.detect_outputs(run_dir)
        assert "summary" in outputs
        assert "charges" in outputs

    def test_detects_logs(self, adapter: BeachAdapter, run_dir: Path) -> None:
        (run_dir / "work" / "stdout.123.log").write_text("output")
        outputs = adapter.detect_outputs(run_dir)
        assert "logs" in outputs


# ===================================================================
# 6. detect_status
# ===================================================================


class TestDetectStatus:
    def test_unknown_empty(self, adapter: BeachAdapter, run_dir: Path) -> None:
        assert adapter.detect_status(run_dir) == "unknown"

    def test_completed_with_summary(self, adapter: BeachAdapter, run_dir: Path) -> None:
        out_dir = run_dir / "work" / "outputs"
        out_dir.mkdir(parents=True)
        (out_dir / "summary.txt").write_text("batches=100\n")
        assert adapter.detect_status(run_dir) == "completed"

    def test_failed_on_error_log(self, adapter: BeachAdapter, run_dir: Path) -> None:
        (run_dir / "work" / "stderr.123.log").write_text("FATAL: out of memory")
        assert adapter.detect_status(run_dir) == "failed"

    def test_running_with_charges(self, adapter: BeachAdapter, run_dir: Path) -> None:
        out_dir = run_dir / "work" / "outputs"
        out_dir.mkdir(parents=True)
        (out_dir / "charges.csv").write_text("elem_idx,charge_C\n")
        assert adapter.detect_status(run_dir) == "running"


# ===================================================================
# 7. summarize
# ===================================================================


class TestSummarize:
    def test_empty_summary(self, adapter: BeachAdapter, run_dir: Path) -> None:
        summary = adapter.summarize(run_dir)
        assert summary["status"] == "unknown"

    def test_summary_parses_summary_txt(
        self, adapter: BeachAdapter, run_dir: Path
    ) -> None:
        out_dir = run_dir / "work" / "latest"
        out_dir.mkdir(parents=True)
        (out_dir / "summary.txt").write_text(
            "mesh_nelem=400\nbatches=100\nprocessed_particles=12345\n"
        )
        summary = adapter.summarize(run_dir)
        assert summary["mesh_nelem"] == 400
        assert summary["batches"] == 100
        assert summary["processed_particles"] == 12345

    def test_summary_reads_config(
        self, adapter: BeachAdapter, run_dir: Path, case_data: dict[str, Any]
    ) -> None:
        adapter.render_inputs(case_data, run_dir)
        summary = adapter.summarize(run_dir)
        assert summary.get("sim_batch_count") == 200
        assert summary.get("sim_field_solver") == "fmm"

    def test_summary_reads_latest_stdout_batch_progress(
        self, adapter: BeachAdapter, run_dir: Path
    ) -> None:
        older = run_dir / "work" / "stdout.111.log"
        newer = run_dir / "work" / "stdout.222.log"
        older.write_text(
            "---------- batch 10/280000 rel_change=1.0e-2 ----------\n",
            encoding="utf-8",
        )
        newer.write_text(
            "warmup\n"
            "---------- batch 170489/280000 rel_change=2.0e-6 ----------\n"
            "---------- batch 170490/280000 rel_change=1.9e-6 ----------\n",
            encoding="utf-8",
        )
        os.utime(older, (1, 1))
        os.utime(newer, (2, 2))

        summary = adapter.summarize(run_dir)

        assert summary["last_step"] == 170490
        assert summary["nstep"] == 280000
        assert summary["status"] == "running"

    def test_status_prefers_newer_incomplete_stdout_over_stale_summary(
        self, adapter: BeachAdapter, run_dir: Path
    ) -> None:
        out_dir = run_dir / "work" / "latest"
        out_dir.mkdir(parents=True)
        summary_file = out_dir / "summary.txt"
        summary_file.write_text("batches=100\n", encoding="utf-8")
        stdout = run_dir / "work" / "stdout.123.log"
        stdout.write_text(
            "---------- batch 25/100 rel_change=5.0e-4 ----------\n",
            encoding="utf-8",
        )
        os.utime(summary_file, (1, 1))
        os.utime(stdout, (2, 2))

        assert adapter.detect_status(run_dir) == "running"


# ===================================================================
# 8. collect_provenance
# ===================================================================


class TestCollectProvenance:
    def test_basic_provenance(self, adapter: BeachAdapter) -> None:
        prov = adapter.collect_provenance(
            {"resolver_mode": "package", "executable": "/x/beach"}
        )
        assert prov["resolver_mode"] == "package"
        assert prov["exe_hash"] == ""

    def test_provenance_with_file(self, adapter: BeachAdapter, tmp_path: Path) -> None:
        exe = tmp_path / "beach"
        exe.write_bytes(b"binary")
        prov = adapter.collect_provenance(
            {"resolver_mode": "local_executable", "executable": str(exe)}
        )
        assert prov["exe_hash"].startswith("sha256:")


# ===================================================================
# 9. Helpers
# ===================================================================


class TestHelpers:
    def test_get_modules(self, adapter: BeachAdapter) -> None:
        modules = adapter.get_modules()
        assert any("intel" in m for m in modules)

    def test_get_extra_env(self, adapter: BeachAdapter) -> None:
        env = adapter.get_extra_env()
        assert "OMP_NUM_THREADS" in env
