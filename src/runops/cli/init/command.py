"""CLI facades for project initialization and environment checks."""

from runops.cli.init.github_auth import ensure_github_auth_for_simulators
from runops.cli.init.knowledge import _clone_doc_repos

from .doctor import doctor
from .workflow import init

__all__ = ["_clone_doc_repos", "doctor", "ensure_github_auth_for_simulators", "init"]
