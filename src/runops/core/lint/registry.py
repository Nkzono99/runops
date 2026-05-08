"""Registry and runner for project lint checks."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from runops.core.exceptions import SimctlError
from runops.core.lint.analysis import check_analysis
from runops.core.lint.knowledge import check_knowledge
from runops.core.lint.models import LintContext, LintIssue, LintReport
from runops.core.lint.runs import check_provenance, check_runs
from runops.core.lint.structure import check_structure

LintCheck = Callable[[LintContext], list[LintIssue]]


class LintError(SimctlError):
    """Raised when a lint request is invalid."""


@dataclass(frozen=True)
class RegisteredLintCheck:
    """One named lint check group."""

    scope: str
    description: str
    check: LintCheck


_CHECKS: tuple[RegisteredLintCheck, ...] = (
    RegisteredLintCheck(
        scope="structure",
        description="Project scaffold and managed files.",
        check=check_structure,
    ),
    RegisteredLintCheck(
        scope="runs",
        description="Run manifest readability and run_id uniqueness.",
        check=check_runs,
    ),
    RegisteredLintCheck(
        scope="provenance",
        description="Completed-run provenance completeness.",
        check=check_provenance,
    ),
    RegisteredLintCheck(
        scope="analysis",
        description="Analysis summaries and artifact indexes.",
        check=check_analysis,
    ),
    RegisteredLintCheck(
        scope="knowledge",
        description="Research agenda and curated knowledge auditability.",
        check=check_knowledge,
    ),
)


def available_scopes() -> tuple[str, ...]:
    """Return registered lint scopes."""
    return tuple(check.scope for check in _CHECKS)


def run_project_lint(
    project_root: Path,
    *,
    scopes: Iterable[str] | None = None,
) -> LintReport:
    """Run project lint checks.

    Args:
        project_root: Project root directory.
        scopes: Optional subset of registered scopes.

    Returns:
        Aggregated lint report.

    Raises:
        LintError: If a requested scope is unknown.
    """
    requested = _normalize_scopes(scopes)
    by_scope = {check.scope: check for check in _CHECKS}
    unknown = sorted(set(requested) - set(by_scope))
    if unknown:
        valid = ", ".join(available_scopes())
        raise LintError(f"Unknown lint scope(s): {', '.join(unknown)}. Valid: {valid}")

    context = LintContext(project_root=project_root.resolve())
    issues: list[LintIssue] = []
    for scope in requested:
        issues.extend(by_scope[scope].check(context))

    return LintReport(
        project_root=context.project_root,
        scopes=requested,
        issues=_deduplicate_issues(issues),
    )


def _normalize_scopes(scopes: Iterable[str] | None) -> tuple[str, ...]:
    if scopes is None:
        return available_scopes()

    result: list[str] = []
    for scope in scopes:
        normalized = scope.strip().casefold()
        if not normalized:
            continue
        result.append(normalized)
    return tuple(dict.fromkeys(result)) or available_scopes()


def _deduplicate_issues(issues: list[LintIssue]) -> tuple[LintIssue, ...]:
    deduped: dict[tuple[str, str, str, str], LintIssue] = {}
    for issue in issues:
        key = (
            issue.severity,
            issue.issue_id,
            issue.path.as_posix() if issue.path is not None else "",
            issue.message,
        )
        deduped.setdefault(key, issue)
    return tuple(deduped.values())
