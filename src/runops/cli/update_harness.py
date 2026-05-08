"""CLI command for updating harness files in an existing project.

``runo update-harness`` re-renders all harness-managed templates (CLAUDE.md,
AGENTS.md, .claude/skills/, .claude/rules/, .claude/settings.json,
.vscode/settings.json, the managed block inside ``.gitignore``, etc.) from
the current version of runops and writes them into the project. It also
backfills the visible ``notes/``, ``materials/``, and ``research/`` workspace
scaffold when those paths are missing.

Collision detection:  If the on-disk file matches the hash recorded in
``.runops/harness.lock``, it is assumed to be unedited and is silently
overwritten.  Otherwise the new content is written to ``<path>.new`` so
the user can merge manually.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.cli.init.scaffold import (
    _create_materials_skeleton,
    _create_notes_skeleton,
    _create_research_skeleton,
)
from runops.cli.update_harness_tools import (
    _REEXEC_ENV_VAR,
    _editable_install_needs_refresh,
    _pull_tools_repo,
    _reinstall_editable,
    _restart_with_skip_pull,
)
from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root, load_project
from runops.harness.builder import (
    GITIGNORE_PATH,
    build_gitignore_file,
    build_harness_bundle,
    build_managed_gitignore_block,
    hash_file,
    hash_managed_gitignore_block,
    hash_text,
    load_harness_lock,
    read_upstream_feedback_setting,
    replace_managed_gitignore_block,
    save_harness_lock,
)


def _get_knowledge_imports_path(project_dir: Path) -> str:
    """Return the knowledge imports relative path, if any."""
    imports_file = project_dir / ".runops" / "knowledge" / "enabled" / "imports.md"
    if imports_file.is_file():
        return ".runops/knowledge/enabled/imports.md"
    return ""


def _workspace_target_requested(
    only_prefixes: list[str] | None,
    target: str,
) -> bool:
    """Return whether ``target`` should be considered for workspace backfill."""
    if only_prefixes is None:
        return True
    normalized = f"{target}/"
    return any(
        prefix == target or prefix.startswith(normalized) for prefix in only_prefixes
    )


def _harness_path_requested(
    only_prefixes: list[str] | None,
    rel_path: str,
) -> bool:
    """Return whether ``rel_path`` should be processed by update-harness."""
    if only_prefixes is None:
        return True
    return any(
        rel_path == prefix or rel_path.startswith(prefix) for prefix in only_prefixes
    )


def _missing_workspace_scaffold(
    project_dir: Path,
    *,
    include_notes: bool,
    include_materials: bool,
    include_research: bool,
) -> list[str]:
    """Return missing visible workspace scaffold paths."""
    expected: list[str] = []
    if include_notes:
        expected.extend(
            [
                "notes/",
                "notes/reports/",
                "notes/history/",
                "notes/README.md",
            ]
        )
    if include_materials:
        expected.extend(
            [
                "materials/",
                "materials/papers/",
                "materials/manuals/",
                "materials/figures/",
                "materials/snippets/",
                "materials/README.md",
                "materials/index.toml",
            ]
        )
    if include_research:
        expected.extend(
            [
                "research/",
                "research/README.md",
                "research/agenda.md",
                "research/proposals/",
                "research/proposals/.gitkeep",
                "research/reviews/",
                "research/reviews/.gitkeep",
            ]
        )

    missing: list[str] = []
    for rel_path in expected:
        full_path = project_dir / rel_path.rstrip("/")
        if not full_path.exists():
            missing.append(rel_path)
    return missing


def update_harness(
    path: Annotated[
        Optional[Path],
        typer.Argument(help="Project directory (defaults to cwd)."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be updated without writing."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite even if user-edited."),
    ] = False,
    adopt: Annotated[
        bool,
        typer.Option(
            "--adopt",
            help="Adopt current on-disk files into the lock without overwriting.",
        ),
    ] = False,
    skip_pull: Annotated[
        bool,
        typer.Option("--skip-pull", help="Skip 'git pull' on tools/runops."),
    ] = False,
    only: Annotated[
        Optional[str],
        typer.Option(
            "--only",
            help=(
                "Comma-separated list of files to update"
                " (e.g. 'CLAUDE.md,.claude/rules,.vscode,notes,materials,"
                "research')."
            ),
        ),
    ] = None,
) -> None:
    """Re-render harness files from the current runops templates.

    Files that have not been manually edited since the last init/update
    are silently overwritten.  Files with user edits are written as
    ``<path>.new`` — review the diff and merge manually.

    Use ``--force`` to overwrite all files regardless of user edits.
    Use ``--adopt`` to accept the current on-disk state into the lock
    (useful for first-time migration of an existing project).

    Examples:
      runo update-harness                   # update all harness files
      runo update-harness --dry-run         # preview changes
      runo update-harness --force           # force-overwrite everything
      runo update-harness --adopt           # lock current state
      runo update-harness --only CLAUDE.md  # update a single file
    """
    project_dir = (path or Path.cwd()).resolve()

    # Locate project root
    try:
        project_dir = find_project_root(project_dir)
    except SimctlError:
        typer.echo("No runops.toml found. Are you inside a runops project?")
        raise typer.Exit(code=1) from None

    # Pull tools/runops
    if not skip_pull and not dry_run:
        pull_status = _pull_tools_repo(project_dir)
        if pull_status is not None:
            typer.echo(f"tools/runops: {pull_status}")
            if pull_status.startswith("blocked:"):
                typer.echo(
                    "Local tools/runops changes were preserved. Commit/stash "
                    "them, use patch-runops to finish the local patch, or rerun "
                    "with --skip-pull to refresh harness files from the current "
                    "local tools/runops checkout.",
                    err=True,
                )
                raise typer.Exit(code=1)
            needs_refresh = pull_status == "updated"
            if pull_status == "already up to date":
                needs_refresh = _editable_install_needs_refresh(project_dir)
            if needs_refresh and os.environ.get(_REEXEC_ENV_VAR) != "1":
                install_status = _reinstall_editable(project_dir)
                if install_status is not None:
                    typer.echo(f"tools/runops: {install_status}")
                _restart_with_skip_pull()

    # Load project info
    project = load_project(project_dir)
    project_name = project.name
    simulator_names = list(project.simulators.keys())

    # Read [harness] settings
    upstream_feedback = read_upstream_feedback_setting(project_dir)

    knowledge_imports_path = _get_knowledge_imports_path(project_dir)

    harness = build_harness_bundle(
        project_name,
        simulator_names,
        upstream_feedback=upstream_feedback,
        knowledge_imports_path=knowledge_imports_path,
    )

    # Filter by --only
    only_prefixes: list[str] | None = None
    if only:
        only_prefixes = [p.strip() for p in only.split(",") if p.strip()]

    lock = load_harness_lock(project_dir)
    new_hashes = harness.hashes()

    overwritten: list[str] = []
    written_new: list[str] = []
    unchanged: list[str] = []
    adopted: list[str] = []
    backfilled_workspace: list[str] = []
    updated_lock = dict(lock)

    for rel_path in sorted(harness.files):
        if not _harness_path_requested(only_prefixes, rel_path):
            continue

        full_path = project_dir / rel_path
        content = harness.files[rel_path]
        template_hash = new_hashes[rel_path]

        if adopt:
            # Lock the current on-disk state (or the template if new)
            disk_hash = hash_file(full_path)
            if disk_hash is not None:
                updated_lock[rel_path] = disk_hash
                adopted.append(rel_path)
            else:
                # File doesn't exist — write it and lock the template hash
                if not dry_run:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(content, encoding="utf-8")
                    updated_lock[rel_path] = template_hash
                overwritten.append(rel_path)
            continue

        if not full_path.exists():
            # New file — just create it
            if not dry_run:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
                updated_lock[rel_path] = template_hash
            overwritten.append(rel_path)
            continue

        disk_hash = hash_file(full_path)
        locked_hash = lock.get(rel_path)

        # Check whether the template itself changed
        if disk_hash == template_hash:
            # Already up to date
            updated_lock[rel_path] = template_hash
            unchanged.append(rel_path)
            continue

        if force or (locked_hash is not None and disk_hash == locked_hash):
            # Unedited (matches lock) or --force: safe to overwrite
            if not dry_run:
                full_path.write_text(content, encoding="utf-8")
                updated_lock[rel_path] = template_hash
            overwritten.append(rel_path)
        else:
            # User-edited: write .new file
            new_path = full_path.parent / (full_path.name + ".new")
            if not dry_run:
                new_path.write_text(content, encoding="utf-8")
                updated_lock[rel_path] = template_hash
            written_new.append(rel_path)

    if _harness_path_requested(only_prefixes, GITIGNORE_PATH):
        gitignore_path = project_dir / GITIGNORE_PATH
        managed_block = build_managed_gitignore_block()
        managed_hash = hash_text(managed_block)
        locked_hash = lock.get(GITIGNORE_PATH)
        new_path = gitignore_path.parent / (gitignore_path.name + ".new")

        if adopt and not gitignore_path.exists():
            if not dry_run:
                gitignore_path.write_text(build_gitignore_file(), encoding="utf-8")
                updated_lock[GITIGNORE_PATH] = managed_hash
            overwritten.append(GITIGNORE_PATH)
        elif gitignore_path.exists():
            try:
                disk_text = gitignore_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                disk_text = ""

            disk_hash = hash_managed_gitignore_block(disk_text)
            if adopt and disk_hash is not None:
                updated_lock[GITIGNORE_PATH] = disk_hash
                adopted.append(GITIGNORE_PATH)
            elif disk_hash is None:
                if not dry_run:
                    new_path.write_text(
                        build_gitignore_file(disk_text),
                        encoding="utf-8",
                    )
                written_new.append(GITIGNORE_PATH)
            else:
                updated_text = replace_managed_gitignore_block(disk_text)
                if updated_text is None:
                    if not dry_run:
                        new_path.write_text(
                            build_gitignore_file(disk_text),
                            encoding="utf-8",
                        )
                    written_new.append(GITIGNORE_PATH)
                elif disk_hash == managed_hash:
                    updated_lock[GITIGNORE_PATH] = managed_hash
                    unchanged.append(GITIGNORE_PATH)
                elif force or (locked_hash is not None and disk_hash == locked_hash):
                    if not dry_run:
                        gitignore_path.write_text(updated_text, encoding="utf-8")
                        updated_lock[GITIGNORE_PATH] = managed_hash
                    overwritten.append(GITIGNORE_PATH)
                else:
                    if not dry_run:
                        new_path.write_text(updated_text, encoding="utf-8")
                        updated_lock[GITIGNORE_PATH] = managed_hash
                    written_new.append(GITIGNORE_PATH)
        else:
            if not dry_run:
                gitignore_path.write_text(build_gitignore_file(), encoding="utf-8")
                updated_lock[GITIGNORE_PATH] = managed_hash
            overwritten.append(GITIGNORE_PATH)

    include_notes = _workspace_target_requested(only_prefixes, "notes")
    include_materials = _workspace_target_requested(only_prefixes, "materials")
    include_research = _workspace_target_requested(only_prefixes, "research")
    if dry_run:
        backfilled_workspace.extend(
            _missing_workspace_scaffold(
                project_dir,
                include_notes=include_notes,
                include_materials=include_materials,
                include_research=include_research,
            )
        )
    else:
        if include_notes:
            _create_notes_skeleton(project_dir, backfilled_workspace)
        if include_materials:
            _create_materials_skeleton(project_dir, backfilled_workspace)
        if include_research:
            _create_research_skeleton(project_dir, backfilled_workspace)

    if not dry_run:
        save_harness_lock(project_dir, updated_lock)

    # Report
    prefix = "[dry-run] " if dry_run else ""
    if adopt and adopted:
        typer.echo(f"{prefix}Adopted {len(adopted)} file(s) into harness.lock:")
        for p in adopted:
            typer.echo(f"  {p}")
    if overwritten:
        typer.echo(f"{prefix}Updated {len(overwritten)} file(s):")
        for p in overwritten:
            typer.echo(f"  {p}")
    if written_new:
        n_new = len(written_new)
        typer.echo(
            f"\n{prefix}\u26a0 {n_new} file(s) written as .new "
            "(user-edited originals preserved):",
            err=True,
        )
        for p in written_new:
            typer.echo(f"  {p}.new", err=True)
        typer.echo("", err=True)
        typer.echo(
            "To accept new versions:  runo update-harness --force",
            err=True,
        )
        first_new = written_new[0]
        typer.echo(
            f"To compare:              diff {first_new} {first_new}.new",
            err=True,
        )
        typer.echo(
            "To dismiss:              "
            "rm *.new .claude/**/*.new .codex/**/*.new .agents/**/*.new",
            err=True,
        )
    if unchanged:
        typer.echo(f"{prefix}{len(unchanged)} file(s) already up to date.")
    if backfilled_workspace:
        typer.echo(f"{prefix}Backfilled {len(backfilled_workspace)} workspace item(s):")
        for p in backfilled_workspace:
            typer.echo(f"  {p}")
    if not overwritten and not written_new and not adopted and not backfilled_workspace:
        typer.echo(f"{prefix}All harness files are up to date.")
