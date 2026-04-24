"""Tests for demo replay CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            json.dump(record, f, ensure_ascii=False)
            f.write("\n")


def test_demo_help_shows_import_command() -> None:
    result = runner.invoke(app, ["demo", "--help"])
    assert result.exit_code == 0
    assert "import-codex-session" in result.output
    assert "render-replay" in result.output
    assert "build-codex-replay" in result.output


def test_import_codex_session_command_writes_demo_events(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    session_log = tmp_path / "session.jsonl"
    out = tmp_path / "demo-events.jsonl"
    source_file = project_root / "notes" / "todo.md"
    source_file.parent.mkdir(parents=True)

    _write_jsonl(
        session_log,
        [
            {
                "timestamp": "2026-04-24T03:07:15.536Z",
                "type": "session_meta",
                "payload": {
                    "id": "sess-cli",
                    "cwd": str(project_root),
                    "source": "vscode",
                },
            },
            {
                "timestamp": "2026-04-24T03:07:22.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "exec_command_end",
                    "call_id": "call-exec",
                    "command": [
                        "/usr/bin/bash",
                        "-lc",
                        f"sed -n '1,20p' {source_file}",
                    ],
                    "cwd": str(project_root),
                    "parsed_cmd": [
                        {
                            "type": "read",
                            "cmd": f"sed -n '1,20p' {source_file}",
                            "name": "todo.md",
                            "path": str(source_file),
                        }
                    ],
                    "aggregated_output": "todo",
                    "exit_code": 0,
                },
            },
        ],
    )

    result = runner.invoke(
        app,
        [
            "demo",
            "import-codex-session",
            str(session_log),
            "--out",
            str(out),
            "--workspace-root",
            str(project_root),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Imported 3 demo events" in result.output
    assert "Session: sess-cli" in result.output
    events = [
        json.loads(line)
        for line in out.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["type"] for event in events] == [
        "session_start",
        "read",
        "command",
    ]


def test_render_replay_command_writes_html(tmp_path: Path) -> None:
    events_path = tmp_path / "demo-events.jsonl"
    out = tmp_path / "replay.html"
    _write_jsonl(
        events_path,
        [
            {
                "t": "2026-04-24T03:07:20Z",
                "type": "read",
                "actor": "agent",
                "summary": "Read campaign.toml",
                "path": "campaign.toml",
                "data": {"command": "cat campaign.toml"},
            },
            {
                "t": "2026-04-24T03:07:24Z",
                "type": "command",
                "actor": "agent",
                "summary": "Execute sweep",
                "data": {"command": "runo runs sweep cases/base"},
            },
        ],
    )

    result = runner.invoke(
        app,
        [
            "demo",
            "render-replay",
            str(events_path),
            "--out",
            str(out),
            "--title",
            "Replay Demo",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Rendered replay UI" in result.output
    html = out.read_text(encoding="utf-8")
    assert "<title>Replay Demo</title>" in html
    assert "campaign.toml" in html


def test_build_codex_replay_command_creates_events_and_html(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    session_log = tmp_path / "session.jsonl"
    html_out = tmp_path / "replay.html"
    events_out = tmp_path / "demo-events.jsonl"
    source_file = project_root / "cases" / "base" / "survey.toml"
    source_file.parent.mkdir(parents=True)

    _write_jsonl(
        session_log,
        [
            {
                "timestamp": "2026-04-24T03:07:15.536Z",
                "type": "session_meta",
                "payload": {
                    "id": "sess-build",
                    "cwd": str(project_root),
                    "source": "vscode",
                },
            },
            {
                "timestamp": "2026-04-24T03:07:22.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "exec_command_end",
                    "call_id": "call-exec",
                    "command": [
                        "/usr/bin/bash",
                        "-lc",
                        f"sed -n '1,20p' {source_file}",
                    ],
                    "cwd": str(project_root),
                    "parsed_cmd": [
                        {
                            "type": "read",
                            "cmd": f"sed -n '1,20p' {source_file}",
                            "name": "survey.toml",
                            "path": str(source_file),
                        }
                    ],
                    "aggregated_output": "id = 'demo'",
                    "exit_code": 0,
                },
            },
        ],
    )

    result = runner.invoke(
        app,
        [
            "demo",
            "build-codex-replay",
            str(session_log),
            "--out",
            str(html_out),
            "--events-out",
            str(events_out),
            "--workspace-root",
            str(project_root),
            "--title",
            "Build Replay",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Imported 3 events" in result.output
    assert "Rendered replay UI" in result.output
    assert events_out.is_file()
    assert html_out.is_file()
    html = html_out.read_text(encoding="utf-8")
    assert "<title>Build Replay</title>" in html
    assert "survey.toml" in html


def test_build_codex_replay_command_auto_discovers_session_log(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    sessions_root = tmp_path / "codex" / "sessions"
    session_log = sessions_root / "2026" / "04" / "24" / "rollout-demo.jsonl"
    session_log.parent.mkdir(parents=True, exist_ok=True)
    html_out = tmp_path / "replay.html"
    events_out = tmp_path / "demo-events.jsonl"
    source_file = project_root / "campaign.toml"

    _write_jsonl(
        session_log,
        [
            {
                "timestamp": "2026-04-24T03:07:15.536Z",
                "type": "session_meta",
                "payload": {
                    "id": "sess-auto",
                    "cwd": str(project_root),
                    "source": "vscode",
                },
            },
            {
                "timestamp": "2026-04-24T03:07:22.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "exec_command_end",
                    "call_id": "call-exec",
                    "command": [
                        "/usr/bin/bash",
                        "-lc",
                        f"sed -n '1,20p' {source_file}",
                    ],
                    "cwd": str(project_root),
                    "parsed_cmd": [
                        {
                            "type": "read",
                            "cmd": f"sed -n '1,20p' {source_file}",
                            "name": "campaign.toml",
                            "path": str(source_file),
                        }
                    ],
                    "aggregated_output": "title = 'demo'",
                    "exit_code": 0,
                },
            },
        ],
    )

    result = runner.invoke(
        app,
        [
            "demo",
            "build-codex-replay",
            "--out",
            str(html_out),
            "--events-out",
            str(events_out),
            "--workspace-root",
            str(project_root),
            "--sessions-root",
            str(sessions_root),
            "--title",
            "Auto Replay",
        ],
    )

    assert result.exit_code == 0, result.output
    assert f"Auto-discovered session log: {session_log}" in result.output
    assert "Imported 3 events" in result.output
    assert html_out.is_file()
    assert events_out.is_file()
