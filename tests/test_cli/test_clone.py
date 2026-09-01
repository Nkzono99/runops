"""Tests for runops runs clone command."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import tomli_w
from typer.testing import CliRunner

from runops.cli.main import app

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

runner = CliRunner()


def _create_run(
    parent: Path,
    run_id: str,
    *,
    status: str = "completed",
    params: dict[str, Any] | None = None,
    walltime: str = "00:10:00",
) -> Path:
    """Create a minimal run directory with manifest.toml and input files."""
    run_dir = parent / run_id
    run_dir.mkdir(parents=True)
    for sub in ("input", "submit", "work", "analysis", "status"):
        (run_dir / sub).mkdir()

    # Write a sample input file
    (run_dir / "input" / "config.txt").write_text("nx=64\nny=64\n")

    # Write a sample job script
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n"
        f"#SBATCH --job-name={run_id}\n"
        f"#SBATCH --output={run_dir}/work/%j.out\n"
        f"cd {run_dir}\n"
        "echo hello\n"
    )

    manifest: dict[str, Any] = {
        "run": {
            "id": run_id,
            "display_name": "test run",
            "status": status,
            "last_slurm_state": "COMPLETED",
        },
        "path": {"run_dir": str(run_dir)},
        "origin": {
            "case": "test_case",
            "survey": "",
            "parent_run": "",
        },
        "simulator": {
            "name": "test_sim",
            "adapter": "test_adapter",
        },
        "job": {
            "scheduler": "slurm",
            "job_id": "12345",
            "partition": "debug",
            "walltime": walltime,
            "submitted_at": "2026-03-27T00:00:00+00:00",
            "attempt": 1,
            "attempts": [{"job_id": "12345", "submitted_at": "old"}],
        },
    }
    if params:
        manifest["params_snapshot"] = params

    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(manifest, f)
    return run_dir


def test_clone_basic(tmp_path: Path) -> None:
    source = _create_run(tmp_path, "R20260327-0001")

    result = runner.invoke(
        app,
        ["runs", "clone", str(source), "--dest", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Cloned R20260327-0001" in result.output

    # Find the new run directory
    new_dirs = [d for d in tmp_path.iterdir() if d.is_dir() and d != source]
    assert len(new_dirs) == 1

    new_dir = new_dirs[0]
    assert (new_dir / "manifest.toml").exists()
    assert (new_dir / "input" / "config.txt").exists()
    assert (new_dir / "input" / "config.txt").read_text() == "nx=64\nny=64\n"
    assert (new_dir / "submit" / "job.sh").exists()
    job_script = (new_dir / "submit" / "job.sh").read_text()
    assert "#SBATCH" in job_script
    assert str(source) not in job_script
    assert "R20260327-0001" not in job_script
    assert str(new_dir) in job_script

    with open(new_dir / "manifest.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["path"]["run_dir"] == str(new_dir)
    assert data["job"]["job_id"] == ""
    assert data["job"]["submitted_at"] == ""
    assert "attempts" not in data["job"]
    assert "last_slurm_state" not in data["run"]


def test_clone_sets_parent_run(tmp_path: Path) -> None:
    source = _create_run(tmp_path, "R20260327-0001")

    result = runner.invoke(
        app,
        ["runs", "clone", str(source), "--dest", str(tmp_path)],
    )
    assert result.exit_code == 0

    new_dirs = [d for d in tmp_path.iterdir() if d.is_dir() and d != source]
    new_dir = new_dirs[0]

    with open(new_dir / "manifest.toml", "rb") as f:
        data = tomllib.load(f)

    assert data["origin"]["parent_run"] == "R20260327-0001"
    assert data["run"]["status"] == "created"


def test_clone_with_set_params(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    _make_case(project_dir, "test_case")
    source = _create_run(
        project_dir / "runs",
        "R20260327-0001",
        params={"nx": 64, "ny": 64},
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "clone",
            str(source),
            "--dest",
            str(project_dir / "runs"),
            "--set",
            "nx=128",
        ],
    )
    assert result.exit_code == 0, result.output

    new_dirs = [
        d for d in (project_dir / "runs").iterdir() if d.is_dir() and d != source
    ]
    new_dir = new_dirs[0]

    with open(new_dir / "manifest.toml", "rb") as f:
        data = tomllib.load(f)

    assert data["params_snapshot"]["nx"] == "128"
    assert data["params_snapshot"]["ny"] == 64
    assert data["origin"]["parent_run"] == "R20260327-0001"
    assert data["variation"]["changed_keys"] == ["nx"]

    params_json = json.loads((new_dir / "input" / "params.json").read_text())
    assert params_json["nx"] == "128"
    assert params_json["ny"] == 64


def test_clone_invalid_set_format(tmp_path: Path) -> None:
    source = _create_run(tmp_path, "R20260327-0001")

    result = runner.invoke(
        app,
        [
            "runs",
            "clone",
            str(source),
            "--dest",
            str(tmp_path),
            "--set",
            "badparam",
        ],
    )
    assert result.exit_code == 1
    assert "invalid --set format" in result.output


def test_clone_nonexistent_run() -> None:
    result = runner.invoke(app, ["runs", "clone", "/nonexistent/run"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_clone_rejects_non_completed_source(tmp_path: Path) -> None:
    source = _create_run(tmp_path, "R20260327-0001", status="created")

    result = runner.invoke(
        app,
        ["runs", "clone", str(source), "--dest", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "completed-equivalent snapshot" in result.output
    assert [path for path in tmp_path.iterdir() if path.is_dir()] == [source]


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal project structure for clone regeneration."""
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


