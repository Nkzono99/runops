"""Knowledge and agenda checks for ``runo lint``."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
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
    issues.extend(_check_dispersed_experiment_narratives(context))
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
            recommendation=_research_recommendation(issue.code),
        )
        for issue in status.issues
    ]


def _research_recommendation(code: str) -> str:
    if code in {
        "current.too_many_lines",
        "current.too_many_paths",
        "current.looks_chronological",
    }:
        return (
            "Keep research/CURRENT.md as the current decision ledger; move "
            "chronology to `runo research append`, refined detail to "
            "research/results/, and exhaustive provenance to export/source indexes."
        )
    return "Run `runo research status` and archive or rotate intact."


def _check_dispersed_experiment_narratives(
    context: LintContext,
) -> list[LintIssue]:
    """Warn on narrative Markdown outside the bounded research workspace.

    Project documentation and harness policy remain valid Markdown.  The
    experiment-producing roots are intentionally stricter: prose under cases,
    runs, top-level notes, or top-level analysis should move to work, journal,
    CURRENT, or one Result README.  Known generated reports and harness files
    are excluded.
    """
    candidates: set[Path] = set()
    for directory, filenames in _walk_metadata(context.project_root):
        for filename in filenames:
            if not filename.casefold().endswith(".md"):
                continue
            path = directory / filename
            relative = path.relative_to(context.project_root)
            if _is_allowed_research_or_project_markdown(relative):
                continue
            candidates.add(path)

    return [
        LintIssue(
            severity="warning",
            issue_id="knowledge.dispersed_experiment_narrative",
            path=path,
            message=("persistent research Markdown is outside the bounded allowlist"),
            recommendation=(
                "Keep provisional prose in .runops/work, decisions in the Experiment "
                "record/journal, and durable evidence narrative in one Result README."
            ),
        )
        for path in sorted(candidates)
    ]


def _is_allowed_research_or_project_markdown(relative: Path) -> bool:
    """Keep project documentation distinct from persistent research prose."""
    if not relative.parts:
        return True
    if relative.parts[0] in {
        ".agents",
        ".claude",
        ".codex",
        ".git",
        ".github",
        ".venv",
        "_handoff",
        "docs",
        "refs",
        "src",
        "tests",
    }:
        return True
    if relative.name in {"AGENTS.md", "CLAUDE.md"}:
        return True
    if len(relative.parts) == 1 and relative.name.casefold() in {
        "readme.md",
        "changelog.md",
        "contributing.md",
        "code_of_conduct.md",
    }:
        return True
    if relative == Path("materials/README.md"):
        return True
    if relative.name == "survey_summary.md" and "summary" in relative.parts:
        return True
    if relative.name == "audit.md" and "stories" in relative.parts:
        return True
    if relative == Path("research/CURRENT.md"):
        return True
    if relative == Path("research/journal/active.md"):
        return True
    if (
        len(relative.parts) == 4
        and relative.parts[:3] == ("research", "journal", "archive")
        and re.fullmatch(r"J\d{4}\.md", relative.name) is not None
    ):
        return True
    if (
        len(relative.parts) == 4
        and relative.parts[:2] == ("research", "results")
        and relative.name == "README.md"
    ):
        return True
    if (
        len(relative.parts) == 5
        and relative.parts[:3] == ("research", "archive", "results")
        and relative.name == "README.md"
    ):
        return True
    return relative.parts[:2] in {
        (".runops", "work"),
        (".runops", "knowledge"),
        (".runops", "insights"),
    }


def _walk_metadata(root: Path) -> Iterator[tuple[Path, frozenset[str]]]:
    if not root.is_dir() or root.is_symlink():
        return
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        dirnames[:] = [
            name
            for name in dirnames
            if not (current / name).is_symlink()
            and name not in {".git", ".venv", "__pycache__", ".pytest_cache"}
        ]
        yield current, frozenset(filenames)


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
