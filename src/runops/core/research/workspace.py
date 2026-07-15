"""Domain contract for the quantity-bounded research workspace."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from runops.core.exceptions import ProjectConfigError


@dataclass(frozen=True)
class ResearchBudget:
    """Deterministic limits for the active research workspace.

    The limits are deliberately based on visible quantity rather than elapsed
    time.  Reaching a limit triggers rotation, archival, or a lint issue; it
    never authorizes deletion or semantic summarization.
    """

    current_chars: int = 20_000
    journal_segment_chars: int = 64_000
    result_readme_chars: int = 30_000
    active_results: int = 8
    result_artifact_files: int = 50
    result_artifact_bytes: int = 200 * 1024 * 1024

    @classmethod
    def from_mapping(cls, research: object | None) -> ResearchBudget:
        """Build a budget from the optional ``[research.workspace]`` table."""
        if research is None:
            return cls()
        if not isinstance(research, dict):
            raise ProjectConfigError("[research] must be a TOML table")

        workspace = research.get("workspace")
        if workspace is None:
            return cls()
        if not isinstance(workspace, dict):
            raise ProjectConfigError("[research.workspace] must be a TOML table")

        known = {item.name for item in fields(cls)}
        unknown = sorted(set(workspace) - known)
        if unknown:
            joined = ", ".join(unknown)
            raise ProjectConfigError(f"unknown research.workspace field(s): {joined}")

        values: dict[str, int] = {}
        for name, value in workspace.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ProjectConfigError(
                    f"research.workspace.{name} must be a positive integer"
                )
            values[name] = value
        return cls(**values)

    def to_dict(self) -> dict[str, int]:
        """Return the public JSON-serializable budget shape."""
        return {
            "current_chars": self.current_chars,
            "journal_segment_chars": self.journal_segment_chars,
            "result_readme_chars": self.result_readme_chars,
            "active_results": self.active_results,
            "result_artifact_files": self.result_artifact_files,
            "result_artifact_bytes": self.result_artifact_bytes,
        }


def research_budget_from_raw(raw: dict[str, Any]) -> ResearchBudget:
    """Extract the research workspace budget from parsed ``runops.toml``."""
    return ResearchBudget.from_mapping(raw.get("research"))
