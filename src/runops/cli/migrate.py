"""CLI commands for runops project-state migrations."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from runops.application.operator.migrations import (
    Migration,
    MigrationError,
    MigrationResult,
    available_migrations,
    get_migration,
    parse_migration_reference,
    run_migration,
)
from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root

migrate_app = typer.Typer(
    name="migrate",
    help="Project-state migration commands.",
    no_args_is_help=True,
)


@migrate_app.command("list")
def list_migrations(
    version: Annotated[
        str | None,
        typer.Option(
            "--version",
            "-v",
            help="Filter by major version, such as v0, 0, or 0.7.0.",
        ),
    ] = None,
) -> None:
    """List registered migrations."""
    try:
        migrations = available_migrations(version)
    except MigrationError as exc:
        typer.echo(f"Error listing migrations: {exc}", err=True)
        raise typer.Exit(code=1) from None

    if not migrations:
        typer.echo("No migrations registered.")
        return

    typer.echo("Registered migrations:")
    for migration in migrations:
        _echo_migration_summary(migration)


@migrate_app.command("show")
def show_migration(
    migration: Annotated[
        str,
        typer.Argument(help="Migration id, such as M0-0001."),
    ],
    number: Annotated[
        str | None,
        typer.Argument(
            help="Optional number when MIGRATION is a version, e.g. 'v0 0001'.",
        ),
    ] = None,
) -> None:
    """Show registered migration metadata."""
    try:
        version, normalized_number = parse_migration_reference(migration, number)
        item = get_migration(version, normalized_number)
    except MigrationError as exc:
        typer.echo(f"Error showing migration: {exc}", err=True)
        raise typer.Exit(code=1) from None

    _echo_migration_summary(item)
    typer.echo(f"    impact: {', '.join(item.impact)}")


@migrate_app.command("apply")
def apply_migration(
    migration: Annotated[
        str,
        typer.Argument(help="Migration id, such as M0-0001."),
    ],
    number: Annotated[
        str | None,
        typer.Argument(
            help="Optional number when MIGRATION is a version, e.g. 'v0 0001'.",
        ),
    ] = None,
    project: Annotated[
        Path | None,
        typer.Option(
            "--project",
            "-p",
            help="Project directory (defaults to cwd or nearest parent project).",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show planned changes without writing files.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Regenerate existing generated files when the migration supports it.",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Confirm human-gated migrations after reviewing docs/migrations/.",
        ),
    ] = False,
) -> None:
    """Apply a registered project-state migration."""
    try:
        version, normalized_number = parse_migration_reference(migration, number)
        project_root = find_project_root(project or Path.cwd())
        result = run_migration(
            version,
            normalized_number,
            project_root=project_root,
            dry_run=dry_run,
            force=force,
            yes=yes,
        )
    except (OSError, MigrationError, SimctlError) as exc:
        typer.echo(f"Error applying migration: {exc}", err=True)
        raise typer.Exit(code=1) from None

    _echo_result(result)


def _echo_migration_summary(migration: Migration) -> None:
    human_gate = "human-gate" if migration.human_gate else "no-gate"
    typer.echo(
        f"  {migration.migration_id}  {migration.title} "
        f"[{migration.migration_type}, {human_gate}]"
    )
    typer.echo(f"    {migration.description}")


def _echo_result(result: MigrationResult) -> None:
    typer.echo(f"{result.migration_id}: {result.title}")
    typer.echo(f"Status: {result.status}")
    typer.echo(result.summary)
    _echo_paths("Planned", result.planned)
    _echo_paths("Created", result.created)
    _echo_paths("Updated", result.updated)
    _echo_paths("Deleted", result.deleted)
    _echo_items("Skipped", result.skipped)
    _echo_items("Warnings", result.warnings, err=True)


def _echo_paths(label: str, paths: tuple[Path, ...]) -> None:
    if not paths:
        return
    typer.echo(f"{label}:")
    for path in paths:
        typer.echo(f"  {path.as_posix()}")


def _echo_items(label: str, items: tuple[str, ...], *, err: bool = False) -> None:
    if not items:
        return
    typer.echo(f"{label}:", err=err)
    for item in items:
        typer.echo(f"  {item}", err=err)
