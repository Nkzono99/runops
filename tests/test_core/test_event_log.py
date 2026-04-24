"""Tests for structured event logging."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runops.core.actions import ActionStatus
from runops.core.actions import (
    create_run as create_run_action,
)
from runops.core.actions import (
    save_insight as save_insight_action,
)
from runops.core.event_log import (
    EVENT_LOG_ENV_VAR,
    EVENT_LOG_MODE_ENV_VAR,
    clear_event_logging,
    configure_event_logging,
    emit_artifact_event,
    emit_event,
)


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


def test_emit_event_skips_verbose_records_in_summary_mode(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    configure_event_logging(
        log_path,
        mode="summary-only",
        session_id="sess-test",
        actor="test-suite",
    )
    try:
        emit_event("action_start", action="demo", summary="Start demo")
        emit_artifact_event(
            tmp_path / "manifest.toml",
            operation="create",
            artifact_kind="manifest",
            summary="Create manifest.toml",
        )
    finally:
        clear_event_logging()

    events = _read_events(log_path)
    assert [event["type"] for event in events] == ["action_start"]
    assert events[0]["session_id"] == "sess-test"
    assert events[0]["actor"] == "test-suite"


def test_create_run_action_logs_artifacts_when_verbose(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _create_project_with_case(tmp_path)
    log_path = tmp_path / "events.jsonl"
    clear_event_logging()
    monkeypatch.setenv(EVENT_LOG_ENV_VAR, str(log_path))
    monkeypatch.setenv(EVENT_LOG_MODE_ENV_VAR, "verbose")

    result = create_run_action(tmp_path, "my_case")

    clear_event_logging()
    assert result.status is ActionStatus.SUCCESS
    events = _read_events(log_path)
    event_types = [event["type"] for event in events]
    assert "action_start" in event_types
    assert "action_finish" in event_types

    run_dir = Path(str(result.data["run_dir"]))
    artifact_paths = {
        event.get("path", "") for event in events if event["type"] == "artifact_write"
    }
    assert str(run_dir / "input" / "params.json") in artifact_paths
    assert str(run_dir / "submit" / "job.sh") in artifact_paths
    assert str(run_dir / "manifest.toml") in artifact_paths
    assert len({event["session_id"] for event in events}) == 1


def test_save_insight_action_redacts_content_in_action_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    log_path = tmp_path / "events.jsonl"
    clear_event_logging()
    monkeypatch.setenv(EVENT_LOG_ENV_VAR, str(log_path))
    monkeypatch.setenv(EVENT_LOG_MODE_ENV_VAR, "summary-only")

    result = save_insight_action(
        tmp_path,
        name="demo-note",
        content="secret demo note",
        insight_type="result",
    )

    clear_event_logging()
    assert result.status is ActionStatus.SUCCESS
    events = _read_events(log_path)
    assert [event["type"] for event in events] == ["action_start", "action_finish"]
    start_event = events[0]
    redacted = start_event["data"]["params"]["content"]
    assert redacted.startswith("<redacted:")
    assert redacted.endswith(" chars>")
