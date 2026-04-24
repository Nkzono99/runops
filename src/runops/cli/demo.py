"""CLI commands for demo replay tooling."""

from __future__ import annotations

from pathlib import Path

import typer

from runops.core.demo_import import import_codex_session_log
from runops.core.demo_replay import build_demo_replay_ui
from runops.core.exceptions import DemoReplayError, SessionImportError

demo_app = typer.Typer(
    name="demo",
    help="Demo replay and session import commands.",
)


@demo_app.command("import-codex-session")
def import_codex_session(
    session_log: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Codex session JSONL to import.",
    ),
    out: Path = typer.Option(
        ...,
        "--out",
        dir_okay=False,
        writable=True,
        resolve_path=True,
        help="Output path for normalized demo events JSONL.",
    ),
    workspace_root: Path = typer.Option(
        Path("."),
        "--workspace-root",
        exists=True,
        file_okay=False,
        resolve_path=True,
        help="Project root used to relativize imported file paths.",
    ),
) -> None:
    """Convert one Codex session log into replay-friendly demo events."""
    try:
        result = import_codex_session_log(
            session_log,
            out,
            workspace_root=workspace_root,
        )
    except SessionImportError as exc:
        typer.secho(f"Error: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Imported {result.imported_events} demo events to {result.output_path}")
    if result.session_id:
        typer.echo(f"Session: {result.session_id}")
    if result.event_counts:
        summary = ", ".join(
            f"{event_type}={count}"
            for event_type, count in sorted(result.event_counts.items())
        )
        typer.echo(f"Event types: {summary}")


@demo_app.command("render-replay")
def render_replay(
    events: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Normalized demo events JSONL to replay.",
    ),
    out: Path = typer.Option(
        ...,
        "--out",
        dir_okay=False,
        writable=True,
        resolve_path=True,
        help="Output HTML path for the replay UI.",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Optional page title for the replay UI.",
    ),
    subtitle: str | None = typer.Option(
        None,
        "--subtitle",
        help="Optional subtitle shown under the title.",
    ),
) -> None:
    """Render a self-contained replay HTML UI from demo events."""
    try:
        result = build_demo_replay_ui(
            events,
            out,
            title=title,
            subtitle=subtitle,
        )
    except DemoReplayError as exc:
        typer.secho(f"Error: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Rendered replay UI to {result.output_path}")
    typer.echo(
        f"Title: {result.title} "
        f"({result.event_count} events, {result.file_count} files)"
    )


@demo_app.command("build-codex-replay")
def build_codex_replay(
    session_log: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Codex session JSONL to import and render.",
    ),
    out: Path = typer.Option(
        ...,
        "--out",
        dir_okay=False,
        writable=True,
        resolve_path=True,
        help="Output HTML path for the replay UI.",
    ),
    workspace_root: Path = typer.Option(
        Path("."),
        "--workspace-root",
        exists=True,
        file_okay=False,
        resolve_path=True,
        help="Project root used to relativize imported file paths.",
    ),
    events_out: Path | None = typer.Option(
        None,
        "--events-out",
        dir_okay=False,
        writable=True,
        resolve_path=True,
        help="Optional output path for the normalized demo events JSONL.",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Optional page title for the replay UI.",
    ),
    subtitle: str | None = typer.Option(
        None,
        "--subtitle",
        help="Optional subtitle shown under the title.",
    ),
) -> None:
    """Import a Codex session log and render a replay UI in one step."""
    resolved_events_out = events_out or out.with_suffix(".events.jsonl")

    try:
        import_result = import_codex_session_log(
            session_log,
            resolved_events_out,
            workspace_root=workspace_root,
        )
        replay_result = build_demo_replay_ui(
            resolved_events_out,
            out,
            title=title,
            subtitle=subtitle,
        )
    except (SessionImportError, DemoReplayError) as exc:
        typer.secho(f"Error: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Imported {import_result.imported_events} events to {resolved_events_out}"
    )
    typer.echo(
        f"Rendered replay UI to {replay_result.output_path} "
        f"({replay_result.event_count} events, {replay_result.file_count} files)"
    )
