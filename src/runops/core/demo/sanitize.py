"""Sanitization helpers for Codex session demo imports."""

from __future__ import annotations

import json
import shlex
from json import JSONDecodeError
from pathlib import Path
from typing import Any

MAX_SUMMARY_LENGTH = 120
MAX_TEXT_LENGTH = 400
MAX_RESULT_LENGTH = 800
MAX_LIST_ITEMS = 20
MAX_DEPTH = 3


class DemoSanitizerMixin:
    """Path and payload normalization used by the session importer."""

    workspace_root: Path | None
    session_cwd: Path | None

    def _extract_patch_paths(self, patch_text: str) -> list[str]:
        paths: list[str] = []
        for line in patch_text.splitlines():
            for prefix in (
                "*** Add File: ",
                "*** Update File: ",
                "*** Delete File: ",
                "*** Move to: ",
            ):
                if line.startswith(prefix):
                    path = self._normalize_path(line[len(prefix) :].strip())
                    if path and path not in paths:
                        paths.append(path)
        return paths

    def _extract_user_request(self, message: str) -> str:
        if not message:
            return ""
        marker = "## My request for Codex:"
        if marker in message:
            request = message.split(marker, maxsplit=1)[1].strip()
        else:
            request = message.strip()
        return self._sanitize_text(request, limit=MAX_TEXT_LENGTH)

    def _parse_tool_arguments(self, raw: Any) -> Any:
        if raw is None:
            return None
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except JSONDecodeError:
                return self._sanitize_text(raw)
            return self._sanitize_value(parsed)
        return self._sanitize_value(raw)

    def _sanitize_value(self, value: Any, *, depth: int = 0) -> Any:
        if depth >= MAX_DEPTH:
            return "<truncated>"
        if value is None or isinstance(value, bool | int | float):
            return value
        if isinstance(value, str):
            return self._sanitize_text(value)
        if isinstance(value, Path):
            return self._normalize_path(str(value))
        if isinstance(value, dict):
            items = list(value.items())[:MAX_LIST_ITEMS]
            return {
                str(key): self._sanitize_value(item, depth=depth + 1)
                for key, item in items
            }
        if isinstance(value, list):
            return [
                self._sanitize_value(item, depth=depth + 1)
                for item in value[:MAX_LIST_ITEMS]
            ]
        return self._sanitize_text(str(value))

    def _sanitize_text(self, text: str, *, limit: int = MAX_TEXT_LENGTH) -> str:
        if not text:
            return ""
        normalized = text.replace("\r\n", "\n").strip()
        for root in self._path_roots():
            normalized = normalized.replace(root, ".")
        home = str(Path.home())
        if home:
            normalized = normalized.replace(home, "~")
        if len(normalized) > limit:
            return normalized[: limit - 3].rstrip() + "..."
        return normalized

    def _sanitize_command(self, command: str, raw_paths: list[str]) -> str:
        sanitized = command
        for raw_path in raw_paths:
            if raw_path:
                sanitized = sanitized.replace(raw_path, self._normalize_path(raw_path))
        return self._sanitize_text(sanitized, limit=MAX_TEXT_LENGTH)

    def _sanitize_command_output(self, output: str, raw_paths: list[str]) -> str:
        sanitized = output
        for raw_path in raw_paths:
            if raw_path:
                sanitized = sanitized.replace(raw_path, self._normalize_path(raw_path))
        return self._sanitize_text(sanitized, limit=MAX_RESULT_LENGTH)

    def _path_roots(self) -> list[str]:
        roots: list[str] = []
        for candidate in (self.workspace_root, self.session_cwd):
            if candidate is None:
                continue
            root = str(candidate)
            if root and root not in roots:
                roots.append(root)
        return roots

    def _normalize_path(self, raw_path: str) -> str:
        if not raw_path:
            return ""
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            return path.as_posix()
        for root in (self.workspace_root, self.session_cwd):
            if root is None:
                continue
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            return "." if not relative.parts else relative.as_posix()
        parts = path.parts
        if len(parts) <= 4:
            return path.as_posix()
        tail = "/".join(parts[-4:])
        return f".../{tail}"

    def _normalize_command(self, command: Any) -> str:
        if isinstance(command, str):
            return command
        if isinstance(command, list):
            parts = [str(item) for item in command]
            if len(parts) >= 3 and parts[1] == "-lc":
                return parts[2]
            return shlex.join(parts)
        return self._coerce_text(command)

    def _summarize_text(self, text: str) -> str:
        compact = " ".join(text.split())
        if len(compact) > MAX_SUMMARY_LENGTH:
            return compact[: MAX_SUMMARY_LENGTH - 3].rstrip() + "..."
        return compact

    def _coerce_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(value)

    def _compact_mapping(self, mapping: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value for key, value in mapping.items() if value not in (None, "", [])
        }

    def _as_str(self, value: Any) -> str:
        return value if isinstance(value, str) else ""

    def _as_mapping(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _as_list_of_mappings(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _as_mapping_of_mappings(self, value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(value, dict):
            return {}
        return {str(key): item for key, item in value.items() if isinstance(item, dict)}
