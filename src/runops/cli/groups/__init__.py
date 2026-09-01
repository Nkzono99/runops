"""Complete Typer group applications composed from command callbacks."""

from __future__ import annotations

from .analyze import analyze_app
from .case import case_app
from .experiments import experiments_app
from .research import research_app
from .runs import runs_app
from .tests import tests_app

__all__ = [
    "analyze_app",
    "case_app",
    "experiments_app",
    "research_app",
    "runs_app",
    "tests_app",
]
