"""Structured event logging for demos and replay tooling.

The logger is intentionally dormant by default.  When enabled through CLI
options or environment variables, it emits newline-delimited JSON (JSONL)
records that can be replayed by a browser-based viewer or post-processed into
timelines.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from inspect import BoundArguments, Signature, signature
from pathlib import Path
from typing import Any, Final, ParamSpec, TypeVar, cast

EVENT_LOG_ENV_VAR: Final = "RUNOPS_EVENT_LOG"
EVENT_LOG_MODE_ENV_VAR: Final = "RUNOPS_EVENT_LOG_MODE"
EVENT_LOG_SESSION_ENV_VAR: Final = "RUNOPS_EVENT_LOG_SESSION"

_UNSET: Final = object()
_REDACTED_PARAM_NAMES: Final = frozenset(
    {
        "apikey",
        "accesskey",
        "authorization",
        "clientsecret",
        "content",
        "credential",
        "credentials",
        "password",
        "privatekey",
        "secret",
        "token",
    }
)
_SECRET_ASSIGNMENT_RE: Final = re.compile(
    r"(?ix)"
    r"(?P<name>--?(?:api[-_]?key|access[-_]?key|client[-_]?secret|"
    r"private[-_]?key|authorization|credentials?|password|secret|token)|"
    r"(?:api[-_]?key|access[-_]?key|client[-_]?secret|private[-_]?key|"
    r"authorization|credentials?|password|secret|token))"
    r"(?P<separator>\s*[:=]\s*|\s+)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_AUTH_VALUE_RE: Final = re.compile(
    r"(?i)\b(?P<scheme>bearer|basic)\s+(?P<value>[^\s,;]+)"
)
_URL_USERINFO_RE: Final = re.compile(
    r"(?i)(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<userinfo>[^/@\s]+)@"
)
_MAX_ITEMS: Final = 20
_MAX_DEPTH: Final = 3
_MAX_STRING_LENGTH: Final = 240

_P = ParamSpec("_P")
_R = TypeVar("_R")


class EventLogMode(str, Enum):
    """Supported event logging verbosity levels."""

    OFF = "off"
    SUMMARY_ONLY = "summary-only"
    VERBOSE = "verbose"


@dataclass(frozen=True)
class EventLoggerConfig:
    """Resolved runtime configuration for structured event logging."""

    path: Path
    mode: EventLogMode
    session_id: str
    actor: str = "runops"


_active_config: ContextVar[EventLoggerConfig | None | object] = ContextVar(
    "runops_event_logger_config",
    default=_UNSET,
)
_env_session_id: str | None = None


def normalize_event_log_mode(
    value: str | EventLogMode | None,
    *,
    default: EventLogMode = EventLogMode.SUMMARY_ONLY,
) -> EventLogMode:
    """Normalize a raw event log mode string."""
    if isinstance(value, EventLogMode):
        return value
    if value is None:
        return default

    normalized = str(value).strip().lower().replace("_", "-")
    if not normalized:
        return default

    try:
        return EventLogMode(normalized)
    except ValueError as exc:
        valid = ", ".join(mode.value for mode in EventLogMode)
        raise ValueError(f"event log mode must be one of: {valid}") from exc


def configure_event_logging(
    path: Path | str | None = None,
    *,
    mode: str | EventLogMode | None = None,
    session_id: str | None = None,
    actor: str = "runops",
) -> EventLoggerConfig | None:
    """Resolve and activate event logging for the current execution context."""
    config = _resolve_config(
        path=path,
        mode=mode,
        session_id=session_id,
        actor=actor,
        validate=True,
    )
    _active_config.set(config)
    return config


def clear_event_logging() -> None:
    """Reset event logging to its default unresolved state."""
    _active_config.set(_UNSET)


def get_event_logger_config() -> EventLoggerConfig | None:
    """Return the active event logger configuration, if any."""
    current = _active_config.get()
    if current is not _UNSET:
        return cast("EventLoggerConfig | None", current)
    return _resolve_config(validate=False)


def emit_event(
    event_type: str,
    *,
    summary: str = "",
    action: str = "",
    status: str = "",
    path: Path | str | None = None,
    data: dict[str, Any] | None = None,
    requires_verbose: bool = False,
    actor: str | None = None,
) -> None:
    """Append one structured event record to the configured JSONL log."""
    config = get_event_logger_config()
    if config is None:
        return
    if requires_verbose and config.mode is not EventLogMode.VERBOSE:
        return

    payload: dict[str, Any] = {
        "t": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "session_id": config.session_id,
        "actor": actor or config.actor,
        "type": event_type,
    }
    if summary:
        payload["summary"] = _sanitize_text(summary)
    if action:
        payload["action"] = action
    if status:
        payload["status"] = status
    if path is not None:
        payload["path"] = _sanitize_text(str(Path(path)))
    if data:
        payload["data"] = _sanitize_value(data)

    try:
        config.path.parent.mkdir(parents=True, exist_ok=True)
        with open(config.path, "a", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True)
            f.write("\n")
    except (OSError, TypeError, ValueError):
        # Event logging is best-effort and should never break the main action.
        return


def emit_artifact_event(
    path: Path | str,
    *,
    operation: str,
    artifact_kind: str,
    summary: str = "",
) -> None:
    """Emit a verbose-only artifact creation/update event."""
    message = summary or f"{operation.title()} {artifact_kind}"
    emit_event(
        "artifact_write",
        summary=message,
        path=path,
        data={
            "operation": operation,
            "artifact_kind": artifact_kind,
        },
        requires_verbose=True,
    )


def logged_action(name: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Decorate an action function so it emits structured start/finish events."""

    def decorator(func: Callable[_P, _R]) -> Callable[_P, _R]:
        func_signature = signature(func)

        @wraps(func)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            bound = _bind_arguments(func_signature, *args, **kwargs)
            emit_event(
                "action_start",
                action=name,
                summary=f"Start {name}",
                data={"params": _sanitize_mapping(bound.arguments)},
            )
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                emit_event(
                    "action_error",
                    action=name,
                    status="error",
                    summary=str(exc),
                    data={"error_type": type(exc).__name__},
                )
                raise

            finish_data = _build_finish_data(result)
            emit_event(
                "action_finish",
                action=name,
                status=_coerce_status(result),
                summary=_coerce_message(result),
                data=finish_data,
            )
            return result

        return wrapper

    return decorator


