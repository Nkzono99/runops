"""Complete Typer group applications composed from command callbacks."""

from __future__ import annotations

from .analyze import analyze_app
from .case import case_app
from .notes import notes_app
from .runs import runs_app

__all__ = ["analyze_app", "case_app", "notes_app", "runs_app"]
