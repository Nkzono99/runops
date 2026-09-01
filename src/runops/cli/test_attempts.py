"""CLI callbacks for isolated smoke/debug TestAttempts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from runops.application.actions import ActionResult, ActionStatus, execute_action
from runops.application.test_attempts import (
    list_test_attempts,
)
from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root
from runops.core.test_attempt import TestAttemptData


def smoke(
    case: Annotated[str, typer.Argument(help="Case name or simulator/case path.")],
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside it."),
    ] = Path("."),
    profile: Annotated[
        str,
        typer.Option("--profile", help="Execution profile identity for caching."),
    ] = "smoke",
    source_commit: Annotated[
        str,
        typer.Option("--source-commit", help="Source commit identity."),
    ] = "",
    executable_hash: Annotated[
        str,
        typer.Option(
            "--executable-hash",
            help="Executable sha256:<hex> identity, when available.",
        ),
    ] = "",
    adapter: Annotated[
        str,
        typer.Option("--adapter", help="Adapter identity; defaults to simulator."),
    ] = "",
    adapter_version: Annotated[
        str,
        typer.Option(
            "--adapter-version",
            help="Adapter version identity required for cache reuse.",
        ),
    ] = "",
    cache_ttl_hours: Annotated[
        float,
        typer.Option(
            "--cache-ttl-hours",
            min=0.0,
            help="Reuse a passed cache key for this many hours.",
        ),
    ] = 24.0,
    rerun: Annotated[
        bool,
        typer.Option("--rerun", help="Ignore a passed cache entry."),
    ] = False,
) -> None:
    """Prepare a smoke TestAttempt receipt/input snapshot without submitting."""
    _prepare(
        case,
        kind="smoke",
        path=path,
        profile=profile,
        source_commit=source_commit,
        executable_hash=executable_hash,
        adapter=adapter,
        adapter_version=adapter_version,
        cache_ttl_hours=cache_ttl_hours,
        rerun=rerun,
    )


def debug(
    case: Annotated[str, typer.Argument(help="Case name or simulator/case path.")],
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside it."),
    ] = Path("."),
    profile: Annotated[
        str,
        typer.Option("--profile", help="Execution profile identity for caching."),
    ] = "debug",
    source_commit: Annotated[
        str,
        typer.Option("--source-commit", help="Source commit identity."),
    ] = "",
    executable_hash: Annotated[
        str,
        typer.Option(
            "--executable-hash",
            help="Executable sha256:<hex> identity, when available.",
        ),
    ] = "",
    adapter: Annotated[
        str,
        typer.Option("--adapter", help="Adapter identity; defaults to simulator."),
    ] = "",
    adapter_version: Annotated[
        str,
        typer.Option(
            "--adapter-version",
            help="Adapter version identity required for cache reuse.",
        ),
    ] = "",
    cache_ttl_hours: Annotated[
        float,
        typer.Option(
            "--cache-ttl-hours",
            min=0.0,
            help="Reuse a passed cache key for this many hours.",
        ),
    ] = 24.0,
    rerun: Annotated[
        bool,
        typer.Option("--rerun", help="Ignore a passed cache entry."),
    ] = False,
) -> None:
    """Prepare a debug TestAttempt receipt/input snapshot without submitting."""
    _prepare(
        case,
        kind="debug",
        path=path,
        profile=profile,
        source_commit=source_commit,
        executable_hash=executable_hash,
        adapter=adapter,
        adapter_version=adapter_version,
        cache_ttl_hours=cache_ttl_hours,
        rerun=rerun,
    )


def list_attempts(
    path: Annotated[
        Path,
        typer.Argument(help="Project root or a path inside it."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """List receipts in the TestAttempt namespace only."""
    root = _project_root(path)
    try:
        attempts = list_test_attempts(root)
    except SimctlError as exc:
        _fail(exc)
    payload = [_payload(attempt, root) for attempt in attempts]
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not attempts:
        typer.echo("No TestAttempts found.")
        return
    for attempt in attempts:
        typer.echo(
            f"{attempt.id}  {attempt.kind:<5}  {attempt.state:<9}  {attempt.case}"
        )


def record(
    attempt_id: Annotated[str, typer.Argument(help="TestAttempt T ID.")],
    result: Annotated[
        str,
        typer.Option("--result", help="passed, failed, or skipped."),
    ],
    observation: Annotated[
        str,
        typer.Option("--observation", help="Concise observed result."),
    ] = "",
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside it."),
    ] = Path("."),
) -> None:
    """Record a terminal observation for a prepared/submitted TestAttempt."""
    root = _project_root(path)
    action_result = execute_action(
        "record_test_result",
        project_root=root,
        attempt_id=attempt_id,
        result=result,
        observation=observation,
    )
    _require_success(action_result)
    typer.echo(
        f"Recorded {action_result.data['attempt_id']}: {action_result.data['state']}"
    )


def clean(
    older_than_days: Annotated[
        int,
        typer.Option(
            "--older-than-days",
            min=0,
            help="Remove only terminal attempts at least this old.",
        ),
    ],
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside it."),
    ] = Path("."),
) -> None:
    """Remove old terminal attempts; refuse old prepared/submitted attempts."""
    root = _project_root(path)
    result = execute_action(
        "clean_test_attempts",
        project_root=root,
        older_than_days=older_than_days,
    )
    _require_success(result)
    removed_ids = list(result.data.get("removed_ids", []))
    if not removed_ids:
        typer.echo("No terminal TestAttempts matched the age threshold.")
        return
    typer.echo(f"Removed {len(removed_ids)} TestAttempt(s): " + ", ".join(removed_ids))


def _prepare(
    case: str,
    *,
    kind: str,
    path: Path,
    profile: str,
    source_commit: str,
    executable_hash: str,
    adapter: str,
    adapter_version: str,
    cache_ttl_hours: float,
    rerun: bool,
) -> None:
    root = _project_root(path)
    result = execute_action(
        "prepare_test_attempt",
        project_root=root,
        case=case,
        kind=kind,
        profile=profile,
        source_commit=source_commit,
        executable_hash=executable_hash,
        adapter=adapter,
        adapter_version=adapter_version,
        cache_ttl_hours=cache_ttl_hours,
        rerun=rerun,
    )
    _require_success(result)
    _render_prepared(result, root)


def _render_prepared(result: ActionResult, root: Path) -> None:
    receipt = Path(str(result.data["receipt_path"])).relative_to(root)
    if result.data.get("cached"):
        typer.echo(
            "SKIPPED: equivalent "
            f"{result.data['kind']} TestAttempt already passed: "
            f"{result.data['attempt_id']}"
        )
        typer.echo(
            "  Cache age: "
            f"{_format_cache_age(_optional_float(result.data['cache_age_seconds']))}"
        )
        typer.echo(f"  Receipt: {receipt}")
        typer.echo("  No Slurm job was submitted; existing evidence was reused.")
        return
    typer.echo(
        f"Prepared {result.data['kind']} TestAttempt {result.data['attempt_id']}"
    )
    typer.echo(f"  State: {result.data['state']}")
    typer.echo(f"  Receipt: {receipt}")
    if result.data["observation"] == "Identity incomplete; cache disabled.":
        typer.echo("  Cache: identity incomplete; cache disabled")
    typer.echo("  No Slurm job was submitted; this command only prepared local state.")


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        return float(value)
    return None


def _format_cache_age(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    bounded = max(0.0, seconds)
    if bounded < 60:
        return f"{bounded:.0f}s"
    if bounded < 3600:
        return f"{bounded / 60:.1f}m"
    return f"{bounded / 3600:.2f}h"


def _payload(attempt: TestAttemptData, root: Path) -> dict[str, object]:
    return {
        "id": attempt.id,
        "kind": attempt.kind,
        "state": attempt.state,
        "case": attempt.case,
        "profile": attempt.profile,
        "adapter": attempt.adapter,
        "adapter_version": attempt.adapter_version,
        "source_commit": attempt.source_commit,
        "executable_hash": attempt.executable_hash,
        "input_hash": attempt.input_hash,
        "cache_key": attempt.cache_key,
        "created_at": attempt.created_at,
        "updated_at": attempt.updated_at,
        "started_at": attempt.started_at,
        "finished_at": attempt.finished_at,
        "observation": attempt.observation,
        "cached_from": attempt.cached_from,
        "path": attempt.attempt_dir.relative_to(root).as_posix(),
    }


def _project_root(path: Path) -> Path:
    try:
        return find_project_root(path.resolve())
    except SimctlError as exc:
        _fail(exc)


def _fail(exc: Exception) -> NoReturn:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=2) from exc


def _require_success(result: ActionResult) -> None:
    if result.status is not ActionStatus.SUCCESS:
        _fail(RuntimeError(result.message))


__all__ = ["clean", "debug", "list_attempts", "record", "smoke"]