def test_managed_clone_rejects_strict_discovery_pruned_destination(
    tmp_path: Path,
) -> None:
    project_dir = _make_project(tmp_path)
    source = _create_run(project_dir / "runs", "R20260327-0001")
    destination = project_dir / "runs" / ".tmp-hidden"

    result = runner.invoke(
        app,
        ["runs", "clone", str(source), "--dest", str(destination)],
    )

    assert result.exit_code == 1
    assert "transaction directory" in result.output
    assert not destination.exists()


def test_managed_clone_rejects_destination_inside_formal_run(
    tmp_path: Path,
) -> None:
    project_dir = _make_project(tmp_path)
    source = _create_run(project_dir / "runs", "R20260327-0001")

    result = runner.invoke(
        app,
        ["runs", "clone", str(source), "--dest", str(source / "derived")],
    )

    assert result.exit_code == 1
    assert "inside existing formal Run" in result.output
    assert not (source / "derived").exists()


def test_ownerless_managed_clone_obeys_project_unreviewed_cap(
    tmp_path: Path,
) -> None:
    project_dir = _make_project(tmp_path)
    (project_dir / "runops.toml").write_text(
        "[project]\n"
        'name = "test-project"\n\n'
        "[experiments.policy]\n"
        "require_experiment = false\n"
        "max_unreviewed_completed_runs = 1\n",
        encoding="utf-8",
    )
    source = _create_run(project_dir / "runs", "R20260327-0001")

    result = runner.invoke(
        app,
        ["runs", "clone", str(source), "--dest", str(project_dir / "runs")],
    )

    assert result.exit_code == 1
    assert "project-wide unreviewed completed Run backlog" in result.output
    assert sorted((project_dir / "runs").glob("*/manifest.toml")) == [
        source / "manifest.toml"
    ]


def test_ownerless_managed_clone_rejects_non_positive_walltime(
    tmp_path: Path,
) -> None:
    project_dir = _make_project(tmp_path)
    source = _create_run(
        project_dir / "runs",
        "R20260327-0001",
        walltime="00:00:00",
    )

    result = runner.invoke(
        app,
        ["runs", "clone", str(source), "--dest", str(project_dir / "runs")],
    )

    assert result.exit_code == 1
    assert "invalid job.walltime" in result.output
    assert sorted((project_dir / "runs").glob("*/manifest.toml")) == [
        source / "manifest.toml"
    ]


def test_external_source_cannot_bypass_managed_destination_experiment_policy(
    tmp_path: Path,
) -> None:
    source = _create_run(tmp_path / "external", "R20260327-0001")
    project_dir = tmp_path / "managed"
    project_dir.mkdir()
    _make_project(project_dir)
    (project_dir / "runops.toml").write_text(
        "[project]\n"
        'name = "test-project"\n\n'
        "[experiments.policy]\n"
        "require_experiment = true\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["runs", "clone", str(source), "--dest", str(project_dir / "runs")],
    )

    assert result.exit_code == 1
    assert "requires --experiment" in result.output
    assert list((project_dir / "runs").iterdir()) == []


def _make_case(project_dir: Path, case_name: str) -> Path:
    """Create a minimal case directory with case.toml."""
    case_dir = project_dir / "cases" / case_name
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text(
        f"[case]\n"
        f'name = "{case_name}"\n'
        f'simulator = "test_sim"\n'
        f'launcher = "slurm_srun"\n'
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
