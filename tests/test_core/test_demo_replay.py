"""Tests for replay UI generation from demo events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runops.core.demo_replay import build_demo_replay_ui, load_demo_replay_bundle
from runops.core.exceptions import DemoReplayError


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            json.dump(record, f, ensure_ascii=False)
            f.write("\n")


def test_load_demo_replay_bundle_normalizes_event_counts(tmp_path: Path) -> None:
    events_path = tmp_path / "demo-events.jsonl"
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
                "type": "create",
                "actor": "agent",
                "summary": "Create survey",
                "path": "cases/base/survey.toml",
                "data": {"diff_excerpt": "+alpha = 1"},
            },
            {
                "t": "2026-04-24T03:07:28Z",
                "type": "command",
                "actor": "agent",
                "summary": "Execute sweep",
                "data": {"command": "runo runs sweep cases/base"},
            },
        ],
    )

    bundle = load_demo_replay_bundle(events_path)

    assert bundle.event_count == 3
    assert bundle.file_count == 2
    assert bundle.actor_count == 1
    assert bundle.chapter_count == 2
    assert bundle.event_types == {"read": 1, "create": 1, "command": 1}
    assert bundle.title == "Demo Events"
    assert bundle.subtitle == "3 events across 2 files from demo-events.jsonl"
    assert [chapter.title for chapter in bundle.chapters] == [
        "Inspect campaign.toml",
        "Run runo runs sweep cases/base",
    ]
    assert bundle.events[0]["chapter_index"] == 1
    assert bundle.events[2]["chapter_index"] == 2


def test_build_demo_replay_ui_writes_self_contained_html(tmp_path: Path) -> None:
    events_path = tmp_path / "demo-events.jsonl"
    output_path = tmp_path / "replay.html"
    _write_jsonl(
        events_path,
        [
            {
                "id": "evt-1",
                "t": "2026-04-24T03:07:20Z",
                "type": "read",
                "actor": "agent",
                "summary": "Read campaign.toml",
                "path": "campaign.toml",
                "data": {"command": "cat campaign.toml"},
            },
            {
                "id": "evt-2",
                "t": "2026-04-24T03:07:24Z",
                "type": "note",
                "actor": "agent",
                "summary": "Need a new survey",
                "data": {"message": "Need a new survey"},
            },
        ],
    )

    result = build_demo_replay_ui(
        events_path,
        output_path,
        title="Lab Sweep Replay",
        subtitle="A compact replay for the demo",
    )

    html = output_path.read_text(encoding="utf-8")
    assert result.event_count == 2
    assert result.file_count == 1
    assert "<title>Lab Sweep Replay</title>" in html
    assert "RunOps Demo Replay" in html
    assert "Lab Sweep Replay" in html
    assert "A compact replay for the demo" in html
    assert "campaign.toml" in html
    assert '"eventCount": 2' in html
    assert '"chapterCount": 1' in html
    assert '"type": "note"' in html
    assert "function timelineBuckets()" in html
    assert "function treeEvents(index)" in html
    assert (
        "grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr));"
        in html
    )
    assert "overflow-x: hidden;" in html
    assert '<option value="64">64x</option>' in html
    assert "Math.max(20" in html
    assert 'id="tree-scope-current"' in html
    assert 'id="tree-scope-all"' in html
    assert "function buildNestedTree(index)" in html
    assert "function renderTreeNode(node, options)" in html
    assert "tree-folder-button" in html
    assert "(project root)" in html


def test_task_start_does_not_force_new_chapter(tmp_path: Path) -> None:
    events_path = tmp_path / "demo-events.jsonl"
    _write_jsonl(
        events_path,
        [
            {
                "t": "2026-04-24T03:07:15Z",
                "type": "user_request",
                "actor": "user",
                "summary": "Create a replay demo",
            },
            {
                "t": "2026-04-24T03:07:16Z",
                "type": "task_start",
                "actor": "system",
                "summary": "Task started",
            },
            {
                "t": "2026-04-24T03:07:20Z",
                "type": "read",
                "actor": "agent",
                "summary": "Read campaign.toml",
                "path": "campaign.toml",
            },
            {
                "t": "2026-04-24T03:07:28Z",
                "type": "command",
                "actor": "agent",
                "summary": "Execute sweep",
                "data": {"command": "runo runs sweep cases/base"},
            },
        ],
    )

    bundle = load_demo_replay_bundle(events_path)

    assert bundle.chapter_count == 2
    assert bundle.events[0]["chapter_index"] == 1
    assert bundle.events[1]["chapter_index"] == 1
    assert bundle.events[2]["chapter_index"] == 1
    assert bundle.events[3]["chapter_index"] == 2


def test_load_demo_replay_bundle_rejects_empty_file(tmp_path: Path) -> None:
    events_path = tmp_path / "empty.jsonl"
    events_path.write_text("", encoding="utf-8")

    with pytest.raises(DemoReplayError, match="empty"):
        load_demo_replay_bundle(events_path)
