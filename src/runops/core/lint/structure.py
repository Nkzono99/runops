"""Project structure checks for ``runo lint``."""

from __future__ import annotations

from runops.core.lint.models import LintContext, LintIssue
from runops.harness.builder import GITIGNORE_MANAGED_START


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

    notes_readme = root / "notes" / "README.md"
    if not notes_readme.is_file():
        issues.append(
            LintIssue(
                severity="warning",
                issue_id="structure.notes_readme_missing",
                path=notes_readme,
                message="notes/README.md is missing.",
                recommendation=(
                    "Run `runo migrate apply M0-0002` or restore the scaffolded "
                    "notes guide."
                ),
                migration="M0-0002",
            )
        )

    agenda_path = root / "research" / "agenda.md"
    if not agenda_path.is_file():
        issues.append(
            LintIssue(
                severity="warning",
                issue_id="structure.research_agenda_missing",
                path=agenda_path,
                message="research/agenda.md is missing.",
                recommendation=(
                    "Run `runo migrate apply M0-0002` to add the research decision "
                    "ledger scaffold."
                ),
                migration="M0-0002",
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
