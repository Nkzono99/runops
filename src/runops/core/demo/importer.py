"""Import Codex session logs into normalized demo replay events."""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from runops.core.demo.sanitize import (
    MAX_RESULT_LENGTH as _MAX_RESULT_LENGTH,
)
from runops.core.demo.sanitize import (
    DemoSanitizerMixin,
)
from runops.core.exceptions import SessionImportError

_SKIP_TOOL_CALL_NAMES = frozenset({"exec_command"})
_SKIP_TOOL_RESULT_NAMES = frozenset({"apply_patch", "exec_command"})


@dataclass(frozen=True)
class DemoImportResult:
    """Summary of a session-log import."""

    session_log: Path
    output_path: Path
    session_id: str | None
    imported_events: int
    skipped_records: int
    event_counts: dict[str, int]


@dataclass(frozen=True)
class DiscoveredCodexSessionLog:
    """Metadata for one Codex session log discovered on disk."""

    path: Path
    session_id: str | None
    cwd: Path | None
    started_at: str | None


def import_codex_session_log(
    session_log: Path | str,
    output_path: Path | str,
    *,
    workspace_root: Path | str | None = None,
) -> DemoImportResult:
    """Import a Codex session JSONL into replay-friendly demo events JSONL."""
    importer = _CodexSessionImporter(workspace_root=workspace_root)
    return importer.import_file(Path(session_log), Path(output_path))


def discover_codex_session_log(
    *,
    workspace_root: Path | str,
    sessions_root: Path | str | None = None,
) -> DiscoveredCodexSessionLog:
    """Find the latest Codex session log whose cwd matches ``workspace_root``."""
    workspace = _canonicalize_path(Path(workspace_root))
    search_root = (
        _canonicalize_path(Path(sessions_root))
        if sessions_root is not None
        else _default_codex_sessions_root()
    )

    if not search_root.is_dir():
        raise SessionImportError(f"Codex sessions directory not found: {search_root}")

    latest_match: DiscoveredCodexSessionLog | None = None
    latest_key: tuple[str, int] | None = None
    for session_log in search_root.rglob("*.jsonl"):
        candidate = _read_codex_session_meta(session_log)
        if candidate is None or candidate.cwd != workspace:
            continue
        sort_key = (candidate.started_at or "", _file_mtime_ns(candidate.path))
        if latest_key is None or sort_key > latest_key:
            latest_match = candidate
            latest_key = sort_key

    if latest_match is None:
        raise SessionImportError(
            f"no Codex session logs found for workspace {workspace} under {search_root}"
        )

    return latest_match


def _default_codex_sessions_root() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex"))
    return _canonicalize_path(codex_home) / "sessions"


