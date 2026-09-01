"""Tests for ``runo runs create`` and bounded ``runs sweep`` behavior."""

from __future__ import annotations

import json
import re
from pathlib import Path

import tomli as tomllib
from typer.testing import CliRunner

from runops.cli.main import app
from runops.core.manifest import update_manifest

runner = CliRunner()


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "test-project"\n', encoding="utf-8"
    )
    (tmp_path / "simulators.toml").write_text(
        "[simulators.test_sim]\n"
        'adapter = "generic"\n'
        'executable = "echo"\n'
        'resolver_mode = "package"\n',
        encoding="utf-8",
    )
    (tmp_path / "launchers.toml").write_text(
        "[launchers.slurm_srun]\n"
        'kind = "srun"\n'
        'command = "srun"\n'
        "use_slurm_ntasks = true\n",
        encoding="utf-8",
    )
    (tmp_path / "cases").mkdir()
    (tmp_path / "runs").mkdir()
    return tmp_path


def _make_case(project_dir: Path, case_name: str) -> Path:
    case_dir = project_dir / "cases" / case_name
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text(
        "[case]\n"
        f'name = "{case_name}"\n'
        'simulator = "test_sim"\n'
        'launcher = "slurm_srun"\n'
        'description = "A test case"\n\n'
        "[classification]\n"
        'model = "base_model"\n'
        'submodel = "base_submodel"\n'
        'tags = ["baseline"]\n\n'
        "[job]\n"
        'partition = "debug"\n'
        "nodes = 1\n"
        "ntasks = 4\n"
        'walltime = "00:10:00"\n\n'
        "[params]\n"
        "nx = 64\n"
        "ny = 64\n",
        encoding="utf-8",
    )
    return case_dir


def _make_survey(
    survey_dir: Path,
    base_case: str,
    *,
    max_materialized_runs: int = 4,
) -> Path:
    survey_dir.mkdir(parents=True, exist_ok=True)
    (survey_dir / "survey.toml").write_text(
        "[survey]\n"
        'id = "S20260327-test"\n'
        'name = "Test Survey"\n'
        f'base_case = "{base_case}"\n'
        'simulator = "test_sim"\n'
        'launcher = "slurm_srun"\n'
        'phase = "pilot"\n\n'
        "[intent]\n"
        'purpose = "explore"\n'
        'information_gap = "The resolution trend is unknown."\n'
        'created_by = "agent"\n\n'
        "[budget]\n"
        f"max_materialized_runs = {max_materialized_runs}\n"
        "max_core_hours = 10.0\n\n"
        "[axes]\n"
        "nx = [32, 64]\n"
        "ny = [32, 64]\n\n"
        "[naming]\n"
        'display_name = "nx{nx}_ny{ny}"\n\n'
        "[job]\n"
        'partition = "debug"\n'
        "nodes = 1\n"
        "ntasks = 4\n"
        'walltime = "00:10:00"\n',
        encoding="utf-8",
    )
    return survey_dir


