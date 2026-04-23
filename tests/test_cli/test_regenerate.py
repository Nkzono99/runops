"""Tests for `runops runs regenerate`."""

from __future__ import annotations

import sys
from pathlib import Path

from typer.testing import CliRunner

from runops.cli.main import app

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

runner = CliRunner()


def _make_project(tmp_path: Path) -> Path:
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


def _make_case(project_dir: Path, case_name: str, *, input_text: str) -> Path:
    case_dir = project_dir / "cases" / case_name
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text(
        f"[case]\n"
        f'name = "{case_name}"\n'
        f'simulator = "test_sim"\n'
        f'launcher = "slurm_srun"\n'
        f'description = "regen test"\n'
        f"\n"
        f"[job]\n"
        f'partition = "debug"\n'
        f"nodes = 1\n"
        f"ntasks = 1\n"
        f'walltime = "00:10:00"\n'
        f"\n"
        f"[params]\n"
        f"modeww = -2\n"
    )
    input_dir = case_dir / "input"
    input_dir.mkdir()
    (input_dir / "plasma.toml").write_text(input_text, encoding="utf-8")
    return case_dir


def _create_one_run(project_dir: Path, case_name: str) -> Path:
    dest = project_dir / "runs" / case_name
    result = runner.invoke(app, ["runs", "create", case_name, "--dest", str(dest)])
    assert result.exit_code == 0, result.output
    run_dirs = [d for d in dest.iterdir() if d.is_dir()]
    assert len(run_dirs) == 1
    return run_dirs[0]


def test_regenerate_detects_case_template_change(tmp_path: Path) -> None:
    """After editing the case template, regenerate updates input/ in place."""
    project_dir = _make_project(tmp_path)
    _make_case(project_dir, "cA", input_text="modeww = -2\n")
    run_dir = _create_one_run(project_dir, "cA")

    # Sanity: initial input reflects original template
    original_input = (run_dir / "input" / "plasma.toml").read_text(encoding="utf-8")
    assert "modeww = -2" in original_input

    # Edit the case template
    (project_dir / "cases" / "cA" / "input" / "plasma.toml").write_text(
        "modeww = -5\n", encoding="utf-8"
    )

    # Run regenerate
    result = runner.invoke(app, ["runs", "regenerate", str(run_dir)])
    assert result.exit_code == 0, result.output
    assert "Regenerated input" in result.output
    assert "plasma.toml" in result.output

    # Input file now reflects the new template
    new_input = (run_dir / "input" / "plasma.toml").read_text(encoding="utf-8")
    assert "modeww = -5" in new_input

    # manifest and analysis/ preserved
    assert (run_dir / "manifest.toml").is_file()
    assert (run_dir / "analysis").is_dir()


def test_regenerate_dry_run_does_not_modify(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    _make_case(project_dir, "cB", input_text="modeww = -2\n")
    run_dir = _create_one_run(project_dir, "cB")

    (project_dir / "cases" / "cB" / "input" / "plasma.toml").write_text(
        "modeww = -5\n", encoding="utf-8"
    )
    original = (run_dir / "input" / "plasma.toml").read_text(encoding="utf-8")

    result = runner.invoke(app, ["runs", "regenerate", str(run_dir), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
    # File unchanged
    assert (run_dir / "input" / "plasma.toml").read_text(encoding="utf-8") == original


def test_regenerate_rejects_unsafe_state(tmp_path: Path) -> None:
    """Submitted / running / completed runs must not be regenerated."""
    import tomli_w

    project_dir = _make_project(tmp_path)
    _make_case(project_dir, "cC", input_text="x=1\n")
    run_dir = _create_one_run(project_dir, "cC")

    # Bump manifest state to 'running'
    manifest_path = run_dir / "manifest.toml"

    with open(manifest_path, "rb") as f:
        manifest = tomllib.load(f)
    manifest["run"]["status"] = "running"
    with open(manifest_path, "wb") as f:
        tomli_w.dump(manifest, f)

    result = runner.invoke(app, ["runs", "regenerate", str(run_dir)])
    assert result.exit_code == 1
    assert "cannot regenerate" in result.output.lower()


def test_regenerate_warns_when_work_exists(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    _make_case(project_dir, "cD", input_text="x=1\n")
    run_dir = _create_one_run(project_dir, "cD")

    # Populate work/ with a file
    (run_dir / "work" / "leftover.dat").write_text("stale", encoding="utf-8")

    # Change template so regenerate has work to do
    (project_dir / "cases" / "cD" / "input" / "plasma.toml").write_text(
        "x=2\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["runs", "regenerate", str(run_dir)])
    assert result.exit_code == 0, result.output
    assert "work/" in result.output  # warning printed to stderr
