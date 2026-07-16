"""CLI callbacks for the quantity-bounded research workspace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from runops.application.research.workspace import (
    ResearchWorkspaceError,
    append_journal,
    archive_result,
    create_result,
    inspect_workspace,
    migrate_legacy_workspace,
    plan_legacy_migration,
    restore_legacy_workspace,
    restore_result,
    rotate_journal,
)
from runops.core.exceptions import ProjectConfigError, ProjectNotFoundError
from runops.core.project import find_project_root, load_project
from runops.core.research.workspace import ResearchBudget


def status(
    path: Annotated[
        Path,
        typer.Argument(help="Project root or a path inside the project."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the stable JSON status shape."),
    ] = False,
) -> None:
    """Show active narrative and artifact quantities against configured budgets."""
    root, budget = _load_workspace(path)
    workspace = inspect_workspace(root, budget=budget)
    if json_output:
        typer.echo(json.dumps(workspace.to_dict(), ensure_ascii=False, indent=2))
        return
    _render_status(workspace.to_dict())


def check(
    path: Annotated[
        Path,
        typer.Argument(help="Project root or a path inside the project."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the stable JSON status shape."),
    ] = False,
) -> None:
    """Validate research layout and budgets, exiting one on error issues."""
    root, budget = _load_workspace(path)
    workspace = inspect_workspace(root, budget=budget)
    if json_output:
        typer.echo(json.dumps(workspace.to_dict(), ensure_ascii=False, indent=2))
    else:
        _render_status(workspace.to_dict())
    if not workspace.ok:
        raise typer.Exit(code=1)


def append(
    title: Annotated[str, typer.Argument(help="Short journal entry title.")],
    body: Annotated[str, typer.Argument(help="Journal entry body.")],
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside the project."),
    ] = Path("."),
) -> None:
    """Append to the active journal, rotating first when its character limit hits."""
    root, budget = _load_workspace(path)
    try:
        result = append_journal(root, title=title, body=body, budget=budget)
    except ResearchWorkspaceError as exc:
        _workspace_error(exc)
    if result.rotated_to is not None:
        typer.echo(f"Rotated: {_relative(result.rotated_to, root)}")
    typer.echo(f"Appended: {_relative(result.path, root)} ({result.chars} chars)")


def rotate(
    path: Annotated[
        Path,
        typer.Argument(help="Project root or a path inside the project."),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option("--force", help="Rotate even when the journal is below budget."),
    ] = False,
) -> None:
    """Rotate the active journal intact into the next numbered archive segment."""
    root, budget = _load_workspace(path)
    try:
        destination = rotate_journal(root, budget=budget, force=force)
    except ResearchWorkspaceError as exc:
        _workspace_error(exc)
    if destination is None:
        typer.echo("No rotation required.")
        return
    typer.echo(f"Rotated: {_relative(destination, root)}")


def new_result(
    name: Annotated[str, typer.Argument(help="Human-readable result title.")],
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside the project."),
    ] = Path("."),
) -> None:
    """Create one result workspace with one README and an artifact directory."""
    root, _budget = _load_workspace(path)
    try:
        result = create_result(root, name)
    except ResearchWorkspaceError as exc:
        _workspace_error(exc)
    typer.echo(f"Created {result.result_id}: {_relative(result.path, root)}")


def archive(
    result_id: Annotated[str, typer.Argument(help="Active result ID to archive.")],
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside the project."),
    ] = Path("."),
) -> None:
    """Move a result intact out of the active set."""
    root, _budget = _load_workspace(path)
    try:
        destination = archive_result(root, result_id)
    except ResearchWorkspaceError as exc:
        _workspace_error(exc)
    typer.echo(f"Archived: {_relative(destination, root)}")


def restore(
    result_id: Annotated[str, typer.Argument(help="Archived result ID to restore.")],
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside the project."),
    ] = Path("."),
) -> None:
    """Restore an archived result to the active set."""
    root, _budget = _load_workspace(path)
    try:
        destination = restore_result(root, result_id)
    except ResearchWorkspaceError as exc:
        _workspace_error(exc)
    typer.echo(f"Restored: {_relative(destination, root)}")


def migrate_legacy(
    path: Annotated[
        Path,
        typer.Argument(help="Project root or a path inside the project."),
    ] = Path("."),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List reversible moves without writing."),
    ] = False,
    restore_migration: Annotated[
        bool,
        typer.Option("--restore", help="Restore paths from MIGRATION.json."),
    ] = False,
) -> None:
    """Move legacy notes/analysis/HarnessOps paths intact into a recovery archive."""
    root, _budget = _load_workspace(path)
    try:
        if restore_migration:
            if dry_run:
                typer.echo(
                    "Error: --dry-run and --restore cannot be combined", err=True
                )
                raise typer.Exit(code=2)
            moves = restore_legacy_workspace(root)
            verb = "Restored"
        else:
            moves = (
                plan_legacy_migration(root)
                if dry_run
                else migrate_legacy_workspace(root)
            )
            verb = "Would move" if dry_run else "Moved"
    except ResearchWorkspaceError as exc:
        _workspace_error(exc)
    if not moves:
        typer.echo("No legacy workspace paths found.")
        return
    typer.echo(f"{verb} {len(moves)} legacy path(s):")
    for move in moves:
        source = move.destination if restore_migration else move.source
        destination = move.source if restore_migration else move.destination
        typer.echo(f"  {_relative(source, root)} -> {_relative(destination, root)}")


def _load_workspace(path: Path) -> tuple[Path, ResearchBudget]:
    try:
        candidate = path.resolve()
        root = (
            candidate
            if (candidate / "runops.toml").is_file()
            else find_project_root(candidate)
        )
        project = load_project(root)
    except (ProjectConfigError, ProjectNotFoundError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    return root, project.research_budget


def _workspace_error(exc: ResearchWorkspaceError) -> None:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=2) from exc


def _render_status(payload: dict[str, object]) -> None:
    typer.echo(f"Research workspace: {payload['root']}")
    typer.echo(
        "Quantities: "
        f"current={payload['current_chars']} chars/{payload['current_lines']} lines, "
        f"current_paths={payload['current_path_references']}, "
        f"current_chronology={payload['current_chronological_headings']}, "
        f"journal={payload['journal_chars']} chars, "
        f"active_results={payload['active_result_count']}, "
        f"artifacts={payload['artifact_files']} files/{payload['artifact_bytes']} bytes"
    )
    issues = payload["issues"]
    if not isinstance(issues, list) or not issues:
        typer.echo("Status: OK")
        return
    for issue in issues:
        if isinstance(issue, dict):
            typer.echo(
                f"[{issue.get('severity', 'error')}] {issue.get('code', '')}: "
                f"{issue.get('path', '')} — {issue.get('message', '')}"
            )


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()
