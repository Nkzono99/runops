"""Golden-path E2E coverage for the agent-first workflow."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from runops.cli.main import app
from runops.core.discovery import discover_runs
from runops.core.manifest import read_manifest, write_manifest

runner = CliRunner()


def _fake_bootstrap_environment(
    project_dir: Path,
    _sim_names: list[str],
    _runops_package: str,
    created: list[str],
    _skipped: list[str],
    **_kwargs: object,
) -> None:
    """Create a lightweight venv marker without running uv."""
    (project_dir / ".venv" / "Scripts").mkdir(parents=True, exist_ok=True)
    created.append(".venv")


def _init_project(
    monkeypatch: Any,
    project_dir: Path,
    simulators: Sequence[str] = (),
) -> None:
    """Initialize a project while skipping external bootstrap work."""
    monkeypatch.setattr(
        "runops.cli.init._bootstrap_environment",
        _fake_bootstrap_environment,
    )
    result = runner.invoke(
        app,
        [
            "init",
            *simulators,
            "-y",
            "--path",
            str(project_dir),
        ],
    )
    assert result.exit_code == 0, result.output


def _write_generic_simulator_config(project_dir: Path) -> None:
    executable = Path(sys.executable).as_posix()
    (project_dir / "simulators.toml").write_text(
        "[simulators.test_sim]\n"
        'adapter = "generic"\n'
        f'executable = "{executable}"\n'
        'resolver_mode = "local_executable"\n',
        encoding="utf-8",
    )
    (project_dir / "launchers.toml").write_text(
        "[launchers.slurm_srun]\n"
        'kind = "srun"\n'
        'command = "srun"\n'
        "use_slurm_ntasks = true\n",
        encoding="utf-8",
    )


def _write_case(project_dir: Path, case_name: str) -> None:
    case_dir = project_dir / "cases" / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "case.toml").write_text(
        "[case]\n"
        f'name = "{case_name}"\n'
        'simulator = "test_sim"\n'
        'launcher = "slurm_srun"\n'
        'description = "Golden path baseline"\n'
        "\n"
        "[classification]\n"
        'model = "golden"\n'
        'submodel = "baseline"\n'
        'tags = ["golden-path"]\n'
        "\n"
        "[job]\n"
        'partition = "debug"\n'
        "nodes = 1\n"
        "ntasks = 2\n"
        'walltime = "00:05:00"\n'
        "\n"
        "[params]\n"
        "nx = 32\n"
        "ny = 32\n",
        encoding="utf-8",
    )


def _create_experiment(project_dir: Path) -> str:
    result = runner.invoke(
        app,
        [
            "experiments",
            "create",
            "Golden path convergence",
            "--question",
            "Does the baseline response converge?",
            "--intent",
            "explore",
            "--baseline-reason",
            "No compatible prior Run exists.",
            "--exit",
            "Stop after the two-point pilot resolves the trend.",
            "--max-planned-points",
            "2",
            "--max-materialized-runs",
            "2",
            "--max-active-runs",
            "2",
            "--max-core-hours",
            "2",
            "--max-unreviewed-runs",
            "2",
            "--expires-at",
            "2099-01-01T00:00:00+00:00",
            "--path",
            str(project_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    experiment_file = next((project_dir / "experiments").glob("*.toml"))
    return experiment_file.name.split("--", maxsplit=1)[0]


def _write_survey(project_dir: Path, case_name: str, experiment_id: str) -> Path:
    survey_dir = project_dir / "runs" / "golden_survey"
    survey_dir.mkdir(parents=True, exist_ok=True)
    (survey_dir / "survey.toml").write_text(
        "[survey]\n"
        'id = "S20260513-golden"\n'
        'name = "Golden Path Survey"\n'
        f'base_case = "{case_name}"\n'
        'simulator = "test_sim"\n'
        'launcher = "slurm_srun"\n'
        'phase = "pilot"\n'
        f'experiment_id = "{experiment_id}"\n'
        "\n"
        "[intent]\n"
        'purpose = "explore"\n'
        'information_gap = "The resolution trend is unknown."\n'
        'created_by = "golden-path-test"\n'
        "\n"
        "[budget]\n"
        "max_materialized_runs = 2\n"
        "max_core_hours = 2.0\n"
        "\n"
        "[axes]\n"
        "nx = [32, 64]\n"
        "\n"
        "[naming]\n"
        'display_name = "nx{{nx}}"\n'
        "\n"
        "[job]\n"
        'partition = "debug"\n'
        "nodes = 1\n"
        "ntasks = 2\n"
        'walltime = "00:05:00"\n',
        encoding="utf-8",
    )
    return survey_dir


def _mark_completed(run_dir: Path) -> None:
    manifest = read_manifest(run_dir)
    manifest.run["status"] = "completed"
    write_manifest(run_dir, manifest, log_event=False)
    (run_dir / "work" / "exit_code").write_text("0\n", encoding="utf-8")


def test_e2e_agent_golden_path_from_context_to_collection(
    tmp_path: Path,
    monkeypatch: Any,
    mock_init_external_processes: None,
) -> None:
    """Exercise the shortest Agent-facing path from context to analysis collect."""
    del mock_init_external_processes
    project_dir = tmp_path / "golden-project"

    _init_project(monkeypatch, project_dir)
    _write_generic_simulator_config(project_dir)
    _write_case(project_dir, "baseline")
    experiment_id = _create_experiment(project_dir)
    survey_dir = _write_survey(project_dir, "baseline", experiment_id)

    context = runner.invoke(app, ["context", str(project_dir), "--json"])
    assert context.exit_code == 0, context.output
    payload = json.loads(context.output)
    assert payload["project"]["name"] == "golden-project"

    dry_run = runner.invoke(
        app,
        ["runs", "sweep", "--dry-run", "--json", str(survey_dir)],
    )
    assert dry_run.exit_code == 0, dry_run.output
    plan = json.loads(dry_run.output)
    assert plan["candidate_count"] == 2
    assert plan["experiment_id"] == experiment_id
    assert discover_runs(survey_dir) == []

    sweep = runner.invoke(
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
    assert sweep.exit_code == 0, sweep.output
    assert "created=2, reused=0" in sweep.output

    run_dirs = discover_runs(survey_dir)
    assert len(run_dirs) == 2
    assert read_manifest(run_dirs[0]).intent["experiment_id"] == experiment_id

    status = runner.invoke(app, ["runs", "status", "--short", str(survey_dir)])
    assert status.exit_code == 0, status.output
    assert "created" in status.output
    assert "baseline" in status.output

    completed_run = run_dirs[0]
    _mark_completed(completed_run)

    summarize = runner.invoke(app, ["analyze", "summarize", str(completed_run)])
    assert summarize.exit_code == 0, summarize.output
    assert (completed_run / "analysis" / "summary.json").is_file()

    collect = runner.invoke(app, ["analyze", "collect", str(survey_dir)])
    assert collect.exit_code == 0, collect.output
    assert (survey_dir / "summary" / "survey_summary.csv").is_file()
    assert (survey_dir / "summary" / "survey_summary.json").is_file()
