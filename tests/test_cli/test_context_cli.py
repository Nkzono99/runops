"""Tests for the ``runops context`` CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


def test_context_outputs_json_bundle(tmp_path: Path) -> None:
    context_data = {
        "project": {"name": "demo-project", "root": str(tmp_path)},
        "status": "ok",
    }

    with (
        patch("runops.cli.context.find_project_root", return_value=tmp_path),
        patch(
            "runops.application.context.build_project_context",
            return_value=context_data,
        ),
    ):
        result = runner.invoke(app, ["context", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == context_data


def test_context_no_json_outputs_human_summary(tmp_path: Path) -> None:
    context_data = {
        "project": {"name": "demo-project", "root": str(tmp_path)},
        "campaign": {"hypothesis": "density controls stability"},
        "research_agenda": {
            "exists": True,
            "path": "research/agenda.md",
            "is_template": False,
            "current_decision": "sync smoke run before rerun",
            "next_actions_count": 2,
        },
        "notes": {"latest_path": "notes/2026-05-08.md"},
        "simulators": ["emses", "beach"],
        "runs": {"total": 3, "running": 1, "failed": 2},
        "recent_failures": [
            {"run_id": "R20260409-0002", "reason": "timeout"},
            {"run_id": "R20260409-0003", "reason": "oom"},
        ],
    }

    with (
        patch("runops.cli.context.find_project_root", return_value=tmp_path),
        patch(
            "runops.application.context.build_project_context",
            return_value=context_data,
        ),
    ):
        result = runner.invoke(app, ["context", "--no-json", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Project: demo-project" in result.output
    assert f"Root: {tmp_path}" in result.output
    assert "Hypothesis: density controls stability" in result.output
    assert (
        "Research agenda: research/agenda.md (ready, next_actions=2)" in result.output
    )
    assert "Current decision: sync smoke run before rerun" in result.output
    assert "Latest note: notes/2026-05-08.md" in result.output
    assert "Simulators: emses, beach" in result.output
    assert "Runs: total=3, running=1, failed=2" in result.output
    assert "Recent failures (2):" in result.output
    assert "R20260409-0002: timeout" in result.output
    assert "R20260409-0003: oom" in result.output
