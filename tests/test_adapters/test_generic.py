"""Tests for the GenericAdapter — contract tests for all 7 abstract methods."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from runops.adapters.generic import GenericAdapter


@pytest.fixture()
def adapter() -> GenericAdapter:
    """Return a fresh GenericAdapter instance."""
    return GenericAdapter()


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    """Create a minimal run directory structure."""
    (tmp_path / "input").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / "analysis").mkdir()
    (tmp_path / "status").mkdir()
    (tmp_path / "submit").mkdir()
    return tmp_path


@pytest.fixture()
def case_data() -> dict[str, Any]:
    """Sample case data for testing."""
    return {
        "case": {
            "name": "test_case",
            "simulator": "generic",
            "launcher": "slurm_srun",
            "description": "unit test case",
        },
        "params": {
            "nx": 64,
            "ny": 64,
            "dt": 1.0e-6,
        },
    }


@pytest.fixture()
def simulator_config_local_source() -> dict[str, Any]:
    """Sample simulator config for local_source mode."""
    return {
        "adapter": "generic",
        "resolver_mode": "local_source",
        "source_repo": "/tmp/fake-repo",
        "build_command": "make -j",
        "executable": "/tmp/fake-repo/build/solver",
    }


@pytest.fixture()
def simulator_config_package() -> dict[str, Any]:
    """Sample simulator config for package mode."""
    return {
        "adapter": "generic",
        "resolver_mode": "package",
        "executable": "solver",
    }


# ===================================================================
# 1. name property
# ===================================================================


class TestName:
    """Tests for the name property."""

    def test_name(self, adapter: GenericAdapter) -> None:
        """Name should be 'generic'."""
        assert adapter.name == "generic"


# ===================================================================
# 2. render_inputs
# ===================================================================


class TestRenderInputs:
    """Tests for render_inputs."""

    def test_renders_params_json(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
        case_data: dict[str, Any],
    ) -> None:
        """Should create input/params.json from case params."""
        created = adapter.render_inputs(case_data, run_dir)
        assert "input/params.json" in created
        params_path = run_dir / "input" / "params.json"
        assert params_path.exists()
        loaded = json.loads(params_path.read_text())
        assert loaded["nx"] == 64

    def test_no_params_section(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """No params -> no params.json, but still succeeds."""
        data: dict[str, Any] = {"case": {"name": "no_params", "simulator": "generic"}}
        created = adapter.render_inputs(data, run_dir)
        assert "input/params.json" not in created

    def test_missing_case_section_raises(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Missing 'case' section should raise ValueError."""
        with pytest.raises(ValueError, match="case"):
            adapter.render_inputs({}, run_dir)

    def test_copies_input_files(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Explicit input_files are copied into input/."""
        # Create a source file outside run_dir
        src_dir = tmp_path / "sources"
        src_dir.mkdir()
        src_file = src_dir / "mesh.inp"
        src_file.write_text("mesh data")

        data: dict[str, Any] = {
            "case": {
                "name": "copy_test",
                "simulator": "generic",
                "input_files": [str(src_file)],
            },
        }
        created = adapter.render_inputs(data, run_dir)
        assert "input/mesh.inp" in created
        assert (run_dir / "input" / "mesh.inp").read_text() == "mesh data"

    def test_missing_input_file_skipped(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Non-existent input files are skipped with a warning."""
        data: dict[str, Any] = {
            "case": {
                "name": "missing_file",
                "simulator": "generic",
                "input_files": ["/nonexistent/file.dat"],
            },
        }
        created = adapter.render_inputs(data, run_dir)
        assert created == []

    def test_creates_input_dir(
        self,
        adapter: GenericAdapter,
        tmp_path: Path,
        case_data: dict[str, Any],
    ) -> None:
        """input/ directory is created if it doesn't exist."""
        bare_dir = tmp_path / "bare_run"
        bare_dir.mkdir()
        adapter.render_inputs(case_data, bare_dir)
        assert (bare_dir / "input" / "params.json").exists()


# ===================================================================
# 3. resolve_runtime
# ===================================================================


class TestResolveRuntime:
    """Tests for resolve_runtime."""

    def test_package_mode(
        self,
        adapter: GenericAdapter,
        simulator_config_package: dict[str, Any],
    ) -> None:
        """Package mode resolves executable name."""
        with patch("shutil.which", return_value="/usr/bin/solver"):
            rt = adapter.resolve_runtime(simulator_config_package, "package")
        assert rt["executable"] == "/usr/bin/solver"
        assert rt["resolver_mode"] == "package"

    def test_package_mode_not_found(
        self,
        adapter: GenericAdapter,
        simulator_config_package: dict[str, Any],
    ) -> None:
        """Package mode falls back to raw name if not on PATH."""
        with patch("shutil.which", return_value=None):
            rt = adapter.resolve_runtime(simulator_config_package, "package")
        assert rt["executable"] == "solver"

    def test_package_mode_preserves_runtime_shape(
        self,
        adapter: GenericAdapter,
        simulator_config_package: dict[str, Any],
    ) -> None:
        """Package mode keeps the established three-key payload."""
        with patch("shutil.which", return_value=None):
            rt = adapter.resolve_runtime(simulator_config_package, "package")
        assert rt == {
            "resolver_mode": "package",
            "executable": "solver",
            "source": "package",
        }

    def test_local_source_mode(
        self,
        adapter: GenericAdapter,
        simulator_config_local_source: dict[str, Any],
    ) -> None:
        """Local source mode captures repo, exe, and build command."""
        rt = adapter.resolve_runtime(simulator_config_local_source, "local_source")
        assert rt["source_repo"] == "/tmp/fake-repo"
        assert rt["executable"] == "/tmp/fake-repo/build/solver"
        assert rt["build_command"] == "make -j"

    def test_local_executable_mode(
        self,
        adapter: GenericAdapter,
    ) -> None:
        """Local executable mode uses the path directly."""
        cfg: dict[str, Any] = {"executable": "/opt/solver/bin/solver"}
        rt = adapter.resolve_runtime(cfg, "local_executable")
        assert rt["executable"] == "/opt/solver/bin/solver"
        assert rt["resolver_mode"] == "local_executable"

    def test_unsupported_mode_raises(
        self,
        adapter: GenericAdapter,
    ) -> None:
        """Unsupported resolver mode should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported resolver_mode"):
            adapter.resolve_runtime({}, "conda")

    def test_package_mode_missing_executable(
        self,
        adapter: GenericAdapter,
    ) -> None:
        """Package mode without executable should raise ValueError."""
        with pytest.raises(ValueError, match="executable"):
            adapter.resolve_runtime({}, "package")

    def test_local_source_missing_keys(
        self,
        adapter: GenericAdapter,
    ) -> None:
        """local_source without source_repo should raise."""
        with pytest.raises(ValueError, match="source_repo"):
            adapter.resolve_runtime({"executable": "x"}, "local_source")

    def test_local_executable_missing_exe(
        self,
        adapter: GenericAdapter,
    ) -> None:
        """local_executable without executable should raise."""
        with pytest.raises(ValueError, match="executable"):
            adapter.resolve_runtime({}, "local_executable")


# ===================================================================
# 4. build_program_command
# ===================================================================


class TestBuildProgramCommand:
    """Tests for build_program_command."""

    def test_basic_command(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Returns [executable] when no params.json exists."""
        rt: dict[str, Any] = {"executable": "/usr/bin/solver"}
        cmd = adapter.build_program_command(rt, run_dir)
        assert cmd == ["/usr/bin/solver"]

    def test_with_params_file(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Appends params.json path when it exists."""
        params_file = run_dir / "input" / "params.json"
        params_file.write_text("{}")
        rt: dict[str, Any] = {"executable": "/usr/bin/solver"}
        cmd = adapter.build_program_command(rt, run_dir)
        assert cmd[0] == "/usr/bin/solver"
        assert cmd[1] == str(params_file)

    def test_missing_executable_raises(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Missing executable in runtime_info raises ValueError."""
        with pytest.raises(ValueError, match="executable"):
            adapter.build_program_command({}, run_dir)


# ===================================================================
# 5. detect_outputs
# ===================================================================


class TestDetectOutputs:
    """Tests for detect_outputs."""

    def test_no_work_dir(
        self,
        adapter: GenericAdapter,
        tmp_path: Path,
    ) -> None:
        """Missing work/ returns empty dict."""
        result = adapter.detect_outputs(tmp_path)
        assert result == {}

    def test_empty_work_dir(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Empty work/ returns empty dict."""
        result = adapter.detect_outputs(run_dir)
        assert result == {}

    def test_detects_stdout_stderr(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Detects stdout.log and stderr.log."""
        (run_dir / "work" / "stdout.log").write_text("output")
        (run_dir / "work" / "stderr.log").write_text("errors")
        result = adapter.detect_outputs(run_dir)
        assert result["stdout"] == "work/stdout.log"
        assert result["stderr"] == "work/stderr.log"

    def test_detects_additional_files(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Other files in work/ are detected."""
        (run_dir / "work" / "result.dat").write_text("data")
        result = adapter.detect_outputs(run_dir)
        assert "result" in result

    def test_detects_subdirectories(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Subdirectories in work/ are detected."""
        (run_dir / "work" / "outputs").mkdir()
        result = adapter.detect_outputs(run_dir)
        assert "outputs" in result

    def test_excludes_exit_code(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """exit_code file is not listed as an output."""
        (run_dir / "work" / "exit_code").write_text("0")
        (run_dir / "work" / "result.dat").write_text("data")
        result = adapter.detect_outputs(run_dir)
        assert "exit_code" not in result


# ===================================================================
# 6. detect_status
# ===================================================================


class TestDetectStatus:
    """Tests for detect_status."""

    def test_completed(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """exit_code 0 -> completed."""
        (run_dir / "work" / "exit_code").write_text("0")
        assert adapter.detect_status(run_dir) == "completed"

    def test_failed(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Non-zero exit_code -> failed."""
        (run_dir / "work" / "exit_code").write_text("1")
        assert adapter.detect_status(run_dir) == "failed"

    def test_running(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Files in work/ without exit_code -> running."""
        (run_dir / "work" / "stdout.log").write_text("in progress")
        assert adapter.detect_status(run_dir) == "running"

    def test_unknown_empty(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Empty work/ -> unknown."""
        assert adapter.detect_status(run_dir) == "unknown"

    def test_unknown_no_work(
        self,
        adapter: GenericAdapter,
        tmp_path: Path,
    ) -> None:
        """Missing work/ -> unknown."""
        assert adapter.detect_status(tmp_path) == "unknown"

    def test_corrupt_exit_code(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Non-integer exit_code -> unknown."""
        (run_dir / "work" / "exit_code").write_text("SEGFAULT")
        assert adapter.detect_status(run_dir) == "unknown"


# ===================================================================
# 7. summarize
# ===================================================================


class TestSummarize:
    """Tests for summarize."""

    def test_completed_summary(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Summary of a completed run."""
        (run_dir / "work" / "exit_code").write_text("0")
        (run_dir / "work" / "result.dat").write_text("data")
        summary = adapter.summarize(run_dir)
        assert summary["status"] == "completed"
        assert summary["exit_code"] == 0
        assert "result" in summary["outputs"]
        assert "errors" not in summary

    def test_empty_run_summary(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Summary of an empty run."""
        summary = adapter.summarize(run_dir)
        assert summary["status"] == "unknown"
        assert summary["outputs"] == {}

    def test_summary_with_corrupt_exit_code(
        self,
        adapter: GenericAdapter,
        run_dir: Path,
    ) -> None:
        """Corrupt exit_code is reported in errors."""
        (run_dir / "work" / "exit_code").write_text("bad")
        summary = adapter.summarize(run_dir)
        assert "errors" in summary


# ===================================================================
# 8. collect_provenance
# ===================================================================


class TestCollectProvenance:
    """Tests for collect_provenance."""

    def test_basic_provenance(
        self,
        adapter: GenericAdapter,
    ) -> None:
        """Provenance includes resolver_mode and executable."""
        rt: dict[str, Any] = {
            "resolver_mode": "local_executable",
            "executable": "/nonexistent/solver",
        }
        prov = adapter.collect_provenance(rt)
        assert prov["resolver_mode"] == "local_executable"
        assert prov["executable"] == "/nonexistent/solver"
        # Non-existent file -> empty hash
        assert prov["exe_hash"] == ""

    def test_provenance_with_real_file(
        self,
        adapter: GenericAdapter,
        tmp_path: Path,
    ) -> None:
        """Provenance includes sha256 hash for existing executables."""
        exe = tmp_path / "solver"
        exe.write_bytes(b"fake binary content")
        rt: dict[str, Any] = {
            "resolver_mode": "local_executable",
            "executable": str(exe),
        }
        prov = adapter.collect_provenance(rt)
        assert prov["exe_hash"].startswith("sha256:")

    def test_provenance_local_source(
        self,
        adapter: GenericAdapter,
    ) -> None:
        """local_source mode includes source_repo and git info as flat fields."""
        rt: dict[str, Any] = {
            "resolver_mode": "local_source",
            "source_repo": "/nonexistent/repo",
            "executable": "/nonexistent/solver",
            "build_command": "make",
        }
        prov = adapter.collect_provenance(rt)
        assert prov["source_repo"] == "/nonexistent/repo"
        assert "git_commit" in prov
        assert "git_dirty" in prov
        assert prov["build_command"] == "make"
        assert prov["package_version"] == ""

    def test_provenance_empty_runtime(
        self,
        adapter: GenericAdapter,
    ) -> None:
        """Empty runtime_info produces safe defaults."""
        prov = adapter.collect_provenance({})
        assert prov["resolver_mode"] == ""
        assert prov["executable"] == ""
        assert prov["exe_hash"] == ""
        assert prov["git_commit"] == ""
        assert prov["git_dirty"] is False
        assert prov["build_command"] == ""
        assert prov["package_version"] == ""

    def test_provenance_preserves_package_version(
        self,
        adapter: GenericAdapter,
    ) -> None:
        """Generic runtime metadata carries package version into provenance."""
        prov = adapter.collect_provenance(
            {
                "resolver_mode": "package",
                "executable": "solver",
                "package_version": "2.3.4",
            }
        )

        assert prov["package_version"] == "2.3.4"
