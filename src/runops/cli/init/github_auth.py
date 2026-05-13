"""GitHub authentication preflight for ``runo init``."""

from __future__ import annotations

import shutil
import subprocess

import typer

from runops.harness._adapters import collect_doc_repos

_GITHUB_HOST = "github.com"


def ensure_github_auth_for_simulators(
    simulator_names: list[str],
    *,
    interactive: bool,
    login: bool,
    skip: bool,
) -> None:
    """Ensure GitHub CLI auth is ready for simulator documentation repos."""
    if skip:
        return

    github_repos = _github_doc_repos(simulator_names)
    if not github_repos:
        return

    if shutil.which("gh") is None:
        typer.echo(
            "GitHub authentication is required before initializing this project, "
            "but the `gh` command was not found.",
            err=True,
        )
        typer.echo(
            "Install GitHub CLI and run `gh auth login`, or rerun with "
            "`--skip-github-auth-check` to continue without preflight.",
            err=True,
        )
        raise typer.Exit(code=1)

    if _gh_auth_ok():
        return

    typer.echo(
        "GitHub authentication is required to fetch simulator documentation "
        f"for: {', '.join(sorted(github_repos))}",
        err=True,
    )

    should_login = login
    if interactive and not should_login:
        should_login = typer.confirm("Run `gh auth login` now?", default=True)

    if not should_login:
        typer.echo(
            "Run `gh auth login` first, then rerun `runo init`.",
            err=True,
        )
        raise typer.Exit(code=1)

    result = subprocess.run(
        ["gh", "auth", "login", "--hostname", _GITHUB_HOST],
        check=False,
    )
    if result.returncode == 0 and _gh_auth_ok():
        typer.echo("GitHub authentication is ready.")
        return

    typer.echo(
        "GitHub authentication did not complete. Rerun `gh auth login`, then "
        "rerun `runo init`.",
        err=True,
    )
    raise typer.Exit(code=1)


def _github_doc_repos(simulator_names: list[str]) -> set[str]:
    repos: set[str] = set()
    for url, dest in collect_doc_repos(simulator_names):
        if _GITHUB_HOST in url:
            repos.add(dest)
    return repos


def _gh_auth_ok() -> bool:
    result = subprocess.run(
        ["gh", "auth", "status", "--hostname", _GITHUB_HOST],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.returncode == 0
