"""Tests for the minimal research workspace domain contract."""

from __future__ import annotations

import pytest

from runops.core.exceptions import ProjectConfigError
from runops.core.research.workspace import ResearchBudget


def test_research_budget_defaults_are_quantity_based() -> None:
    budget = ResearchBudget.from_mapping(None)

    assert budget.current_chars == 20_000
    assert budget.current_lines == 50
    assert budget.current_path_references == 10
    assert budget.current_chronological_headings == 3
    assert budget.journal_segment_chars == 64_000
    assert budget.result_readme_chars == 30_000
    assert budget.active_results == 8
    assert budget.result_artifact_files == 50
    assert budget.result_artifact_bytes == 200 * 1024 * 1024


def test_research_budget_reads_nested_workspace_mapping() -> None:
    budget = ResearchBudget.from_mapping(
        {
            "workspace": {
                "current_chars": 12_000,
                "current_lines": 60,
                "current_path_references": 15,
                "current_chronological_headings": 5,
                "journal_segment_chars": 40_000,
                "result_readme_chars": 18_000,
                "active_results": 4,
                "result_artifact_files": 25,
                "result_artifact_bytes": 10_000_000,
            }
        }
    )

    assert budget.current_chars == 12_000
    assert budget.current_lines == 60
    assert budget.current_path_references == 15
    assert budget.current_chronological_headings == 5
    assert budget.journal_segment_chars == 40_000
    assert budget.result_readme_chars == 18_000
    assert budget.active_results == 4
    assert budget.result_artifact_files == 25
    assert budget.result_artifact_bytes == 10_000_000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_chars", 0),
        ("current_lines", 0),
        ("current_path_references", -1),
        ("current_chronological_headings", True),
        ("journal_segment_chars", -1),
        ("result_readme_chars", True),
        ("active_results", "8"),
        ("result_artifact_files", 0),
        ("result_artifact_bytes", 1.5),
    ],
)
def test_research_budget_rejects_invalid_positive_integers(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ProjectConfigError, match=field):
        ResearchBudget.from_mapping({"workspace": {field: value}})


def test_research_budget_rejects_unknown_workspace_fields() -> None:
    with pytest.raises(ProjectConfigError, match=r"unknown research\.workspace"):
        ResearchBudget.from_mapping({"workspace": {"days": 7}})
