"""Knowledge and agenda checks for ``runo lint``."""

from __future__ import annotations

import sys
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.application.operator.lint.models import LintContext, LintIssue
from runops.application.research.workspace import inspect_workspace
from runops.core.project import load_project


def check_knowledge(context: LintContext) -> list[LintIssue]:
    """Check curated knowledge and the bounded research workspace."""
    issues: list[LintIssue] = []
    issues.extend(_check_research_workspace(context))
    issues.extend(_check_facts(context))
    return issues


def _check_research_workspace(context: LintContext) -> list[LintIssue]:
    status = inspect_workspace(
        context.project_root,
        budget=load_project(context.project_root).research_budget,
    )
    return [
        LintIssue(
            severity=issue.severity,
            issue_id=f"knowledge.{issue.code}",
            path=context.project_root / issue.path,
            message=issue.message,
            recommendation="Run `runo research status` and archive or rotate intact.",
        )
        for issue in status.issues
    ]


def _check_facts(context: LintContext) -> list[LintIssue]:
    facts_path = context.project_root / ".runops" / "facts.toml"
    if not facts_path.is_file():
        return []

    try:
        with open(facts_path, "rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        return [
            LintIssue(
                severity="error",
                issue_id="knowledge.facts_invalid",
                path=facts_path,
                message=f"Invalid TOML in .runops/facts.toml: {exc}",
                recommendation="Fix facts.toml before using curated facts.",
            )
        ]

    issues: list[LintIssue] = []
    missing_count = sum(
        1 for fact in _iter_fact_like_tables(data) if not _has_source_field(fact)
    )
    if missing_count:
        noun = "entry" if missing_count == 1 else "entries"
        verb = "lacks" if missing_count == 1 else "lack"
        issues.append(
            LintIssue(
                severity="warning",
                issue_id="knowledge.fact_source_missing",
                path=facts_path,
                message=f"{missing_count} fact-like {noun} {verb} a source path.",
                recommendation=(
                    "Add source/source_path/evidence fields so facts remain auditable."
                ),
            )
        )
    return issues


def _iter_fact_like_tables(value: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if any(key in value for key in ("claim", "statement", "value")):
            results.append(value)
        for child in value.values():
            results.extend(_iter_fact_like_tables(child))
    elif isinstance(value, list):
        for child in value:
            results.extend(_iter_fact_like_tables(child))
    return results


def _has_source_field(fact: dict[str, Any]) -> bool:
    return any(
        str(fact.get(key, "")).strip()
        for key in ("source", "source_path", "evidence", "evidence_path", "path")
    )
