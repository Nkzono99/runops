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

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer

from runops import __version__
from runops.application.gateway.plugins import build_project_codex_plugin_inventory
from runops.application.operator.harness_upgrade import (
    HarnessUpgradePlan,
    HarnessUpgradeRequest,
    HarnessUpgradeStep,
    HarnessUpgradeStepError,
    apply_harness_upgrade,
    plan_harness_upgrade,
)
from runops.cli.init.knowledge import _prepare_knowledge_imports
from runops.cli.init.scaffold import (
    _create_materials_skeleton,
    _create_notes_skeleton,
    _create_research_skeleton,
)
from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root, load_project
from runops.core.upgrade_chain import UpgradePlanError
from runops.harness._adapters import collect_doc_repos
from runops.harness.builder import (
    GITIGNORE_PATH,
    applied_harness_runops_version,
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


def _has_reference_repos(project_dir: Path, simulator_names: list[str]) -> bool:
    """Return whether this project has adapter-declared refs mirrors."""
    if not simulator_names:
        return False
    return any(
        (project_dir / "refs" / dest).is_dir()
        for _url, dest in collect_doc_repos(simulator_names)
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
                "research/experiments.toml",
                "research/paper_requests.toml",
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


def _echo_upgrade_plan(plan: HarnessUpgradePlan) -> None:
    """Print a human-readable update-harness chain plan."""
    typer.echo(f"project harness applied: {plan.applied_version}")
    typer.echo(f"current runops runtime:  {plan.current_runtime_version}")
    typer.echo(f"target runops:           {plan.target_version}")
    typer.echo("")
    if not plan.steps:
        typer.echo("planned upgrade chain: already at target")
        return
    typer.echo("planned upgrade chain:")
    for index, step in enumerate(plan.steps, start=1):
        typer.echo(f"{index}. {step.from_version} -> {step.to_version}")


def _echo_upgrade_step(
    index: int,
    total: int,
    step: HarnessUpgradeStep,
) -> None:
    """Render one exact-version command immediately before application."""
    typer.echo(f"\n[{index}/{total}] runops {step.from_version} -> {step.to_version}")
    typer.echo(" ".join(step.command))


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
        typer.Option(
            "--skip-pull",
            help="Deprecated no-op kept for older update scripts.",
        ),
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
    no_harnessops: Annotated[
        bool,
        typer.Option(
            "--no-harnessops",
            help="Do not initialize or update the project-side HarnessOps overlay.",
        ),
    ] = False,
    plan: Annotated[
        bool,
        typer.Option(
            "--plan",
            help="Show a versioned update-harness chain without applying it.",
        ),
    ] = False,
    apply_chain: Annotated[
        bool,
        typer.Option(
            "--apply-chain",
            help="Apply the versioned update-harness chain via uvx exact versions.",
        ),
    ] = False,
    target: Annotated[
        str | None,
        typer.Option(
            "--target",
            help="Target runops version for --plan/--apply-chain (exact or latest).",
        ),
    ] = None,
    allow_major: Annotated[
        bool,
        typer.Option(
            "--allow-major",
            help="Allow --plan/--apply-chain to cross a major version boundary.",
        ),
    ] = False,
    upgrade_step: Annotated[
        bool,
        typer.Option(
            "--upgrade-step",
            help="Internal: apply one exact-version upgrade step.",
            hidden=True,
        ),
    ] = False,
    from_version: Annotated[
        str | None,
        typer.Option(
            "--from-version",
            help="Internal: source version for --upgrade-step.",
            hidden=True,
        ),
    ] = None,
) -> None:
    """Re-render harness files from the current runops templates.

    Files that have not been manually edited since the last init/update
    are silently overwritten.  Files with user edits are written as
    ``<path>.new`` — review the diff and merge manually.
    When the external ``hops`` CLI is available, this command also delegates
    HarnessOps overlay/agent-bridge refresh to ``hops update-harness``.

    Use ``--force`` to overwrite all files regardless of user edits.
    Use ``--adopt`` to accept the current on-disk state into the lock
    (useful for first-time migration of an existing project).

    Examples:
      runo update-harness                   # update all harness files
      runo update-harness --dry-run         # preview changes
      runo update-harness --force           # force-overwrite everything
      runo update-harness --adopt           # lock current state
      runo update-harness --only CLAUDE.md  # update a single file
      runo update-harness --no-harnessops   # skip the hops lifecycle hook
      runo update-harness --plan            # show versioned upgrade chain
      runo update-harness --apply-chain     # run chain via uvx exact versions
    """
    del skip_pull

    project_dir = (path or Path.cwd()).resolve()

    # Locate project root
    try:
        project_dir = find_project_root(project_dir)
    except SimctlError:
        typer.echo("No runops.toml found. Are you inside a runops project?")
        raise typer.Exit(code=1) from None

    if plan or apply_chain:
        if dry_run:
            typer.echo(
                "--dry-run cannot be combined with --plan/--apply-chain.",
                err=True,
            )
            raise typer.Exit(code=1)
        if adopt:
            typer.echo(
                "--adopt cannot be combined with --plan/--apply-chain.",
                err=True,
            )
            raise typer.Exit(code=1)
        if only:
            typer.echo("--only cannot be combined with --plan/--apply-chain.", err=True)
            raise typer.Exit(code=1)
        if upgrade_step:
            typer.echo(
                "--upgrade-step cannot be combined with --plan/--apply-chain.",
                err=True,
            )
            raise typer.Exit(code=1)
        try:
            upgrade_plan = plan_harness_upgrade(
                HarnessUpgradeRequest(
                    project_dir=project_dir,
                    current_runtime_version=__version__,
                    target=target,
                    allow_major=allow_major,
                    force=force,
                    no_harnessops=no_harnessops,
                ),
                applied_version_source=applied_harness_runops_version,
            )
        except UpgradePlanError as exc:
            typer.echo(f"Error planning upgrade chain: {exc}", err=True)
            raise typer.Exit(code=1) from None
        _echo_upgrade_plan(upgrade_plan)
        if apply_chain:
            if not upgrade_plan.steps:
                typer.echo("Harness is already at the requested runops target.")
            else:
                try:
                    apply_harness_upgrade(
                        upgrade_plan,
                        before_step=_echo_upgrade_step,
                    )
                except HarnessUpgradeStepError as exc:
                    typer.echo(str(exc), err=True)
                    raise typer.Exit(code=exc.returncode) from None
        return

    if target is not None or allow_major:
        typer.echo("--target/--allow-major require --plan or --apply-chain.", err=True)
        raise typer.Exit(code=1)
    if upgrade_step and from_version is None:
        typer.echo("--upgrade-step requires --from-version.", err=True)
        raise typer.Exit(code=1)

    if not upgrade_step and not dry_run and not adopt and only is None:
        try:
            plain_plan = plan_harness_upgrade(
                HarnessUpgradeRequest(
                    project_dir=project_dir,
                    current_runtime_version=__version__,
                    target=__version__,
                    allow_major=True,
                ),
                applied_version_source=applied_harness_runops_version,
                version_source=lambda: (),
            )
        except UpgradePlanError:
            plain_plan = None
        if plain_plan is not None and plain_plan.steps:
            _echo_upgrade_plan(plain_plan)
            typer.echo("")
            typer.echo(
                "This project should be upgraded through the versioned chain.",
                err=True,
            )
            typer.echo(
                "Run: uvx --from runops runo update-harness --apply-chain",
                err=True,
            )
            typer.echo(
                "Use --upgrade-step only for exact-version internal chain steps.",
                err=True,
            )
            raise typer.Exit(code=1)

    # Load project info
    project = load_project(project_dir)
    project_name = project.name
    simulator_names = list(project.simulators.keys())
    codex_plugin_recommendations = list(
        build_project_codex_plugin_inventory(project).recommendations
    )

    # Read [harness] settings
    upstream_feedback = read_upstream_feedback_setting(project_dir)

    if dry_run:
        imports_file = project_dir / ".runops" / "knowledge" / "enabled" / "imports.md"
        knowledge_imports_path = (
            ".runops/knowledge/enabled/imports.md" if imports_file.is_file() else ""
        )
    else:
        knowledge_imports_path = _prepare_knowledge_imports(
            project_dir,
            simulator_names,
            sync_sources=False,
        )

    harness = build_harness_bundle(
        project_name,
        simulator_names,
        upstream_feedback=upstream_feedback,
        knowledge_imports_path=knowledge_imports_path,
        include_reference_repos=_has_reference_repos(project_dir, simulator_names),
        codex_plugin_recommendations=codex_plugin_recommendations,
    )

    # Filter by --only
    only_prefixes: list[str] | None = None
    if only:
        only_prefixes = [p.strip() for p in only.split(",") if p.strip()]

    lock = load_harness_lock(project_dir)
    previous_runops_version = applied_harness_runops_version(project_dir)
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

    upgrade_event: dict[str, str] | None = None
    if upgrade_step and from_version is not None and not written_new:
        upgrade_event = {
            "from": from_version,
            "to": __version__,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "command": "update-harness --upgrade-step",
        }

    if not dry_run and written_new:
        save_harness_lock(
            project_dir,
            updated_lock,
            runops_version=previous_runops_version,
        )
    elif not dry_run:
        save_harness_lock(
            project_dir,
            updated_lock,
            upgrade_event=upgrade_event,
        )

    harnessops_message: str | None = None
    harnessops_failed = False
    if no_harnessops:
        harnessops_message = "HarnessOps skipped (disabled)"
    elif only_prefixes is not None:
        harnessops_message = "HarnessOps skipped (--only was used)"
    else:
        from runops.harness.harnessops import update_project_harnessops

        harnessops_result = update_project_harnessops(project_dir, dry_run=dry_run)
        harnessops_message = harnessops_result.message
        harnessops_failed = harnessops_result.status == "failed"

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
    if harnessops_message is not None:
        if harnessops_failed:
            typer.echo(f"{prefix}Warning: {harnessops_message}", err=True)
        else:
            typer.echo(f"{prefix}{harnessops_message}.")
    if (
        not overwritten
        and not written_new
        and not adopted
        and not backfilled_workspace
        and not harnessops_failed
    ):
        typer.echo(f"{prefix}All harness files are up to date.")
