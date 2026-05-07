"""Tests for Codex session-log import into demo events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runops.core.demo import discover_codex_session_log, import_codex_session_log
from runops.core.exceptions import SessionImportError


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            json.dump(record, f, ensure_ascii=False)
            f.write("\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_session_meta(
    path: Path,
    *,
    session_id: str,
    cwd: Path,
    started_at: str,
) -> None:
    _write_jsonl(
        path,
        [
            {
                "timestamp": started_at,
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "timestamp": started_at,
                    "cwd": str(cwd),
                    "source": "vscode",
                },
            }
        ],
    )


def test_import_codex_session_log_normalizes_demo_events(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    source_file = project_root / "src" / "demo.py"
    source_file.parent.mkdir(parents=True)
    session_log = tmp_path / "session.jsonl"
    output_path = tmp_path / "demo-events.jsonl"

    _write_jsonl(
        session_log,
        [
            {
                "timestamp": "2026-04-24T03:07:15.536Z",
                "type": "session_meta",
                "payload": {
                    "id": "sess-123",
                    "cwd": str(project_root),
                    "originator": "codex_vscode",
                    "source": "vscode",
                    "cli_version": "0.1.0",
                    "model_provider": "openai",
                    "base_instructions": {"text": "ignore me"},
                },
            },
            {
                "timestamp": "2026-04-24T03:07:20.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "user_message",
                    "message": "# Context\n\n## My request for Codex:\nデモを作って\n",
                },
            },
            {
                "timestamp": "2026-04-24T03:07:21.000Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": json.dumps(
                        {
                            "cmd": f"sed -n '1,40p' {source_file}",
                            "workdir": str(project_root),
                        },
                        ensure_ascii=False,
                    ),
                    "call_id": "call-exec",
                },
            },
            {
                "timestamp": "2026-04-24T03:07:22.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "exec_command_end",
                    "call_id": "call-exec",
                    "process_id": "12345",
                    "command": [
                        "/usr/bin/bash",
                        "-lc",
                        f"sed -n '1,40p' {source_file}",
                    ],
                    "cwd": str(project_root),
                    "parsed_cmd": [
                        {
                            "type": "read",
                            "cmd": f"sed -n '1,40p' {source_file}",
                            "name": "demo.py",
                            "path": str(source_file),
                        },
                        {
                            "type": "search",
                            "cmd": "rg -n 'demo' src",
                            "query": "demo",
                            "path": "src",
                        },
                    ],
                    "aggregated_output": f"{source_file}: print('demo')\n",
                    "exit_code": 0,
                },
            },
            {
                "timestamp": "2026-04-24T03:07:23.000Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "status": "completed",
                    "name": "apply_patch",
                    "call_id": "call-patch",
                    "input": (
                        "*** Begin Patch\n"
                        f"*** Add File: {project_root / 'notes' / 'demo.md'}\n"
                        "+hello\n"
                        "*** End Patch\n"
                    ),
                },
            },
            {
                "timestamp": "2026-04-24T03:07:24.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "patch_apply_end",
                    "call_id": "call-patch",
                    "stdout": "Success",
                    "stderr": "",
                    "success": True,
                    "changes": {
                        str(project_root / "notes" / "demo.md"): {
                            "type": "create",
                            "unified_diff": "@@ -0,0 +1 @@\n+hello\n",
                            "move_path": None,
                        }
                    },
                },
            },
            {
                "timestamp": "2026-04-24T03:07:25.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "agent_message",
                    "message": "調査して修正しました。",
                    "phase": "commentary",
                },
            },
            {
                "timestamp": "2026-04-24T03:07:26.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": "turn-1",
                    "last_agent_message": "完了しました。",
                    "duration_ms": 1000,
                },
            },
        ],
    )

    result = import_codex_session_log(
        session_log,
        output_path,
        workspace_root=project_root,
    )

    events = _read_jsonl(output_path)
    assert [event["type"] for event in events] == [
        "session_start",
        "user_request",
        "read",
        "search",
        "command",
        "tool_call",
        "create",
        "note",
        "task_complete",
    ]
    assert result.imported_events == 9
    assert result.session_id == "sess-123"
    assert result.event_counts["command"] == 1
    assert events[2]["path"] == "src/demo.py"
    assert events[4]["data"]["command"] == "sed -n '1,40p' src/demo.py"
    assert events[4]["data"]["cwd"] == "."
    assert events[4]["data"]["output_excerpt"] == "src/demo.py: print('demo')"
    assert events[5]["data"]["paths"] == ["notes/demo.md"]
    assert events[6]["path"] == "notes/demo.md"
    assert "diff_excerpt" in events[6]["data"]


def test_import_codex_session_log_reports_invalid_json_line(tmp_path: Path) -> None:
    session_log = tmp_path / "broken.jsonl"
    session_log.write_text('{"type": "session_meta"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(SessionImportError, match="line 2"):
        import_codex_session_log(session_log, tmp_path / "out.jsonl")


def test_discover_codex_session_log_picks_latest_matching_workspace(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    other_root = tmp_path / "other"
    project_root.mkdir()
    other_root.mkdir()
    sessions_root = tmp_path / "codex" / "sessions"

    older = sessions_root / "2026" / "04" / "23" / "rollout-older.jsonl"
    newer = sessions_root / "2026" / "04" / "24" / "rollout-newer.jsonl"
    unrelated = sessions_root / "2026" / "04" / "24" / "rollout-other.jsonl"
    older.parent.mkdir(parents=True, exist_ok=True)
    newer.parent.mkdir(parents=True, exist_ok=True)

    _write_session_meta(
        older,
        session_id="sess-older",
        cwd=project_root,
        started_at="2026-04-23T10:00:00Z",
    )
    _write_session_meta(
        newer,
        session_id="sess-newer",
        cwd=project_root,
        started_at="2026-04-24T10:00:00Z",
    )
    _write_session_meta(
        unrelated,
        session_id="sess-other",
        cwd=other_root,
        started_at="2026-04-24T11:00:00Z",
    )

    discovered = discover_codex_session_log(
        workspace_root=project_root,
        sessions_root=sessions_root,
    )

    assert discovered.path == newer
    assert discovered.session_id == "sess-newer"
    assert discovered.cwd == project_root.resolve()
    assert discovered.started_at == "2026-04-24T10:00:00Z"


def test_discover_codex_session_log_reports_no_match(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    sessions_root = tmp_path / "codex" / "sessions"
    session_log = sessions_root / "2026" / "04" / "24" / "rollout-other.jsonl"
    session_log.parent.mkdir(parents=True, exist_ok=True)

    _write_session_meta(
        session_log,
        session_id="sess-other",
        cwd=tmp_path / "other",
        started_at="2026-04-24T11:00:00Z",
    )

    with pytest.raises(SessionImportError, match="no Codex session logs found"):
        discover_codex_session_log(
            workspace_root=project_root,
            sessions_root=sessions_root,
        )
