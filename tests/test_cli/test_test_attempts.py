"""CLI tests for smoke/debug TestAttempts outside the Run namespace."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


def _project(root: Path) -> Path:
    (root / "runops.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    case_dir = root / "cases" / "base"
    (case_dir / "input").mkdir(parents=True)
    (case_dir / "case.toml").write_text(
        '[case]\nname = "base"\nsimulator = "generic"\nlauncher = "srun"\n',
        encoding="utf-8",
    )
    (case_dir / "input" / "config.toml").write_text("steps = 1\n", encoding="utf-8")
    (root / "runs").mkdir()
    return root


def test_test_help_lists_isolated_lifecycle_commands() -> None:
    result = runner.invoke(app, ["test", "--help"])

    assert result.exit_code == 0
    for command in ["smoke", "debug", "list", "record", "clean"]:
        assert command in result.output


def test_smoke_prepares_receipt_without_run_or_slurm_submission(tmp_path: Path) -> None:
    project = _project(tmp_path)

    result = runner.invoke(
        app,
        ["test", "smoke", "base", "--path", str(project)],
    )

    assert result.exit_code == 0, result.output
    assert "T" in result.output
    assert "identity incomplete; cache disabled" in result.output
    assert "No Slurm job was submitted" in result.output
    assert len(list((project / ".runops/test-runs").glob("T*/test-receipt.toml"))) == 1
    assert not list((project / "runs").rglob("manifest.toml"))


def test_debug_record_and_list_json(tmp_path: Path) -> None:
    project = _project(tmp_path)
    created = runner.invoke(
        app,
        ["test", "debug", "base", "--path", str(project)],
    )
    attempt_id = next((project / ".runops/test-runs").glob("T*")).name

    recorded = runner.invoke(
        app,
        [
            "test",
            "record",
            attempt_id,
            "--result",
            "failed",
            "--observation",
            "startup failure",
            "--path",
            str(project),
        ],
    )
    listed = runner.invoke(
        app,
        ["test", "list", str(project), "--json"],
    )

    assert created.exit_code == 0, created.output
    assert recorded.exit_code == 0, recorded.output
    payload = json.loads(listed.stdout)
    assert payload[0]["id"] == attempt_id
    assert payload[0]["kind"] == "debug"
    assert payload[0]["state"] == "failed"
    assert payload[0]["adapter_version"].startswith("sha256:")
    assert payload[0]["observation"] == "startup failure"


def test_cache_hit_reuses_existing_passed_directory_and_reports_age(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    identity_options = [
        "--source-commit",
        "abc123",
        "--executable-hash",
        "sha256:" + "1" * 64,
        "--adapter-version",
        "1.2.3",
    ]
    first = runner.invoke(
        app,
        [
            "test",
            "smoke",
            "base",
            "--path",
            str(project),
            *identity_options,
        ],
    )
    attempt_id = next((project / ".runops/test-runs").glob("T*")).name
    recorded = runner.invoke(
        app,
        [
            "test",
            "record",
            attempt_id,
            "--result",
            "passed",
            "--path",
            str(project),
        ],
    )

    cached = runner.invoke(
        app,
        [
            "test",
            "smoke",
            "base",
            "--path",
            str(project),
            *identity_options,
        ],
    )

    assert first.exit_code == 0, first.output
    assert recorded.exit_code == 0, recorded.output
    assert cached.exit_code == 0, cached.output
    assert "SKIPPED: equivalent" in cached.output
    assert attempt_id in cached.output
    assert "Cache age:" in cached.output
    assert len(list((project / ".runops/test-runs").glob("T*"))) == 1


def test_clean_refuses_prepared_attempt(tmp_path: Path) -> None:
    project = _project(tmp_path)
    runner.invoke(app, ["test", "smoke", "base", "--path", str(project)])

    result = runner.invoke(
        app,
        ["test", "clean", "--older-than-days", "0", "--path", str(project)],
    )

    assert result.exit_code == 2
    assert "prepared" in result.output
