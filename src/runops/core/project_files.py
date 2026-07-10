"""Neutral constants for project-managed files."""

GITIGNORE_MANAGED_START = "# >>> runops managed (auto-updated by runo update-harness)"
GITIGNORE_MANAGED_END = "# <<< runops managed"

__all__ = ["GITIGNORE_MANAGED_END", "GITIGNORE_MANAGED_START"]
