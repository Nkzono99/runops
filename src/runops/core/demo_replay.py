"""Build browser-based replay UIs from demo event logs."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from runops.core.exceptions import DemoReplayError
from runops.templates import render


@dataclass(frozen=True)
class DemoReplayChapter:
    """One inferred chapter in the replay timeline."""

    id: str
    index: int
    title: str
    start_index: int
    end_index: int
    event_count: int
    lead_type: str


@dataclass(frozen=True)
class DemoReplayBundle:
    """Normalized replay data passed to the HTML renderer."""

    source_path: Path
    title: str
    subtitle: str
    events: list[dict[str, Any]]
    event_count: int
    file_count: int
    actor_count: int
    chapter_count: int
    event_types: dict[str, int]
    chapters: list[DemoReplayChapter]


@dataclass(frozen=True)
class DemoReplayBuildResult:
    """Summary of a rendered replay UI build."""

    source_path: Path
    output_path: Path
    title: str
    event_count: int
    file_count: int


def load_demo_replay_bundle(
    source_path: Path | str,
    *,
    title: str | None = None,
    subtitle: str | None = None,
) -> DemoReplayBundle:
    """Load JSONL events and normalize them for replay rendering."""
    path = Path(source_path)
    events = _load_events(path)
    event_count = len(events)
    file_count = len({event["path"] for event in events if event["path"]})
    actor_count = len({event["actor"] for event in events})
    chapters = _infer_chapters(events)
    event_types = dict(Counter(event["type"] for event in events))
    replay_title = title or _default_title(path)
    replay_subtitle = subtitle or _default_subtitle(path, event_count, file_count)
    return DemoReplayBundle(
        source_path=path,
        title=replay_title,
        subtitle=replay_subtitle,
        events=events,
        event_count=event_count,
        file_count=file_count,
        actor_count=actor_count,
        chapter_count=len(chapters),
        event_types=event_types,
        chapters=chapters,
    )


def render_demo_replay_html(bundle: DemoReplayBundle) -> str:
    """Render one self-contained replay HTML document."""
    replay_payload = {
        "title": bundle.title,
        "subtitle": bundle.subtitle,
        "sourcePath": bundle.source_path.name,
        "stats": {
            "eventCount": bundle.event_count,
            "fileCount": bundle.file_count,
            "actorCount": bundle.actor_count,
            "chapterCount": bundle.chapter_count,
            "eventTypes": bundle.event_types,
        },
        "chapters": [
            {
                "id": chapter.id,
                "index": chapter.index,
                "title": chapter.title,
                "startIndex": chapter.start_index,
                "endIndex": chapter.end_index,
                "eventCount": chapter.event_count,
                "leadType": chapter.lead_type,
            }
            for chapter in bundle.chapters
        ],
        "events": bundle.events,
    }
    replay_data_json = _json_for_html(replay_payload)
    return render(
        "demo/replay.html.j2",
        title=bundle.title,
        subtitle=bundle.subtitle,
        replay_data_json=replay_data_json,
    )


def build_demo_replay_ui(
    source_path: Path | str,
    output_path: Path | str,
    *,
    title: str | None = None,
    subtitle: str | None = None,
) -> DemoReplayBuildResult:
    """Build a replay HTML file from normalized demo events."""
    bundle = load_demo_replay_bundle(
        source_path,
        title=title,
        subtitle=subtitle,
    )
    html = render_demo_replay_html(bundle)
    out_path = Path(output_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
    except OSError as exc:
        raise DemoReplayError(str(exc)) from exc
    return DemoReplayBuildResult(
        source_path=bundle.source_path,
        output_path=out_path,
        title=bundle.title,
        event_count=bundle.event_count,
        file_count=bundle.file_count,
    )


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = json.loads(stripped)
                except JSONDecodeError as exc:
                    raise DemoReplayError(
                        f"invalid JSON in demo events at line {line_number}"
                    ) from exc
                if not isinstance(raw, dict):
                    raise DemoReplayError(
                        f"demo event at line {line_number} must be an object"
                    )
                events.append(_normalize_event(raw, len(events) + 1))
    except OSError as exc:
        raise DemoReplayError(str(exc)) from exc

    if not events:
        raise DemoReplayError("demo events file is empty")
    return events


def _normalize_event(raw: dict[str, Any], index: int) -> dict[str, Any]:
    event_type = _as_str(raw.get("type")) or "event"
    summary = _as_str(raw.get("summary")) or _default_summary(event_type)
    event: dict[str, Any] = {
        "id": _as_str(raw.get("id")) or f"evt-{index:06d}",
        "t": _as_str(raw.get("t")) or _as_str(raw.get("timestamp")),
        "type": event_type,
        "summary": summary,
        "actor": _as_str(raw.get("actor")) or "system",
        "status": _as_str(raw.get("status")),
        "path": _as_str(raw.get("path")),
        "source": _as_str(raw.get("source")) or "runops",
        "action": _as_str(raw.get("action")),
        "data": _sanitize_value(raw.get("data")),
    }
    return event


def _infer_chapters(events: list[dict[str, Any]]) -> list[DemoReplayChapter]:
    if not events:
        return []

    starts = [0]
    current_start = 0
    for index in range(1, len(events)):
        if _starts_new_chapter(events, current_start, index):
            starts.append(index)
            current_start = index

    chapters: list[DemoReplayChapter] = []
    for chapter_index, start_index in enumerate(starts, start=1):
        end_index = (
            starts[chapter_index] - 1
            if chapter_index < len(starts)
            else len(events) - 1
        )
        lead_event = events[start_index]
        chapter = DemoReplayChapter(
            id=f"chapter-{chapter_index:02d}",
            index=chapter_index,
            title=_chapter_title(lead_event, chapter_index),
            start_index=start_index,
            end_index=end_index,
            event_count=(end_index - start_index) + 1,
            lead_type=lead_event["type"],
        )
        chapters.append(chapter)

    for chapter in chapters:
        for offset, event_index in enumerate(
            range(chapter.start_index, chapter.end_index + 1),
            start=1,
        ):
            event = events[event_index]
            event["chapter_id"] = chapter.id
            event["chapter_index"] = chapter.index
            event["chapter_title"] = chapter.title
            event["step_in_chapter"] = offset
    return chapters


def _starts_new_chapter(
    events: list[dict[str, Any]],
    current_start: int,
    index: int,
) -> bool:
    event = events[index]
    distance = index - current_start
    event_type = event["type"]
    if event_type in {"user_request", "task_start"}:
        return True
    if event_type == "command" and distance >= 2 and _is_primary_command(event):
        return True
    if event_type in {"create", "update", "delete"} and distance >= 5:
        return _is_major_write(event)
    return False


def _phase(event: dict[str, Any]) -> str:
    event_type = event["type"]
    if event_type in {"session_start", "user_request", "task_start"}:
        return "setup"
    if event_type in {"read", "search", "list_files", "web_search"}:
        return "inspect"
    if event_type in {"create", "update", "delete", "tool_call"}:
        return "edit"
    if event_type in {"command", "tool_result", "action_start", "action_finish"}:
        return "execute"
    if event_type in {"task_complete", "note"}:
        return "wrap_up"
    return "other"


def _is_primary_command(event: dict[str, Any]) -> bool:
    data = event.get("data")
    if not isinstance(data, dict):
        return False
    command = _as_str(data.get("command")).strip()
    return command.startswith(("runo ", "runops ", "uv run runo ", "uv run runops "))


def _is_major_write(event: dict[str, Any]) -> bool:
    path = _as_str(event.get("path"))
    if not path:
        return False
    filename = Path(path).name
    if filename in {"survey.toml", "manifest.toml", "job.sh", "facts.toml"}:
        return True
    return path.startswith("notes/") or path.startswith(".runops/insights/")


def _chapter_title(event: dict[str, Any], chapter_index: int) -> str:
    event_type = event["type"]
    summary = _as_str(event.get("summary")) or _default_summary(event_type)
    path = _as_str(event.get("path"))
    if event_type == "user_request":
        return f"Request {chapter_index}"
    if event_type == "task_start":
        return f"Task Start {chapter_index}"
    if event_type == "command":
        command = _command_label(event)
        return f"Run {command}" if command else f"Execute {chapter_index}"
    if event_type in {"create", "update", "delete"} and path:
        return f"{event_type.title()} {Path(path).name}"
    if event_type in {"read", "search", "list_files"} and path:
        return f"Inspect {Path(path).name}"
    if event_type == "task_complete":
        return "Wrap Up"
    return _short_text(summary, limit=38)


def _command_label(event: dict[str, Any]) -> str:
    data = event.get("data")
    if not isinstance(data, dict):
        return ""
    command = _as_str(data.get("command")).strip()
    if not command:
        return ""
    parts = command.split()
    if len(parts) <= 4:
        return command
    return " ".join(parts[:4]) + "..."


def _sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        return "<truncated>"
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {
            str(key): _sanitize_value(item, depth=depth + 1)
            for key, item in list(value.items())[:30]
        }
    if isinstance(value, list):
        return [_sanitize_value(item, depth=depth + 1) for item in value[:30]]
    return str(value)


def _default_summary(event_type: str) -> str:
    return event_type.replace("_", " ").title()


def _default_title(path: Path) -> str:
    label = path.stem.replace("-", " ").replace("_", " ").strip()
    return label.title() or "Replay Timeline"


def _default_subtitle(path: Path, event_count: int, file_count: int) -> str:
    return f"{event_count} events across {file_count} files from {path.name}"


def _short_text(text: str, *, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) > limit:
        return compact[: limit - 3].rstrip() + "..."
    return compact


def _json_for_html(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""
