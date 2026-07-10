"""Tests for the EMSES adapter — contract tests for all abstract methods."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import tomli_w

from runops.adapters.contrib.emses import EmseAdapter

SAMPLE_PLASMA_CONFIG: dict[str, Any] = {
    "meta": {
        "format_version": 2,
        "unit_conversion": {"dx": 0.5, "to_c": 10000.0},
    },
    "jobcon": {"nstep": 2000},
    "plasma": {"wc": 0.0, "phiz": 0.0, "cv": 10000.0},
    "tmgrid": {"dt": 0.002, "nx": 1000, "ny": 1, "nz": 800},
    "system": {"nspec": 2},
    "species": [
        {"wp": 2.1, "qm": -1.0, "npin": 24000000},
        {"wp": 0.049, "qm": 0.00054, "npin": 24000000},
    ],
}


@pytest.fixture()
def adapter() -> EmseAdapter:
    """Return a fresh EmseAdapter instance."""
    return EmseAdapter()


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    """Create a minimal run directory structure."""
    for sub in ("input", "work", "analysis", "status", "submit"):
        (tmp_path / sub).mkdir()
    return tmp_path


@pytest.fixture()
def case_dir(tmp_path: Path) -> Path:
    """Create a case directory with a plasma.toml template."""
    cdir = tmp_path / "case_flat"
    cdir.mkdir()
    with open(cdir / "plasma.toml", "wb") as f:
        tomli_w.dump(SAMPLE_PLASMA_CONFIG, f)
    return cdir


@pytest.fixture()
def case_data(case_dir: Path) -> dict[str, Any]:
    """Sample EMSES case data."""
    return {
        "case": {
            "name": "flat_surface",
            "simulator": "emses",
            "launcher": "srun",
            "case_dir": str(case_dir),
        },
        "params": {
            "jobcon.nstep": 5000,
            "plasma.wc": 0.147,
        },
    }


# ===================================================================
# 1. name
# ===================================================================


class TestName:
    def test_name(self, adapter: EmseAdapter) -> None:
        assert adapter.name == "emses"


class TestKnowledgeSources:
    def test_includes_cookbook_patterns(self) -> None:
        sources = EmseAdapter.knowledge_sources()
        assert "MPIEMSES3D" in sources
        patterns = sources["MPIEMSES3D"]
        assert "cookbook/index.toml" in patterns
        assert "cookbook/**/*.toml" in patterns
        assert "cookbook/**/*.md" in patterns


class TestCaseTemplate:
    def test_summarize_scaffold_focuses_on_profiles_and_conductors(self) -> None:
        templates = EmseAdapter.case_template()
        summarize_script = templates["summarize.py"]

        assert "potential_density_profile.png" in summarize_script
        assert "unit.phi.reverse" in summarize_script
        assert "inp.npc" in summarize_script
        assert "input_path=str(input_path)" in summarize_script
        assert "output_directory=str(output_dir)" in summarize_script
        assert "energy_total.png" not in summarize_script

    def test_summarize_scaffold_uses_input_and_latest_output_dirs(
        self,
        tmp_path: Path,
    ) -> None:
        templates = EmseAdapter.case_template()
        script_path = tmp_path / "summarize.py"
        script_path.write_text(templates["summarize.py"], encoding="utf-8")

        run_dir = tmp_path / "R20260403-0001"
        (run_dir / "input").mkdir(parents=True)
        (run_dir / "work" / "latest").mkdir(parents=True)
        (run_dir / "analysis").mkdir()
        (run_dir / "input" / "plasma.toml").write_text(
            "[jobcon]\nnstep = 10\n",
            encoding="utf-8",
        )

        calls: list[dict[str, str]] = []

        class FakeEmout:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                calls.append(
                    {
                        "input_path": str(kwargs.get("input_path", "")),
                        "output_directory": str(kwargs.get("output_directory", "")),
                    }
                )

        fake_module = types.ModuleType("emout")
        fake_module.Emout = FakeEmout  # type: ignore[attr-defined]

        spec = importlib.util.spec_from_file_location(
            "_emses_summarize_test",
            script_path,
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)

        original = sys.modules.get("emout")
        sys.modules["emout"] = fake_module
        try:
            spec.loader.exec_module(module)
            result = module.summarize(run_dir, {})  # type: ignore[attr-defined]
        finally:
            if original is None:
                sys.modules.pop("emout", None)
            else:
                sys.modules["emout"] = original

        assert result == {}
        assert len(calls) == 1
        assert calls[0]["input_path"] == str(run_dir / "input" / "plasma.toml")
        assert calls[0]["output_directory"] == str(run_dir / "work" / "latest")


# ===================================================================
# 2. render_inputs
# ===================================================================


class TestRenderInputs:
    def test_renders_plasma_toml(
        self, adapter: EmseAdapter, run_dir: Path, case_data: dict[str, Any]
    ) -> None:
        created = adapter.render_inputs(case_data, run_dir)
        assert any(Path(path).name == "plasma.toml" for path in created)
        assert (run_dir / "input" / "plasma.toml").exists()

    def test_applies_overrides(
        self, adapter: EmseAdapter, run_dir: Path, case_data: dict[str, Any]
    ) -> None:
        adapter.render_inputs(case_data, run_dir)
        import tomli

        with open(run_dir / "input" / "plasma.toml", "rb") as f:
            config = tomli.load(f)
        assert config["jobcon"]["nstep"] == 5000
        assert config["plasma"]["wc"] == 0.147

    def test_preserves_unmodified_params(
        self, adapter: EmseAdapter, run_dir: Path, case_data: dict[str, Any]
    ) -> None:
        adapter.render_inputs(case_data, run_dir)
        import tomli

        with open(run_dir / "input" / "plasma.toml", "rb") as f:
            config = tomli.load(f)
        assert config["plasma"]["phiz"] == 0.0
        assert config["tmgrid"]["dt"] == 0.002
        assert config["tmgrid"]["nx"] == 1000

    def test_no_case_section_raises(self, adapter: EmseAdapter, run_dir: Path) -> None:
        with pytest.raises(ValueError, match="case"):
            adapter.render_inputs({}, run_dir)

    def test_no_template_creates_no_files(
        self, adapter: EmseAdapter, run_dir: Path
    ) -> None:
        data: dict[str, Any] = {
            "case": {"name": "empty", "simulator": "emses", "case_dir": "/nonexistent"},
        }
        created = adapter.render_inputs(data, run_dir)
        assert created == []

    def test_species_override(
        self, adapter: EmseAdapter, run_dir: Path, case_dir: Path
    ) -> None:
        """Dot-notation with numeric index targets array-of-tables."""
        data: dict[str, Any] = {
            "case": {"name": "test", "simulator": "emses", "case_dir": str(case_dir)},
            "params": {"species.0.wp": 3.0},
        }
        adapter.render_inputs(data, run_dir)
        import tomli

        with open(run_dir / "input" / "plasma.toml", "rb") as f:
            config = tomli.load(f)
        assert config["species"][0]["wp"] == 3.0
        assert config["species"][1]["wp"] == 0.049  # unchanged


# ===================================================================
# 3. resolve_runtime
# ===================================================================


class TestResolveRuntime:
    def test_package_mode_uses_simulator_default(self, adapter: EmseAdapter) -> None:
        with patch("shutil.which", return_value=None):
            rt = adapter.resolve_runtime({"venv_path": "/opt/emses-venv"}, "package")
        assert rt == {
            "resolver_mode": "package",
            "venv_path": "/opt/emses-venv",
            "executable": "mpiemses3D",
            "source": "package",
        }

    def test_package_mode(self, adapter: EmseAdapter) -> None:
        with patch("shutil.which", return_value="/usr/bin/mpiemses3D"):
            rt = adapter.resolve_runtime({"executable": "mpiemses3D"}, "package")
        assert rt["executable"] == "/usr/bin/mpiemses3D"

    def test_local_executable_mode(self, adapter: EmseAdapter) -> None:
        rt = adapter.resolve_runtime(
            {"executable": "/opt/emses/mpiemses3D"}, "local_executable"
        )
        assert rt["executable"] == "/opt/emses/mpiemses3D"

    def test_local_source_mode(self, adapter: EmseAdapter) -> None:
        rt = adapter.resolve_runtime(
            {"source_repo": "/src/EMSES", "executable": "mpiemses3D"},
            "local_source",
        )
        assert rt["source_repo"] == "/src/EMSES"
        assert rt["executable"] == "mpiemses3D"
        assert rt["build_command"] == ""

    def test_local_source_mode_uses_simulator_defaults(
        self,
        adapter: EmseAdapter,
    ) -> None:
        rt = adapter.resolve_runtime(
            {
                "source_repo": "/src/EMSES",
                "venv_path": "/opt/emses-venv",
            },
            "local_source",
        )
        assert rt == {
            "resolver_mode": "local_source",
            "venv_path": "/opt/emses-venv",
            "source_repo": "/src/EMSES",
            "executable": "mpiemses3D",
            "build_command": "",
        }

    def test_unsupported_mode(self, adapter: EmseAdapter) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            adapter.resolve_runtime({}, "conda")

    def test_local_source_missing_repo(self, adapter: EmseAdapter) -> None:
        with pytest.raises(ValueError, match="source_repo"):
            adapter.resolve_runtime({"executable": "x"}, "local_source")

    def test_local_executable_missing_exe(self, adapter: EmseAdapter) -> None:
        with pytest.raises(ValueError, match="executable"):
            adapter.resolve_runtime({}, "local_executable")


# ===================================================================
# 4. build_program_command
# ===================================================================


class TestBuildProgramCommand:
    def test_basic_command(self, adapter: EmseAdapter, run_dir: Path) -> None:
        cmd = adapter.build_program_command({"executable": "/opt/mpiemses3D"}, run_dir)
        assert cmd == [
            "/opt/mpiemses3D",
            "input/plasma.toml",
            "-o",
            "work/latest",
        ]

    def test_default_executable(self, adapter: EmseAdapter, run_dir: Path) -> None:
        cmd = adapter.build_program_command({}, run_dir)
        assert cmd[0] == "mpiemses3D"

    def test_creates_latest_output_dir(
        self, adapter: EmseAdapter, run_dir: Path, case_data: dict[str, Any]
    ) -> None:
        adapter.render_inputs(case_data, run_dir)
        assert (run_dir / "work" / "latest").is_dir()


# ===================================================================
# 5. detect_outputs
# ===================================================================


class TestDetectOutputs:
    def test_no_work_dir(self, adapter: EmseAdapter, tmp_path: Path) -> None:
        assert adapter.detect_outputs(tmp_path) == {}

    def test_detects_h5_files(self, adapter: EmseAdapter, run_dir: Path) -> None:
        (run_dir / "work" / "ex00_0000.h5").write_bytes(b"")
        (run_dir / "work" / "ey00_0000.h5").write_bytes(b"")
        outputs = adapter.detect_outputs(run_dir)
        assert "hdf5_fields" in outputs
        assert len(outputs["hdf5_fields"]) == 2

    def test_detects_diagnostics(self, adapter: EmseAdapter, run_dir: Path) -> None:
        (run_dir / "work" / "energy").write_text("0 1.0 2.0")
        (run_dir / "work" / "volt").write_text("0 0.5")
        outputs = adapter.detect_outputs(run_dir)
        assert "diagnostics" in outputs
        assert len(outputs["diagnostics"]) == 2

    def test_detects_snapshots(self, adapter: EmseAdapter, run_dir: Path) -> None:
        snap_dir = run_dir / "work" / "SNAPSHOT1"
        snap_dir.mkdir()
        (snap_dir / "esdat0000.h5").write_bytes(b"")
        (snap_dir / "esdat0001.h5").write_bytes(b"")
        outputs = adapter.detect_outputs(run_dir)
        assert "snapshots" in outputs
        assert len(outputs["snapshots"]) == 2

    def test_detects_logs(self, adapter: EmseAdapter, run_dir: Path) -> None:
        (run_dir / "work" / "stdout.12345.log").write_text("output")
        outputs = adapter.detect_outputs(run_dir)
        assert "logs" in outputs

    def test_detects_outputs_in_latest_dir(
        self, adapter: EmseAdapter, run_dir: Path
    ) -> None:
        latest_dir = run_dir / "work" / "latest"
        latest_dir.mkdir(parents=True, exist_ok=True)
        (latest_dir / "energy").write_text("100 1.0 2.0")
        (latest_dir / "ex00_0000.h5").write_bytes(b"")
        outputs = adapter.detect_outputs(run_dir)
        assert outputs["hdf5_fields"] == ["work/latest/ex00_0000.h5"]
        assert "work/latest/energy" in outputs["diagnostics"]

    def test_declares_hdf5_fields_as_required_output(
        self,
        adapter: EmseAdapter,
    ) -> None:
        assert adapter.required_outputs() == {
            "hdf5_fields": "EMSES HDF5 field output files"
        }


# ===================================================================
# 6. detect_status
# ===================================================================


class TestDetectStatus:
    def test_unknown_no_work(self, adapter: EmseAdapter, tmp_path: Path) -> None:
        assert adapter.detect_status(tmp_path) == "unknown"

    def test_unknown_empty_work(self, adapter: EmseAdapter, run_dir: Path) -> None:
        assert adapter.detect_status(run_dir) == "unknown"

    def test_failed_on_error_log(self, adapter: EmseAdapter, run_dir: Path) -> None:
        (run_dir / "work" / "stderr.123.log").write_text("Segmentation fault")
        assert adapter.detect_status(run_dir) == "failed"

    def test_completed_when_nstep_reached(
        self, adapter: EmseAdapter, run_dir: Path
    ) -> None:
        # Set up plasma.toml with nstep = 100
        with open(run_dir / "input" / "plasma.toml", "wb") as f:
            tomli_w.dump({"jobcon": {"nstep": 100}}, f)
        # Energy file showing step 100 reached
        (run_dir / "work" / "energy").write_text("50 1.0 2.0\n100 1.1 2.1\n")
        assert adapter.detect_status(run_dir) == "completed"

    def test_running_when_not_finished(
        self, adapter: EmseAdapter, run_dir: Path
    ) -> None:
        with open(run_dir / "input" / "plasma.toml", "wb") as f:
            tomli_w.dump({"jobcon": {"nstep": 1000}}, f)
        (run_dir / "work" / "energy").write_text("50 1.0 2.0\n")
        assert adapter.detect_status(run_dir) == "running"

    def test_running_with_h5_files(self, adapter: EmseAdapter, run_dir: Path) -> None:
        (run_dir / "work" / "ex00_0000.h5").write_bytes(b"")
        assert adapter.detect_status(run_dir) == "running"


# ===================================================================
# 7. summarize
# ===================================================================


class TestSummarize:
    def test_basic_summary(self, adapter: EmseAdapter, run_dir: Path) -> None:
        summary = adapter.summarize(run_dir)
        assert summary["status"] == "unknown"
        assert "output_counts" in summary

    def test_summary_with_energy(self, adapter: EmseAdapter, run_dir: Path) -> None:
        (run_dir / "work" / "energy").write_text("50 1.0\n100 1.1\n")
        summary = adapter.summarize(run_dir)
        assert summary["total_energy_lines"] == 2
        assert summary["last_step"] == 100

    def test_summary_reads_toml_params(
        self, adapter: EmseAdapter, run_dir: Path
    ) -> None:
        with open(run_dir / "input" / "plasma.toml", "wb") as f:
            tomli_w.dump(
                {"tmgrid": {"nx": 512, "dt": 0.001}, "jobcon": {"nstep": 5000}},
                f,
            )
        summary = adapter.summarize(run_dir)
        assert summary["nx"] == 512
        assert summary["nstep"] == 5000


# ===================================================================
# 8. collect_provenance
# ===================================================================


class TestCollectProvenance:
    def test_basic_provenance(self, adapter: EmseAdapter) -> None:
        prov = adapter.collect_provenance(
            {"resolver_mode": "local_executable", "executable": "/x/solver"}
        )
        assert prov["resolver_mode"] == "local_executable"
        assert prov["exe_hash"] == ""

    def test_provenance_with_real_file(
        self, adapter: EmseAdapter, tmp_path: Path
    ) -> None:
        exe = tmp_path / "mpiemses3D"
        exe.write_bytes(b"fake binary")
        prov = adapter.collect_provenance(
            {"resolver_mode": "local_executable", "executable": str(exe)}
        )
        assert prov["exe_hash"].startswith("sha256:")

    def test_package_version_remains_empty(self, adapter: EmseAdapter) -> None:
        prov = adapter.collect_provenance(
            {
                "resolver_mode": "package",
                "executable": "mpiemses3D",
                "package_version": "9.9.9",
            }
        )

        assert prov["package_version"] == ""


# ===================================================================
# 9. Helper methods
# ===================================================================


class TestHelpers:
    def test_get_setup_commands(self, adapter: EmseAdapter, run_dir: Path) -> None:
        cmds = adapter.get_setup_commands(run_dir)
        assert any("plasma.toml" in c for c in cmds)

    def test_get_modules(self, adapter: EmseAdapter) -> None:
        modules = adapter.get_modules()
        assert modules == []

    def test_get_extra_env(self, adapter: EmseAdapter) -> None:
        env = adapter.get_extra_env()
        assert "EMSES_DEBUG" in env
