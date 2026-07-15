"""Project structure checks for ``runo lint``."""

from __future__ import annotations

from runops.application.operator.lint.models import LintContext, LintIssue
from runops.core.project_files import GITIGNORE_MANAGED_START


def check_structure(context: LintContext) -> list[LintIssue]:
    """Check baseline project files that make a project legible."""
    root = context.project_root
    issues: list[LintIssue] = []

    campaign_path = root / "campaign.toml"
    if not campaign_path.is_file():
        issues.append(
            LintIssue(
                severity="error",
                issue_id="structure.campaign_missing",
                path=campaign_path,
                message="campaign.toml is missing.",
                recommendation=(
                    "Create campaign.toml so agents can read the project goal."
                ),
            )
        )

    current = root / "research" / "CURRENT.md"
    if not current.is_file():
        issues.append(
            LintIssue(
                severity="warning",
                issue_id="structure.research_current_missing",
                path=current,
                message="research/CURRENT.md is missing.",
                recommendation=(
                    "Run `runo update-harness --only research` to restore the "
                    "minimal research scaffold."
                ),
            )
        )

    journal = root / "research" / "journal" / "active.md"
    if not journal.is_file():
        issues.append(
            LintIssue(
                severity="warning",
                issue_id="structure.research_journal_missing",
                path=journal,
                message="research/journal/active.md is missing.",
                recommendation=(
                    "Run `runo update-harness --only research` to restore the "
                    "minimal research scaffold."
                ),
            )
        )

    gitignore_path = root / ".gitignore"
    if not gitignore_path.is_file():
        issues.append(
            LintIssue(
                severity="warning",
                issue_id="structure.gitignore_missing",
                path=gitignore_path,
                message=".gitignore is missing.",
                recommendation=(
                    "Regenerate or update the runops managed .gitignore block."
                ),
            )
        )
    elif GITIGNORE_MANAGED_START not in gitignore_path.read_text(
        encoding="utf-8", errors="replace"
    ):
        issues.append(
            LintIssue(
                severity="warning",
                issue_id="structure.gitignore_managed_block_missing",
                path=gitignore_path,
                message=".gitignore has no runops managed block.",
                recommendation=(
                    "Run `runo update-harness` or add the managed block from the "
                    "current scaffold."
                ),
            )
        )

    return issues
