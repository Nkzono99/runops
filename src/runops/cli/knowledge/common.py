"""Shared helpers for knowledge CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer

from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root


def _find_root() -> Path:
    """Find project root or exit."""
    try:
        from runops.cli import knowledge as knowledge_cli

        return find_project_root(knowledge_cli.Path.cwd().resolve())
    except SimctlError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None
