"""GitHub authentication preflight for GitHub-backed simulator resources."""

from __future__ import annotations

import shutil
import subprocess

import typer

from runops.harness._adapters import collect_doc_repos, collect_pip_packages

_GITHUB_HOST = "github.com"


def ensure_github_auth_for_simulators(
    simulator_names: list[str],
    *,
    interactive: bool,
    login: bool,
    skip: bool,
    include_refs: bool = False,
) -> None:
    """Ensure GitHub CLI auth is ready for simulator package/ref access."""
    if skip:
        return

    github_resources = _github_resources(
        simulator_names,
        include_refs=include_refs,
    )
    if not github_resources:
        return

    if shutil.which("gh") is None:
        typer.echo(
            "GitHub authentication is required before installing or cloning "
            "GitHub-backed simulator resources, but the `gh` command was not "
            "found.",
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
        "GitHub authentication is required to access simulator GitHub "
        f"resources for: {', '.join(sorted(github_resources))}",
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


def _github_resources(
    simulator_names: list[str],
    *,
    include_refs: bool,
) -> set[str]:
    resources: set[str] = set()
    for package in collect_pip_packages(simulator_names):
        if _is_github_resource(package):
            resources.add(_display_package(package))

    if include_refs:
        for url, dest in collect_doc_repos(simulator_names):
            if _is_github_resource(url):
                resources.add(f"refs/{dest}")
    return resources


def _is_github_resource(value: str) -> bool:
    return _GITHUB_HOST in value.lower()


def _display_package(package: str) -> str:
    name, separator, _source = package.partition(" @ ")
    if separator and name.strip():
        return f"package {name.strip()}"
    return f"package {package}"


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
