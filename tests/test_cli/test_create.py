"""Tests for runops runs create and runs sweep CLI commands."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal project structure with simulators and launchers."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
    (tmp_path / "simulators.toml").write_text(
        "[simulators.test_sim]\n"
        'adapter = "generic"\n'
        'executable = "echo"\n'
        'resolver_mode = "package"\n'
    )
    (tmp_path / "launchers.toml").write_text(
        "[launchers.slurm_srun]\n"
        'kind = "srun"\n'
        'command = "srun"\n'
        "use_slurm_ntasks = true\n"
    )
    (tmp_path / "cases").mkdir()
    (tmp_path / "runs").mkdir()
    return tmp_path


def _make_case(project_dir: Path, case_name: str) -> Path:
    """Create a minimal case directory with case.toml."""
    case_dir = project_dir / "cases" / case_name
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text(
        f"[case]\n"
        f'name = "{case_name}"\n'
        f'simulator = "test_sim"\n'
        f'launcher = "slurm_srun"\n'
        f'description = "A test case"\n'
        f"\n"
        f"[classification]\n"
        f'model = "base_model"\n'
        f'submodel = "base_submodel"\n'
        f'tags = ["baseline"]\n'
        f"\n"
        f"[job]\n"
        f'partition = "debug"\n'
        f"nodes = 1\n"
        f"ntasks = 4\n"
        f'walltime = "00:10:00"\n'
        f"\n"
        f"[params]\n"
        f"nx = 64\n"
        f"ny = 64\n"
    )
    return case_dir


def _make_survey(
    survey_dir: Path,
    base_case: str,
) -> Path:
    """Create a minimal survey.toml."""
    survey_dir.mkdir(parents=True, exist_ok=True)
    (survey_dir / "survey.toml").write_text(
        f"[survey]\n"
        f'id = "S20260327-test"\n'
        f'name = "Test Survey"\n'
        f'base_case = "{base_case}"\n'
        f'simulator = "test_sim"\n'
        f'launcher = "slurm_srun"\n'
        f"\n"
        f"[axes]\n"
        f"nx = [32, 64]\n"
        f"ny = [32, 64]\n"
        f"\n"
        f"[naming]\n"
        f'display_name = "nx{{nx}}_ny{{ny}}"\n'
        f"\n"
        f"[job]\n"
        f'partition = "debug"\n'
        f"nodes = 1\n"
        f"ntasks = 4\n"
        f'walltime = "00:10:00"\n'
    )
    return survey_dir


# ---------------------------------------------------------------------------
# create command tests
# ---------------------------------------------------------------------------


class TestCreate:
    """Tests for the ``runops runs create`` command."""

    def test_create_success(self, tmp_path: Path) -> None:
        """A valid create invocation produces a run directory with manifest."""
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "my_case")
        dest = project_dir / "runs" / "my_survey"

        result = runner.invoke(
            app,
            ["runs", "create", "my_case", "--dest", str(dest)],
        )

        assert result.exit_code == 0, result.output
        assert "Created run:" in result.output

        # Verify a run directory was created under dest
        run_dirs = [d for d in dest.iterdir() if d.is_dir()]
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]

        # Verify standard subdirectories
        for subdir in ("input", "submit", "work", "analysis", "status"):
            assert (run_dir / subdir).is_dir()

        # Verify manifest.toml exists
        assert (run_dir / "manifest.toml").exists()

        # Verify job.sh exists
        assert (run_dir / "submit" / "job.sh").exists()

    def test_create_case_not_found(self, tmp_path: Path) -> None:
        """Create with a nonexistent case name produces an error."""
        project_dir = _make_project(tmp_path)
        dest = project_dir / "runs" / "survey1"

        result = runner.invoke(
            app,
            ["runs", "create", "nonexistent_case", "--dest", str(dest)],
        )

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_create_no_project(self, tmp_path: Path) -> None:
        """Create fails gracefully when no runops.toml exists."""
        dest = tmp_path / "no_project" / "survey"
        dest.mkdir(parents=True)

        result = runner.invoke(
            app,
            ["runs", "create", "some_case", "--dest", str(dest)],
        )

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_create_rejects_removed_survey_alias(self, tmp_path: Path) -> None:
        """Legacy survey alias points users to the dedicated sweep command."""
        project_dir = _make_project(tmp_path)
        dest = project_dir / "runs" / "survey1"
        _make_case(project_dir, "base_case")
        _make_survey(dest, "base_case")

        result = runner.invoke(
            app,
            ["runs", "create", "survey", "--dest", str(dest)],
        )

        assert result.exit_code == 1
        assert "runs sweep" in result.output

    def test_create_run_id_format(self, tmp_path: Path) -> None:
        """Created run ID matches the RYYYYMMDD-NNNN format."""
        import re

        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "my_case")
        dest = project_dir / "runs" / "survey1"

        result = runner.invoke(
            app,
            ["runs", "create", "my_case", "--dest", str(dest)],
        )

        assert result.exit_code == 0
        # Extract run_id from output
        match = re.search(r"R\d{8}-\d{4}", result.output)
        assert match is not None


# ---------------------------------------------------------------------------
# sweep command tests
# ---------------------------------------------------------------------------


class TestSweep:
    """Tests for the ``runops runs sweep`` command."""

    def test_sweep_success(self, tmp_path: Path) -> None:
        """A valid sweep creates the correct number of runs."""
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = project_dir / "runs" / "my_survey"
        _make_survey(survey_dir, "base_case")

        result = runner.invoke(
            app,
            ["runs", "sweep", str(survey_dir)],
        )

        assert result.exit_code == 0, result.output
        assert "Created 4 runs" in result.output

        # 2 x 2 = 4 run directories
        run_dirs = [
            d
            for d in survey_dir.iterdir()
            if d.is_dir() and (d / "manifest.toml").exists()
        ]
        assert len(run_dirs) == 4

    def test_sweep_display_names(self, tmp_path: Path) -> None:
        """Sweep generates display names from the naming template."""
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = project_dir / "runs" / "my_survey"
        _make_survey(survey_dir, "base_case")

        result = runner.invoke(
            app,
            ["runs", "sweep", str(survey_dir)],
        )

        assert result.exit_code == 0
        # Check that display names appear in output
        assert "nx32_ny32" in result.output
        assert "nx64_ny64" in result.output

    def test_sweep_no_survey_toml(self, tmp_path: Path) -> None:
        """Sweep fails gracefully when survey.toml is missing."""
        project_dir = _make_project(tmp_path)
        survey_dir = project_dir / "runs" / "empty_survey"
        survey_dir.mkdir(parents=True)

        result = runner.invoke(
            app,
            ["runs", "sweep", str(survey_dir)],
        )

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_sweep_bad_base_case(self, tmp_path: Path) -> None:
        """Sweep fails when the base case does not exist."""
        project_dir = _make_project(tmp_path)
        survey_dir = project_dir / "runs" / "my_survey"
        _make_survey(survey_dir, "nonexistent_case")

        result = runner.invoke(
            app,
            ["runs", "sweep", str(survey_dir)],
        )

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_sweep_manifest_has_survey_info(self, tmp_path: Path) -> None:
        """Sweep-generated manifests record the survey ID and variation keys."""
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
            import tomli as tomllib

        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = project_dir / "runs" / "my_survey"
        _make_survey(survey_dir, "base_case")

        result = runner.invoke(
            app,
            ["runs", "sweep", str(survey_dir)],
        )

        assert result.exit_code == 0

        # Read one manifest and check survey fields
        run_dirs = [
            d
            for d in survey_dir.iterdir()
            if d.is_dir() and (d / "manifest.toml").exists()
        ]
        manifest_path = run_dirs[0] / "manifest.toml"
        with open(manifest_path, "rb") as f:
            manifest = tomllib.load(f)

        assert manifest["origin"]["survey"] == "S20260327-test"
        assert set(manifest["variation"]["changed_keys"]) == {"nx", "ny"}

    def test_sweep_applies_partial_survey_overrides(self, tmp_path: Path) -> None:
        """Survey [classification]/[job] fields overlay the base case by key."""
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
            import tomli as tomllib

        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = project_dir / "runs" / "my_survey"
        survey_dir.mkdir(parents=True)
        (survey_dir / "survey.toml").write_text(
            "[survey]\n"
            'id = "S20260327-partial"\n'
            'name = "Partial override survey"\n'
            'base_case = "base_case"\n'
            'simulator = "test_sim"\n'
            'launcher = "slurm_srun"\n'
            "\n"
            "[classification]\n"
            'tags = ["scan"]\n'
            "\n"
            "[axes]\n"
            "nx = [32]\n"
            "\n"
            "[job]\n"
            'walltime = "02:30:00"\n'
            'modules = ["custom/module"]\n'
        )

        result = runner.invoke(app, ["runs", "sweep", str(survey_dir)])
        assert result.exit_code == 0, result.output

        run_dirs = [
            d
            for d in survey_dir.iterdir()
            if d.is_dir() and (d / "manifest.toml").exists()
        ]
        assert len(run_dirs) == 1
        with open(run_dirs[0] / "manifest.toml", "rb") as f:
            manifest = tomllib.load(f)
        job_sh = (run_dirs[0] / "submit" / "job.sh").read_text()

        assert manifest["classification"] == {
            "model": "base_model",
            "submodel": "base_submodel",
            "tags": ["scan"],
        }
        assert manifest["job"]["partition"] == "debug"
        assert manifest["job"]["nodes"] == 1
        assert manifest["job"]["ntasks"] == 4
        assert manifest["job"]["walltime"] == "02:30:00"
        assert "module load custom/module" in job_sh

    def test_sweep_dry_run_does_not_create_runs(self, tmp_path: Path) -> None:
        """--dry-run prints planned runs and resource estimate without writing."""
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = project_dir / "runs" / "my_survey"
        _make_survey(survey_dir, "base_case")

        result = runner.invoke(app, ["runs", "sweep", "--dry-run", str(survey_dir)])

        assert result.exit_code == 0, result.output
        assert "[dry-run]" in result.output
        assert "4 runs would be created" in result.output
        assert "base_case" in result.output
        # Resource estimate line.
        assert "core-hours" in result.output

        # No run directories should exist after dry-run.
        run_dirs = [
            d
            for d in survey_dir.iterdir()
            if d.is_dir() and (d / "manifest.toml").exists()
        ]
        assert run_dirs == []

    def test_sweep_dry_run_lists_combinations(self, tmp_path: Path) -> None:
        """--dry-run prints one line per planned run with its parameters."""
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = project_dir / "runs" / "my_survey"
        _make_survey(survey_dir, "base_case")

        result = runner.invoke(app, ["runs", "sweep", "--dry-run", str(survey_dir)])

        assert result.exit_code == 0, result.output
        # Display names from the naming template should appear (as they
        # would in a real sweep).
        assert "nx32_ny32" in result.output
        assert "nx64_ny64" in result.output
        # Parameter values should be shown.
        assert "nx=32" in result.output
        assert "ny=64" in result.output

    def test_sweep_dry_run_short_flag(self, tmp_path: Path) -> None:
        """``-n`` is an accepted short alias for --dry-run."""
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = project_dir / "runs" / "my_survey"
        _make_survey(survey_dir, "base_case")

        result = runner.invoke(app, ["runs", "sweep", "-n", str(survey_dir)])
        assert result.exit_code == 0, result.output
        assert "[dry-run]" in result.output

        # No run directories should exist.
        run_dirs = [
            d
            for d in survey_dir.iterdir()
            if d.is_dir() and (d / "manifest.toml").exists()
        ]
        assert run_dirs == []

    def test_sweep_dry_run_no_survey_toml(self, tmp_path: Path) -> None:
        """--dry-run still surfaces missing survey.toml errors."""
        project_dir = _make_project(tmp_path)
        survey_dir = project_dir / "runs" / "empty_survey"
        survey_dir.mkdir(parents=True)

        result = runner.invoke(app, ["runs", "sweep", "--dry-run", str(survey_dir)])
        assert result.exit_code == 1
        assert "Error" in result.output
