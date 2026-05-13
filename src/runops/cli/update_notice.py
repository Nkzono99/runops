"""Best-effort update notices for the ``runo`` CLI."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from runops.harness.builder import applied_harness_runops_version

_PYPI_JSON_URL = "https://pypi.org/pypi/runops/json"
_DISABLE_ENV = "RUNOPS_DISABLE_VERSION_CHECK"
_FORCE_ENV = "RUNOPS_FORCE_VERSION_CHECK"
_CACHE_ENV = "RUNOPS_UPDATE_CHECK_CACHE"
_CHECK_INTERVAL = timedelta(hours=24)
_NOTICE_INTERVAL = timedelta(hours=24)


def maybe_emit_update_notice(
    *,
    program: str,
    argv: list[str],
    current_version: str,
) -> None:
    """Emit a pip-style update notice to stderr when appropriate."""
    env = os.environ
    if not should_check_for_update(argv, env=env, stderr_is_tty=sys.stderr.isatty()):
        return

    message = build_update_notice(
        current_version,
        program=program,
        cache_path=default_cache_path(env),
        project_dir=find_project_root(Path.cwd()),
    )
    if message:
        sys.stderr.write(f"{message}\n")


def should_check_for_update(
    argv: list[str],
    *,
    env: Mapping[str, str],
    stderr_is_tty: bool,
) -> bool:
    """Return whether this CLI invocation may show an update notice."""
    if env.get(_DISABLE_ENV):
        return False
    if env.get("CI"):
        return False
    if not stderr_is_tty and not env.get(_FORCE_ENV):
        return False
    if not argv:
        return False
    if "--version" in argv or "--help" in argv or "-h" in argv:
        return False
    if "--json" in argv:
        return False

    command = argv[0]
    if command in {"update", "update-harness"}:
        return False
    return command != "mcp"


def build_update_notice(
    current_version: str,
    *,
    program: str,
    cache_path: Path,
    project_dir: Path | None = None,
    applied_version: str | None = None,
    now: datetime | None = None,
    fetch_latest: Callable[[], str | None] | None = None,
) -> str | None:
    """Return a user-facing update notice, updating cache metadata."""
    now = now or datetime.now(timezone.utc)
    fetch_latest = fetch_latest or fetch_latest_version
    cache = _read_cache(cache_path)
    if applied_version is None and project_dir is not None:
        applied_version = applied_harness_runops_version(project_dir)

    latest = _latest_from_fresh_cache(cache, now)
    if latest is None:
        latest = fetch_latest()
        if latest is not None:
            cache["latest_version"] = latest
            cache["checked_at"] = _format_dt(now)
            _write_cache(cache_path, cache)

    notices = _build_notice_sections(
        current_version=current_version,
        latest_version=latest,
        applied_version=applied_version,
        program=program,
    )
    if not notices:
        return None

    notice_key = "|".join(notices)
    if not _should_emit_notice(cache, notice_key, now):
        return None

    cache["notice_version"] = notice_key
    cache["last_notice_at"] = _format_dt(now)
    _write_cache(cache_path, cache)
    return "\n".join(notices)


def _build_notice_sections(
    *,
    current_version: str,
    latest_version: str | None,
    applied_version: str | None,
    program: str,
) -> list[str]:
    """Build update notice sections without touching cache state."""
    notices: list[str] = []
    command_name = _preferred_program(program)
    if latest_version is not None and _is_newer_version(
        latest_version,
        current_version,
    ):
        notices.extend(
            [
                f"A new runops release is available: {current_version} -> "
                f"{latest_version}",
                "Preferred project CLI flow:",
                f"  uvx --from runops {command_name} update-harness",
                "Use the project skill `$update-runops` (Codex) or "
                "`/update-runops` (Claude Code) to refresh the harness and "
                "check migrations.",
            ]
        )

    if applied_version is not None and _is_newer_version(
        current_version,
        applied_version,
    ):
        if notices:
            notices.append("")
        notices.extend(
            [
                "This project's runops harness is older than the CLI running "
                f"now: {applied_version} -> {current_version}",
                "Refresh project harness files with:",
                f"  uvx --from runops {command_name} update-harness",
            ]
        )
    elif applied_version is not None and _is_newer_version(
        applied_version,
        current_version,
    ):
        if notices:
            notices.append("")
        notices.extend(
            [
                "This project harness was last applied with a newer runops "
                f"version ({applied_version}) than the CLI running now "
                f"({current_version}).",
                "You may be using an old project .venv `runo`; prefer:",
                f"  uvx --from runops {command_name} <command>",
            ]
        )

    if notices:
        notices.append(f"Set {_DISABLE_ENV}=1 to hide this notice.")
    return notices


def fetch_latest_version(timeout: float = 1.0) -> str | None:
    """Return the latest runops version from PyPI, or None on failure."""
    request = urllib.request.Request(
        _PYPI_JSON_URL,
        headers={"User-Agent": "runops update-check"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        TimeoutError,
        urllib.error.URLError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return None

    if not isinstance(payload, dict):
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    version = info.get("version")
    return version if isinstance(version, str) and version else None


def default_cache_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the update-check cache path."""
    env = env or os.environ
    override = env.get(_CACHE_ENV)
    if override:
        return Path(override).expanduser()

    cache_root = env.get("XDG_CACHE_HOME") or env.get("LOCALAPPDATA")
    if cache_root:
        return Path(cache_root) / "runops" / "update-check.json"
    return Path.home() / ".cache" / "runops" / "update-check.json"


def find_project_root(start: Path) -> Path | None:
    """Return the nearest runops project root at or above ``start``."""
    current = start.resolve()
    candidates = (current, *current.parents)
    for directory in candidates:
        if (directory / "runops.toml").is_file() or (
            directory / ".runops" / "harness.lock"
        ).is_file():
            return directory
    return None


def _latest_from_fresh_cache(cache: dict[str, Any], now: datetime) -> str | None:
    latest = cache.get("latest_version")
    checked_at = _parse_dt(cache.get("checked_at"))
    if not isinstance(latest, str) or checked_at is None:
        return None
    if now - checked_at > _CHECK_INTERVAL:
        return None
    return latest


def _should_emit_notice(cache: dict[str, Any], latest: str, now: datetime) -> bool:
    if cache.get("notice_version") != latest:
        return True
    last_notice_at = _parse_dt(cache.get("last_notice_at"))
    if last_notice_at is None:
        return True
    return now - last_notice_at >= _NOTICE_INTERVAL


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _is_newer_version(candidate: str, current: str) -> bool:
    return _version_key(candidate) > _version_key(current)


def _version_key(version: str) -> Version:
    normalized = version.strip()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    try:
        return Version(normalized)
    except InvalidVersion:
        return Version("0")


def _preferred_program(program: str) -> str:
    """Return the canonical CLI name shown in update guidance."""
    return "runo" if program in {"runo", "runops"} else program