def _resolve_config(
    *,
    path: Path | str | None = None,
    mode: str | EventLogMode | None = None,
    session_id: str | None = None,
    actor: str = "runops",
    validate: bool,
) -> EventLoggerConfig | None:
    raw_path = (
        str(path).strip() if path is not None else os.getenv(EVENT_LOG_ENV_VAR, "")
    )
    if not raw_path:
        return None

    raw_mode = mode if mode is not None else os.getenv(EVENT_LOG_MODE_ENV_VAR, "")
    try:
        resolved_mode = normalize_event_log_mode(raw_mode or None)
    except ValueError:
        if validate:
            raise
        return None

    if resolved_mode is EventLogMode.OFF:
        return None

    raw_session = (
        str(session_id).strip()
        if session_id is not None
        else os.getenv(EVENT_LOG_SESSION_ENV_VAR, "").strip()
    )
    resolved_session = raw_session or _default_session_id()

    return EventLoggerConfig(
        path=Path(raw_path).expanduser(),
        mode=resolved_mode,
        session_id=resolved_session,
        actor=actor,
    )


def _default_session_id() -> str:
    global _env_session_id
    if _env_session_id is None:
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _env_session_id = f"sess-{timestamp}-{os.getpid()}"
    return _env_session_id


def _bind_arguments(
    func_signature: Signature,
    *args: Any,
    **kwargs: Any,
) -> BoundArguments:
    try:
        return func_signature.bind_partial(*args, **kwargs)
    except TypeError:
        return func_signature.bind_partial()


