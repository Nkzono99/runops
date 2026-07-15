"""CLI tests for structured event logging."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


def _read_events(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _create_project_with_case(project_root: Path) -> None:
    (project_root / "runops.toml").write_text(
        '[project]\nname = "test-project"\n',
        encoding="utf-8",
    )
    (project_root / "simulators.toml").write_text(
        "[simulators.test_sim]\n"
        'adapter = "generic"\n'
        'executable = "echo"\n'
        'resolver_mode = "package"\n',
        encoding="utf-8",
    )
    (project_root / "launchers.toml").write_text(
        "[launchers.slurm_srun]\n"
        'kind = "srun"\n'
        'command = "srun"\n'
        "use_slurm_ntasks = true\n",
        encoding="utf-8",
    )
    case_dir = project_root / "cases" / "my_case"
    case_dir.mkdir(parents=True)
    (project_root / "runs").mkdir()
    (case_dir / "case.toml").write_text(
        "[case]\n"
        'name = "my_case"\n'
        'simulator = "test_sim"\n'
        'launcher = "slurm_srun"\n'
        "\n"
        "[job]\n"
        'partition = "debug"\n'
        "nodes = 1\n"
        "ntasks = 2\n"
        'walltime = "00:10:00"\n'
        "\n"
        "[params]\n"
        "nx = 64\n"
        "ny = 64\n",
        encoding="utf-8",
    )


def test_help_shows_event_log_options() -> None:
    result = runner.invoke(
        app,
        ["--help"],
        env={"COLUMNS": "200", "TERM": "dumb", "NO_COLOR": "1"},
    )
    assert result.exit_code == 0
    assert "event-log" in result.output
    assert "event-log-mode" in result.output


def test_runs_create_writes_event_log_from_global_options(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _create_project_with_case(tmp_path)
    log_path = tmp_path / "events.jsonl"
    (tmp_path / "research" / "journal").mkdir(parents=True)
    (tmp_path / "research" / "journal" / "active.md").write_text(
        "# Research Journal\n\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [
            "--event-log",
            str(log_path),
            "--event-log-mode",
            "verbose",
            "runs",
            "create",
            "my_case",
        ],
    )

    assert result.exit_code == 0
    events = _read_events(log_path)
    event_types = [event["type"] for event in events]
    assert event_types[0] == "cli_invocation"
    assert "action_start" in event_types
    assert "action_finish" in event_types
    assert any(
        event.get("path", "").endswith("manifest.toml")
        for event in events
        if event["type"] == "artifact_write"
    )


def test_cli_invocation_never_persists_raw_argv_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "test-project"\n',
        encoding="utf-8",
    )
    log_path = tmp_path / "events.jsonl"
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [
            "--event-log",
            str(log_path),
            "research",
            "append",
            "Secret note",
            "top-secret-value",
        ],
    )

    assert result.exit_code == 0, result.output
    log_text = log_path.read_text(encoding="utf-8")
    assert "top-secret-value" not in log_text
    invocation = _read_events(log_path)[0]
    assert invocation["type"] == "cli_invocation"
    assert invocation["data"] == {"program": "runo"}
    assert "argv" not in invocation["data"]
