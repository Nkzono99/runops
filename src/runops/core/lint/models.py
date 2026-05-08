"""Models for project health lint reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

SEVERITY_ORDER = {
    "info": 0,
    "warning": 1,
    "error": 2,
}


@dataclass(frozen=True)
class LintContext:
    """Context shared by project lint checks."""

    project_root: Path

    def relpath(self, path: Path) -> Path:
        """Return a stable project-relative path when possible."""
        try:
            return path.resolve().relative_to(self.project_root.resolve())
        except ValueError:
            return path


@dataclass(frozen=True)
class LintIssue:
    """One project lint finding."""

    severity: str
    issue_id: str
    path: Path | None
    message: str
    recommendation: str = ""
    migration: str = ""

    def to_dict(self, project_root: Path) -> dict[str, Any]:
        """Convert the issue to a JSON-serializable dictionary."""
        payload: dict[str, Any] = {
            "severity": self.severity,
            "id": self.issue_id,
            "message": self.message,
        }
        if self.path is not None:
            payload["path"] = _display_path(self.path, project_root)
        if self.recommendation:
            payload["recommendation"] = self.recommendation
        if self.migration:
            payload["migration"] = self.migration
        return payload


@dataclass(frozen=True)
class LintReport:
    """Aggregated lint result for a project."""

    project_root: Path
    scopes: tuple[str, ...]
    issues: tuple[LintIssue, ...]

    @property
    def error_count(self) -> int:
        """Number of error findings."""
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        """Number of warning findings."""
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def info_count(self) -> int:
        """Number of informational findings."""
        return sum(1 for issue in self.issues if issue.severity == "info")

    @property
    def status(self) -> str:
        """Project health status."""
        if self.error_count:
            return "fail"
        if self.warning_count:
            return "warning"
        return "ok"

    def sorted_issues(self) -> tuple[LintIssue, ...]:
        """Return issues ordered by severity, path, and id."""
        return tuple(
            sorted(
                self.issues,
                key=lambda issue: (
                    -SEVERITY_ORDER.get(issue.severity, 0),
                    _display_path(issue.path, self.project_root) if issue.path else "",
                    issue.issue_id,
                ),
            )
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the report to a JSON-serializable dictionary."""
        return {
            "project_root": self.project_root.as_posix(),
            "status": self.status,
            "scopes": list(self.scopes),
            "counts": {
                "error": self.error_count,
                "warning": self.warning_count,
                "info": self.info_count,
            },
            "issues": [
                issue.to_dict(self.project_root) for issue in self.sorted_issues()
            ],
        }


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