def _build_finish_data(result: Any) -> dict[str, Any]:
    finish_data: dict[str, Any] = {}
    message = _coerce_message(result)
    if message:
        finish_data["message"] = message

    state_before = getattr(result, "state_before", "")
    if state_before:
        finish_data["state_before"] = state_before
    state_after = getattr(result, "state_after", "")
    if state_after:
        finish_data["state_after"] = state_after

    config = get_event_logger_config()
    result_data = getattr(result, "data", {})
    if (
        config is not None
        and config.mode is EventLogMode.VERBOSE
        and isinstance(result_data, dict)
        and result_data
    ):
        finish_data["result"] = _sanitize_mapping(result_data)
    return finish_data


def _coerce_message(result: Any) -> str:
    message = getattr(result, "message", "")
    return str(message) if message else ""


def _coerce_status(result: Any) -> str:
    status = getattr(result, "status", "")
    value = getattr(status, "value", status)
    return str(value) if value else ""


def _sanitize_mapping(values: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in values.items():
        sanitized[str(key)] = _sanitize_named_value(str(key), value, depth=0)
    return sanitized


def _sanitize_named_value(name: str, value: Any, *, depth: int) -> Any:
    if _is_secret_name(name):
        return _redacted_marker(value)
    return _sanitize_value(value, depth=depth + 1)


def _sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        return "<max-depth>"

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"

    if isinstance(value, dict):
        items = list(value.items())
        mapping_result: dict[str, Any] = {}
        for key, item in items[:_MAX_ITEMS]:
            mapping_result[str(key)] = _sanitize_named_value(
                str(key),
                item,
                depth=depth,
            )
        if len(items) > _MAX_ITEMS:
            mapping_result["..."] = f"{len(items) - _MAX_ITEMS} more"
        return mapping_result

    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        sequence_result: list[Any] = [
            _sanitize_value(item, depth=depth + 1) for item in items[:_MAX_ITEMS]
        ]
        if len(items) > _MAX_ITEMS:
            sequence_result.append(f"... {len(items) - _MAX_ITEMS} more")
        return sequence_result

    return repr(value)


def _redacted_marker(value: Any) -> str:
    if isinstance(value, str):
        return f"<redacted:{len(value)} chars>"
    if isinstance(value, (bytes, bytearray)):
        return f"<redacted:{len(value)} bytes>"
    return "<redacted>"


def _is_secret_name(name: str) -> bool:
    """Return whether a mapping/parameter name denotes secret material."""
    normalized = re.sub(r"[^a-z0-9]+", "", name.casefold())
    return any(
        normalized == marker or normalized.endswith(marker)
        for marker in _REDACTED_PARAM_NAMES
    )


def _sanitize_text(value: str) -> str:
    """Redact common inline secret forms before bounding event-log strings."""
    sanitized = _URL_USERINFO_RE.sub(r"\g<scheme><redacted>@", value)
    sanitized = _AUTH_VALUE_RE.sub(r"\g<scheme> <redacted>", sanitized)
    sanitized = _SECRET_ASSIGNMENT_RE.sub(
        r"\g<name>\g<separator><redacted>",
        sanitized,
    )
    if len(sanitized) <= _MAX_STRING_LENGTH:
        return sanitized
    return f"{sanitized[: _MAX_STRING_LENGTH - 3]}..."


__all__ = [
    "EVENT_LOG_ENV_VAR",
    "EVENT_LOG_MODE_ENV_VAR",
    "EVENT_LOG_SESSION_ENV_VAR",
    "EventLogMode",
    "EventLoggerConfig",
    "clear_event_logging",
    "configure_event_logging",
    "emit_artifact_event",
    "emit_event",
    "get_event_logger_config",
    "logged_action",
    "normalize_event_log_mode",
]
