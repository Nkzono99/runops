"""Knowledge and agenda checks for ``runo lint``."""

from __future__ import annotations

import re
import sys
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.core.lint.models import LintContext, LintIssue
from runops.core.research import summarize_research_agenda


def check_knowledge(context: LintContext) -> list[LintIssue]:
    """Check curated knowledge and the mutable research agenda."""
    issues: list[LintIssue] = []
    issues.extend(_check_agenda(context))
    issues.extend(_check_facts(context))
    return issues


def _check_agenda(context: LintContext) -> list[LintIssue]:
    issues: list[LintIssue] = []
    agenda_path = context.project_root / "research" / "agenda.md"
    if not agenda_path.is_file():
        return issues

    summary = summarize_research_agenda(context.project_root)
    if bool(summary.get("is_template", False)):
        issues.append(
            LintIssue(
                severity="warning",
                issue_id="knowledge.research_agenda_template",
                path=agenda_path,
                message="research/agenda.md still looks like the scaffold template.",
                recommendation=(
                    "Fill in current beliefs, active questions, current decision, "
                    "and next actions before relying on agent automation."
                ),
            )
        )
        return issues

    text = agenda_path.read_text(encoding="utf-8", errors="replace")
    next_actions = _section_text(text, "next actions", "次の行動")
    if _has_action(next_actions) and not _has_evidence_path(next_actions):
        issues.append(
            LintIssue(
                severity="warning",
                issue_id="knowledge.next_actions_evidence_missing",
                path=agenda_path,
                message="Next Actions lacks an evidence path field.",
                recommendation=(
                    "For each next action, record the evidence path to produce or "
                    "cite so the action can update notes/reports/research cleanly."
                ),
            )
        )

    return issues


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


def _section_text(text: str, *tokens: str) -> str:
    current_matches = False
    collected: list[str] = []
    normalized_tokens = tuple(token.casefold() for token in tokens)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped.removeprefix("## ").casefold()
            current_matches = any(token in heading for token in normalized_tokens)
            continue
        if current_matches:
            collected.append(line)
    return "\n".join(collected)


def _has_action(section: str) -> bool:
    for line in section.splitlines():
        stripped = _strip_item(line)
        if not stripped or "..." in stripped:
            continue
        if re.search(r"\baction\b", stripped, flags=re.IGNORECASE):
            return True
        if re.match(r"^\d+\.\s+", line.strip()):
            return True
    return False


def _has_evidence_path(section: str) -> bool:
    for line in section.splitlines():
        stripped = _strip_item(line).casefold()
        if "evidence path" in stripped or "evidence:" in stripped:
            value = stripped.split(":", 1)[-1].strip() if ":" in stripped else stripped
            if value and value not in {"tbd", "todo", "未定"}:
                return True
    return False


def _strip_item(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("- "):
        return stripped[2:].strip()
    return stripped


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