def _canonicalize_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _file_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _read_codex_session_meta(session_log: Path) -> DiscoveredCodexSessionLog | None:
    try:
        with session_log.open(encoding="utf-8") as src:
            for line_number, line in enumerate(src, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except JSONDecodeError:
                    return None

                if record.get("type") != "session_meta":
                    if line_number >= 20:
                        return None
                    continue

                payload = record.get("payload")
                if not isinstance(payload, dict):
                    return None

                cwd_value = payload.get("cwd")
                cwd = (
                    _canonicalize_path(Path(cwd_value))
                    if isinstance(cwd_value, str) and cwd_value.strip()
                    else None
                )
                session_id = payload.get("id")
                started_at = payload.get("timestamp") or record.get("timestamp")
                return DiscoveredCodexSessionLog(
                    path=session_log,
                    session_id=session_id if isinstance(session_id, str) else None,
                    cwd=cwd,
                    started_at=started_at if isinstance(started_at, str) else None,
                )
    except OSError:
        return None

    return None


class _CodexSessionImporter(DemoSanitizerMixin):
    """Stateful importer for Codex session logs."""

    def __init__(self, *, workspace_root: Path | str | None) -> None:
        self.workspace_root = (
            Path(workspace_root).expanduser().resolve()
            if workspace_root is not None
            else None
        )
        self.session_id: str | None = None
        self.session_cwd: Path | None = None
        self._call_names: dict[str, str] = {}
        self._event_index = 0
        self._event_counts: Counter[str] = Counter()

    def import_file(self, session_log: Path, output_path: Path) -> DemoImportResult:
        """Import one session log into JSONL demo events."""
        imported_events = 0
        skipped_records = 0

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with (
                session_log.open(encoding="utf-8") as src,
                output_path.open("w", encoding="utf-8") as dst,
            ):
                for line_number, line in enumerate(src, start=1):
                    stripped = line.strip()
                    if not stripped:
                        continue

                    try:
                        record = json.loads(stripped)
                    except JSONDecodeError as exc:
                        raise SessionImportError(
                            f"invalid JSON in session log at line {line_number}"
                        ) from exc

                    events = self._convert_record(record)
                    if not events:
                        skipped_records += 1
                        continue

                    for event in events:
                        json.dump(event, dst, ensure_ascii=False, sort_keys=True)
                        dst.write("\n")
                        imported_events += 1
        except OSError as exc:
            raise SessionImportError(str(exc)) from exc

        return DemoImportResult(
            session_log=session_log,
            output_path=output_path,
            session_id=self.session_id,
            imported_events=imported_events,
            skipped_records=skipped_records,
            event_counts=dict(self._event_counts),
        )

    def _convert_record(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        top_level_type = self._as_str(record.get("type"))
        timestamp = self._as_str(record.get("timestamp"))
        payload = self._as_mapping(record.get("payload"))
        if not top_level_type or not payload:
            return []

        if top_level_type == "session_meta":
            return self._convert_session_meta(timestamp, payload)
        if top_level_type == "event_msg":
            return self._convert_event_msg(timestamp, payload)
        if top_level_type == "response_item":
            return self._convert_response_item(timestamp, payload)
        return []

    def _convert_session_meta(
        self,
        timestamp: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        session_id = self._as_str(payload.get("id"))
        if session_id:
            self.session_id = session_id

        cwd = self._as_str(payload.get("cwd"))
        if cwd:
            self.session_cwd = Path(cwd).expanduser()

        data: dict[str, Any] = {}
        for key in ("originator", "source", "cli_version", "model_provider"):
            value = self._as_str(payload.get(key))
            if value:
                data[key] = value
        if cwd:
            data["cwd"] = self._normalize_path(cwd)

        return [
            self._emit(
                timestamp,
                "session_start",
                actor="system",
                summary="Codex session started",
                data=data,
            )
        ]

    def _convert_event_msg(
        self,
        timestamp: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        payload_type = self._as_str(payload.get("type"))
        if payload_type == "agent_message":
            message = self._sanitize_text(self._as_str(payload.get("message")))
            if not message:
                return []
            data = {"message": message}
            phase = self._as_str(payload.get("phase"))
            if phase:
                data["phase"] = phase
            return [
                self._emit(
                    timestamp,
                    "note",
                    actor="agent",
                    summary=self._summarize_text(message),
                    data=data,
                )
            ]
        if payload_type == "user_message":
            request = self._extract_user_request(self._as_str(payload.get("message")))
            if not request:
                return []
            return [
                self._emit(
                    timestamp,
                    "user_request",
                    actor="user",
                    summary=self._summarize_text(request),
                    data={"message": request},
                )
            ]
        if payload_type == "exec_command_end":
            return self._convert_exec_command(timestamp, payload)
        if payload_type == "patch_apply_end":
            return self._convert_patch_apply(timestamp, payload)
        if payload_type == "mcp_tool_call_end":
            return self._convert_mcp_tool_result(timestamp, payload)
        if payload_type == "web_search_end":
            query = self._sanitize_text(self._as_str(payload.get("query")))
            if not query:
                return []
            return [
                self._emit(
                    timestamp,
                    "web_search",
                    actor="agent",
                    summary=f"Search web: {self._summarize_text(query)}",
                    data={
                        "query": query,
                        "call_id": self._as_str(payload.get("call_id")),
                    },
                )
            ]
        if payload_type == "task_started":
            return [
                self._emit(
                    timestamp,
                    "task_start",
                    actor="system",
                    summary="Task started",
                    data=self._compact_mapping(
                        {
                            "turn_id": payload.get("turn_id"),
                            "collaboration_mode": payload.get(
                                "collaboration_mode_kind"
                            ),
                        }
                    ),
                )
            ]
        if payload_type == "task_complete":
            message = self._sanitize_text(
                self._as_str(payload.get("last_agent_message"))
            )
            data = self._compact_mapping(
                {
                    "turn_id": payload.get("turn_id"),
                    "completed_at": payload.get("completed_at"),
                    "duration_ms": payload.get("duration_ms"),
                }
            )
            return [
                self._emit(
                    timestamp,
                    "task_complete",
                    actor="agent",
                    summary=self._summarize_text(message or "Task completed"),
                    data=data or None,
                )
            ]
        return []

    def _convert_response_item(
        self,
        timestamp: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        payload_type = self._as_str(payload.get("type"))
        if payload_type in {"function_call", "custom_tool_call"}:
            tool_name = self._as_str(payload.get("name"))
            call_id = self._as_str(payload.get("call_id"))
            if call_id and tool_name:
                self._call_names[call_id] = tool_name
            if tool_name in _SKIP_TOOL_CALL_NAMES:
                return []
            return [self._build_tool_call_event(timestamp, payload)]
        if payload_type in {"function_call_output", "custom_tool_call_output"}:
            call_id = self._as_str(payload.get("call_id"))
            tool_name = self._call_names.get(call_id, "")
            if tool_name in _SKIP_TOOL_RESULT_NAMES:
                return []
            output = self._sanitize_text(
                self._coerce_text(payload.get("output")),
                limit=_MAX_RESULT_LENGTH,
            )
            if not output:
                return []
            return [
                self._emit(
                    timestamp,
                    "tool_result",
                    actor="agent",
                    summary=f"{tool_name or 'tool'} completed",
                    data=self._compact_mapping(
                        {
                            "tool": tool_name or None,
                            "call_id": call_id or None,
                            "output_excerpt": output,
                        }
                    ),
                )
            ]
        if payload_type == "web_search_call":
            action = self._as_mapping(payload.get("action"))
            query = self._sanitize_text(self._as_str(action.get("query")))
            if not query:
                return []
            return [
                self._emit(
                    timestamp,
                    "tool_call",
                    actor="agent",
                    summary=f"Search web: {self._summarize_text(query)}",
                    data={"tool": "web_search", "query": query},
                )
            ]
        return []

    def _build_tool_call_event(
        self,
        timestamp: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        tool_name = self._as_str(payload.get("name")) or "tool"
        call_id = self._as_str(payload.get("call_id"))
        data = self._compact_mapping(
            {
                "tool": tool_name,
                "call_id": call_id or None,
                "status": self._as_str(payload.get("status")) or None,
            }
        )

        if tool_name == "apply_patch":
            patch_text = self._as_str(payload.get("input"))
            patch_paths = self._extract_patch_paths(patch_text)
            if patch_paths:
                data["paths"] = patch_paths
            return self._emit(
                timestamp,
                "tool_call",
                actor="agent",
                summary=f"Apply patch ({len(patch_paths)} target(s))",
                data=data,
            )

        arguments = self._parse_tool_arguments(payload.get("arguments"))
        if arguments is not None:
            data["arguments"] = arguments
        return self._emit(
            timestamp,
            "tool_call",
            actor="agent",
            summary=f"Call {tool_name}",
            data=data,
        )

    def _convert_exec_command(
        self,
        timestamp: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raw_command = self._normalize_command(payload.get("command"))
        parsed_cmd = self._as_list_of_mappings(payload.get("parsed_cmd"))
        raw_paths = [
            self._as_str(item.get("path"))
            for item in parsed_cmd
            if self._as_str(item.get("path"))
        ]
        cwd = self._as_str(payload.get("cwd"))
        if cwd:
            raw_paths.append(cwd)

        command = self._sanitize_command(raw_command, raw_paths)
        events: list[dict[str, Any]] = []
        for item in parsed_cmd:
            converted = self._convert_parsed_command(timestamp, item)
            if converted is not None:
                events.append(converted)

        exit_code = payload.get("exit_code")
        status = ""
        if isinstance(exit_code, int):
            status = "success" if exit_code == 0 else "error"

        command_data = self._compact_mapping(
            {
                "command": command,
                "cwd": self._normalize_path(cwd) if cwd else None,
                "call_id": self._as_str(payload.get("call_id")) or None,
                "process_id": self._as_str(payload.get("process_id")) or None,
                "exit_code": exit_code,
            }
        )
        output = self._sanitize_command_output(
            self._coerce_text(payload.get("aggregated_output")),
            raw_paths,
        )
        if output:
            command_data["output_excerpt"] = output

        events.append(
            self._emit(
                timestamp,
                "command",
                actor="agent",
                status=status,
                summary=f"Execute {self._summarize_text(command)}",
                data=command_data,
            )
        )
        return events

    def _convert_parsed_command(
        self,
        timestamp: str,
        item: dict[str, Any],
    ) -> dict[str, Any] | None:
        item_type = self._as_str(item.get("type"))
        command = self._sanitize_command(
            self._as_str(item.get("cmd")),
            [self._as_str(item.get("path"))],
        )
        path = self._normalize_path(self._as_str(item.get("path")))
        if item_type == "read" and path:
            name = self._as_str(item.get("name")) or path
            return self._emit(
                timestamp,
                "read",
                actor="agent",
                path=path,
                summary=f"Read {name}",
                data=self._compact_mapping({"command": command}),
            )
        if item_type == "search":
            query = self._sanitize_text(self._as_str(item.get("query")))
            return self._emit(
                timestamp,
                "search",
                actor="agent",
                path=path or None,
                summary=f"Search {self._summarize_text(query or command)}",
                data=self._compact_mapping(
                    {
                        "command": command or None,
                        "query": query or None,
                    }
                ),
            )
        if item_type == "list_files":
            return self._emit(
                timestamp,
                "list_files",
                actor="agent",
                path=path or None,
                summary=f"List files in {path or '.'}",
                data=self._compact_mapping({"command": command or None}),
            )
        return None

    def _convert_patch_apply(
        self,
        timestamp: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        call_id = self._as_str(payload.get("call_id"))
        success = bool(payload.get("success"))
        changes = self._as_mapping_of_mappings(payload.get("changes"))
        events: list[dict[str, Any]] = []
        for raw_path, change in changes.items():
            change_type = self._as_str(change.get("type")) or "update"
            event_type = (
                change_type
                if change_type in {"create", "update", "delete"}
                else "update"
            )
            path = self._normalize_path(raw_path)
            data = self._compact_mapping(
                {
                    "tool": "apply_patch",
                    "call_id": call_id or None,
                    "move_path": self._normalize_path(
                        self._as_str(change.get("move_path"))
                    ),
                }
            )
            diff_excerpt = self._sanitize_text(
                self._as_str(change.get("unified_diff")),
                limit=_MAX_RESULT_LENGTH,
            )
            if diff_excerpt:
                data["diff_excerpt"] = diff_excerpt
            events.append(
                self._emit(
                    timestamp,
                    event_type,
                    actor="agent",
                    status="success" if success else "error",
                    path=path or None,
                    summary=f"{event_type.title()} {path or 'file'}",
                    data=data,
                )
            )

        if events:
            return events

        stdout = self._sanitize_text(self._as_str(payload.get("stdout")), limit=300)
        stderr = self._sanitize_text(self._as_str(payload.get("stderr")), limit=300)
        return [
            self._emit(
                timestamp,
                "tool_result",
                actor="agent",
                status="success" if success else "error",
                summary="apply_patch completed" if success else "apply_patch failed",
                data=self._compact_mapping(
                    {
                        "tool": "apply_patch",
                        "call_id": call_id or None,
                        "stdout": stdout or None,
                        "stderr": stderr or None,
                    }
                ),
            )
        ]

    def _convert_mcp_tool_result(
        self,
        timestamp: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        invocation = self._as_mapping(payload.get("invocation"))
        server = self._as_str(invocation.get("server"))
        tool = self._as_str(invocation.get("tool"))
        result = self._sanitize_text(
            self._coerce_text(payload.get("result")),
            limit=_MAX_RESULT_LENGTH,
        )
        return [
            self._emit(
                timestamp,
                "tool_result",
                actor="agent",
                summary=f"{server or 'mcp'}:{tool or 'tool'} completed",
                data=self._compact_mapping(
                    {
                        "tool": tool or None,
                        "server": server or None,
                        "call_id": self._as_str(payload.get("call_id")) or None,
                        "result_excerpt": result or None,
                    }
                ),
            )
        ]

    def _emit(
        self,
        timestamp: str,
        event_type: str,
        *,
        actor: str,
        summary: str,
        status: str = "",
        path: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._event_index += 1
        self._event_counts[event_type] += 1

        event: dict[str, Any] = {
            "id": f"evt-{self._event_index:06d}",
            "t": timestamp,
            "source": "codex_session",
            "actor": actor,
            "type": event_type,
            "summary": summary,
        }
        if self.session_id:
            event["session_id"] = self.session_id
        if status:
            event["status"] = status
        if path:
            event["path"] = path
        if data:
            event["data"] = data
        return event
