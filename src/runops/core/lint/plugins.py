"""Codex plugin recommendation checks for ``runo lint``."""

from __future__ import annotations

from pathlib import Path

from runops.core.lint.models import LintContext, LintIssue
from runops.core.plugins import check_project_codex_plugins


def check_plugins(context: LintContext) -> list[LintIssue]:
    """Check project-side Codex plugin recommendation metadata."""
    issues: list[LintIssue] = []
    result = check_project_codex_plugins(context.project_root)
    for plugin_issue in result.issues:
        issues.append(
            LintIssue(
                severity=plugin_issue.severity,
                issue_id=f"plugins.metadata_{plugin_issue.severity}",
                path=_issue_path(context.project_root, plugin_issue.source),
                message=(
                    f"{plugin_issue.plugin_name}.{plugin_issue.field}: "
                    f"{plugin_issue.message}"
                    + (
                        f" Source: {plugin_issue.source}."
                        if plugin_issue.source
                        else ""
                    )
                ),
                recommendation=(
                    "Fix the project-side Codex plugin recommendation metadata, "
                    "then run `runo plugins --check` again. runops does not "
                    "install or enable user-local Codex plugins."
                ),
            )
        )
    return issues


def _issue_path(project_root: Path, source: str) -> Path | None:
    """Return the most likely project file for a plugin recommendation source."""
    sources = [part.strip() for part in source.split(",") if part.strip()]
    if len(sources) != 1:
        return None
    source = sources[0]
    if source.startswith("site:"):
        return project_root / "site.toml"
    if source.startswith("simulator:"):
        return project_root / "simulators.toml"
    if source.startswith("project:"):
        return project_root / "runops.toml"
    return None