def _preview_json(survey_dir: Path, *, limit: int = 50) -> dict[str, object]:
    result = runner.invoke(
        app,
        ["runs", "sweep", str(survey_dir), "--limit", str(limit), "--json"],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


class TestCreate:
    def test_create_success(self, tmp_path: Path) -> None:
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "my_case")
        dest = project_dir / "runs" / "my_survey"

        result = runner.invoke(
            app,
            ["runs", "create", "my_case", "--dest", str(dest)],
        )

        assert result.exit_code == 0, result.output
        assert "Created run:" in result.output
        run_dir = next(path for path in dest.iterdir() if path.is_dir())
        for subdir in ("input", "submit", "work", "analysis", "status"):
            assert (run_dir / subdir).is_dir()
        assert (run_dir / "manifest.toml").exists()
        assert (run_dir / "submit" / "job.sh").exists()

    def test_create_reports_completed_duplicate_as_reused(self, tmp_path: Path) -> None:
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "my_case")
        dest = project_dir / "runs" / "my_survey"
        first = runner.invoke(
            app,
            ["runs", "create", "my_case", "--dest", str(dest)],
        )
        assert first.exit_code == 0, first.output
        run_dir = next(path for path in dest.iterdir() if path.is_dir())
        update_manifest(run_dir, {"run": {"status": "completed"}})

        second = runner.invoke(
            app,
            ["runs", "create", "my_case", "--dest", str(dest)],
        )

        assert second.exit_code == 0, second.output
        assert "Reused equivalent Run:" in second.output
        assert len([path for path in dest.iterdir() if path.is_dir()]) == 1

    def test_create_case_not_found(self, tmp_path: Path) -> None:
        project_dir = _make_project(tmp_path)
        result = runner.invoke(
            app,
            [
                "runs",
                "create",
                "nonexistent_case",
                "--dest",
                str(project_dir / "runs" / "survey1"),
            ],
        )
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_create_no_project(self, tmp_path: Path) -> None:
        dest = tmp_path / "no_project" / "survey"
        dest.mkdir(parents=True)
        result = runner.invoke(
            app,
            ["runs", "create", "some_case", "--dest", str(dest)],
        )
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_create_rejects_removed_survey_alias(self, tmp_path: Path) -> None:
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

    def test_create_run_id_and_semantic_label(self, tmp_path: Path) -> None:
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "my_case")
        dest = project_dir / "runs" / "survey1"

        result = runner.invoke(
            app,
            [
                "runs",
                "create",
                "my_case",
                "--dest",
                str(dest),
                "--label",
                "High resolution",
            ],
        )
        assert result.exit_code == 0, result.output
        assert re.search(r"R\d{8}-\d{4}", result.output)
        assert next(path for path in dest.iterdir() if path.is_dir()).name.endswith(
            "--high-resolution"
        )


