"""CLI command for setting up a cloned runops project."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.core.knowledge_source import _repo_name_from_url

_DEFAULT_SIMCTL_REPO = "https://github.com/Nkzono99/runops.git"


def setup(
    url: Annotated[
        Optional[str],
        typer.Argument(
            help="Git URL of the project to clone. "
            "If omitted, sets up the current directory.",
        ),
    ] = None,
    path: Annotated[
        Optional[Path],
        typer.Option(
            "--path",
            "-p",
            help="Destination directory (defaults to repo name or cwd).",
        ),
    ] = None,
    runops_repo: Annotated[
        str,
        typer.Option(
            "--runops-repo",
            help="Git URL for runops repository.",
        ),
    ] = _DEFAULT_SIMCTL_REPO,
) -> None:
    """Set up a runops project from an existing Git repository.

    Clones the repository (if URL given), then bootstraps the
    development environment (.venv, tools/, refs/) without touching
    existing configuration files (TOML, CLAUDE.md, etc.).

    Bootstrap usage (no prior install needed):
      uvx --from runops runo setup https://github.com/user/my-project.git

    Set up an already-cloned directory:
      cd my-project && runo setup
    """
    # 1. Clone if URL is given
    project_dir = _clone_project(url, path) if url else (path or Path.cwd()).resolve()

    if not project_dir.exists():
        typer.echo(f"Error: {project_dir} does not exist.", err=True)
        raise typer.Exit(code=1)

    # Verify it looks like a runops project
    simproject = project_dir / "runops.toml"
    if not simproject.exists():
        typer.echo(
            f"Error: {project_dir} does not contain runops.toml. "
            "Is this a runops project?",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(f"Setting up project in {project_dir}")

    # 2. Read simulator names from project config
    sim_names: list[str] = []
    project = None
    try:
        from runops.core.project import load_project

        project = load_project(project_dir)
        sim_names = list(project.simulators.keys())
    except Exception:
        pass  # Continue without simulator-specific setup

    created: list[str] = []
    skipped: list[str] = []

    # 3. Bootstrap .venv + tools/ + editable install
    from runops.cli.init_bootstrap import _bootstrap_environment

    _bootstrap_environment(project_dir, sim_names, runops_repo, created, skipped)

    # 4. Clone refs/ (doc repos)
    if sim_names:
        from runops.cli.init import _clone_doc_repos

        refs_created, refs_skipped = _clone_doc_repos(project_dir, sim_names)
        created.extend(refs_created)
        skipped.extend(refs_skipped)

    # 5. Ensure .runops/ skeleton exists
    from runops.cli.init_scaffold import _create_runops_skeleton

    _create_runops_skeleton(project_dir, created)

    # 6. Knowledge integration: sync sources and always refresh imports.md
    from runops.cli.init import _prepare_knowledge_imports

    sync_sources = bool(
        project is not None
        and project.knowledge is not None
        and project.knowledge.auto_sync_on_setup
        and project.knowledge.sources
    )
    _prepare_knowledge_imports(
        project_dir,
        sim_names,
        sync_sources=sync_sources,
        validate_sources=sync_sources,
    )

    # Print results
    typer.echo(f"\nProject '{project_dir.name}' is ready.")
    if created:
        typer.echo("  Set up:")
        for item in created:
            typer.echo(f"    {item}")
    if skipped:
        typer.echo("  Skipped (already exist):")
        for item in skipped:
            typer.echo(f"    {item}")

    if sys.platform == "win32":
        activate_cmd = r".venv\Scripts\activate"
    else:
        activate_cmd = "source .venv/bin/activate"
    typer.echo(f"\n  Next: cd {project_dir.name} && {activate_cmd}")
    typer.echo("  Then: runo doctor")


def _clone_project(url: str, dest: Path | None) -> Path:
    """Clone a project repository.

    Args:
        url: Git URL to clone.
        dest: Destination path. If None, uses repo name.

    Returns:
        Resolved path to the cloned directory.
    """
    if dest is None:
        dest = Path.cwd() / _repo_name_from_url(url)

    dest = dest.resolve()
    if dest.exists():
        typer.echo(f"Error: {dest} already exists.", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Cloning {url} ...")
    result = subprocess.run(
        ["git", "clone", url, str(dest)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        typer.echo(
            f"Error: git clone failed: {(result.stderr or '').strip()[:300]}",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(f"Cloned to {dest}")
    return dest