class TestSweep:
    def test_sweep_default_is_plan_only_and_does_not_allocate_id(
        self,
        tmp_path: Path,
    ) -> None:
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = _make_survey(
            project_dir / "runs" / "my_survey",
            "base_case",
        )

        result = runner.invoke(app, ["runs", "sweep", str(survey_dir)])

        assert result.exit_code == 0, result.output
        assert "[plan only] 4 candidate points; 0 directories created" in result.output
        assert "p0001" in result.output
        assert "nx32_ny32" in result.output
        assert "--expect-plan sha256:" in result.output
        assert list(survey_dir.glob("*/manifest.toml")) == []
        assert not (project_dir / ".runops" / "run-id-sequence.toml").exists()

    def test_sweep_json_preview_is_bounded(self, tmp_path: Path) -> None:
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = _make_survey(
            project_dir / "runs" / "my_survey",
            "base_case",
        )

        payload = _preview_json(survey_dir, limit=2)

        assert payload["candidate_count"] == 4
        points = payload["points"]
        assert isinstance(points, list)
        assert len(points) == 2
        assert points[0]["ref"] == "p0001"
        assert str(payload["plan_hash"]).startswith("sha256:")
        assert list(survey_dir.glob("*/manifest.toml")) == []

    def test_sweep_apply_materializes_only_selected_point(self, tmp_path: Path) -> None:
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = _make_survey(
            project_dir / "runs" / "my_survey",
            "base_case",
        )
        plan = _preview_json(survey_dir)

        result = runner.invoke(
            app,
            [
                "runs",
                "sweep",
                "--apply",
                "--point",
                "p0002",
                "--expect-plan",
                str(plan["plan_hash"]),
                str(survey_dir),
            ],
        )

        assert result.exit_code == 0, result.output
        assert "created=1, reused=0" in result.output
        assert "p0002 -> R" in result.output
        run_dirs = [path.parent for path in survey_dir.glob("*/manifest.toml")]
        assert len(run_dirs) == 1
        with (run_dirs[0] / "manifest.toml").open("rb") as stream:
            manifest = tomllib.load(stream)
        assert manifest["origin"]["survey"] == "S20260327-test"
        assert manifest["intent"]["phase"] == "pilot"
        assert manifest["identity"]["plan_hash"] == plan["plan_hash"]
        assert manifest["curation"]["review_status"] == "unreviewed"
        assert manifest["storage"] == {"tier": "hot", "form": "full"}

    def test_sweep_apply_requires_hash_and_exactly_one_selection_mode(
        self,
        tmp_path: Path,
    ) -> None:
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = _make_survey(
            project_dir / "runs" / "my_survey",
            "base_case",
        )

        missing_hash = runner.invoke(
            app,
            ["runs", "sweep", "--apply", "--point", "p0001", str(survey_dir)],
        )
        assert missing_hash.exit_code == 1
        assert "--expect-plan" in missing_hash.output

        plan = _preview_json(survey_dir)
        conflicting = runner.invoke(
            app,
            [
                "runs",
                "sweep",
                "--apply",
                "--point",
                "p0001",
                "--all",
                "--expect-plan",
                str(plan["plan_hash"]),
                str(survey_dir),
            ],
        )
        assert conflicting.exit_code == 1
        assert "exactly one" in conflicting.output

    def test_sweep_all_does_not_bypass_budget(self, tmp_path: Path) -> None:
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = _make_survey(
            project_dir / "runs" / "my_survey",
            "base_case",
            max_materialized_runs=2,
        )
        plan = _preview_json(survey_dir)

        result = runner.invoke(
            app,
            [
                "runs",
                "sweep",
                "--apply",
                "--all",
                "--expect-plan",
                str(plan["plan_hash"]),
                str(survey_dir),
            ],
        )
        assert result.exit_code == 1
        assert "materialization cap" in result.output
        assert list(survey_dir.glob("*/manifest.toml")) == []

    def test_dry_run_remains_a_read_only_compatibility_alias(
        self,
        tmp_path: Path,
    ) -> None:
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = _make_survey(
            project_dir / "runs" / "my_survey",
            "base_case",
        )

        result = runner.invoke(app, ["runs", "sweep", "-n", str(survey_dir)])
        assert result.exit_code == 0, result.output
        assert "[plan only]" in result.output
        assert list(survey_dir.glob("*/manifest.toml")) == []

    def test_sweep_errors_for_missing_survey_or_base_case(self, tmp_path: Path) -> None:
        project_dir = _make_project(tmp_path)
        empty = project_dir / "runs" / "empty"
        empty.mkdir()
        missing_survey = runner.invoke(app, ["runs", "sweep", str(empty)])
        assert missing_survey.exit_code == 1
        assert "Error" in missing_survey.output

        bad_case = _make_survey(
            project_dir / "runs" / "bad_case",
            "does-not-exist",
        )
        missing_case = runner.invoke(app, ["runs", "sweep", str(bad_case)])
        assert missing_case.exit_code == 1
        assert "Error" in missing_case.output

    def test_sweep_apply_uses_partial_case_and_job_overrides(
        self,
        tmp_path: Path,
    ) -> None:
        project_dir = _make_project(tmp_path)
        _make_case(project_dir, "base_case")
        survey_dir = project_dir / "runs" / "partial"
        survey_dir.mkdir()
        (survey_dir / "survey.toml").write_text(
            "[survey]\n"
            'id = "S20260327-partial"\n'
            'base_case = "base_case"\n'
            'simulator = "test_sim"\n'
            'launcher = "slurm_srun"\n'
            'phase = "pilot"\n\n'
            "[intent]\n"
            'purpose = "explore"\n\n'
            "[budget]\n"
            "max_materialized_runs = 1\n"
            "max_core_hours = 20.0\n\n"
            "[classification]\n"
            'tags = ["scan"]\n\n'
            "[axes]\n"
            "nx = [32]\n\n"
            "[job]\n"
            'walltime = "02:30:00"\n'
            'modules = ["custom/module"]\n',
            encoding="utf-8",
        )
        plan = _preview_json(survey_dir)
        result = runner.invoke(
            app,
            [
                "runs",
                "sweep",
                "--apply",
                "--point",
                "p0001",
                "--expect-plan",
                str(plan["plan_hash"]),
                str(survey_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        run_dir = next(path.parent for path in survey_dir.glob("*/manifest.toml"))
        with (run_dir / "manifest.toml").open("rb") as stream:
            manifest = tomllib.load(stream)
        assert manifest["classification"] == {
            "model": "base_model",
            "submodel": "base_submodel",
            "tags": ["scan"],
        }
        assert manifest["job"]["partition"] == "debug"
        assert manifest["job"]["ntasks"] == 4
        assert manifest["job"]["walltime"] == "02:30:00"
        assert "module load custom/module" in (run_dir / "submit" / "job.sh").read_text(
            encoding="utf-8"
        )
