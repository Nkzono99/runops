"""Data models for run creation and regeneration workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runops.core.case import CaseData
from runops.core.run import RunInfo
from runops.core.survey import SurveyData as SurveyData


@dataclass(frozen=True)
class CreatedRunResult:
    """One created run plus non-fatal validation warnings."""

    run_info: RunInfo
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurveyExpansionPlan:
    """Resolved survey expansion shared by dry-run and real sweep creation."""

    survey_data: SurveyData
    base_case: CaseData
    effective_case: CaseData
    combinations: tuple[dict[str, Any], ...]
    variation_keys: tuple[str, ...]


@dataclass(frozen=True)
class RegenerateResult:
    """File-level diff of a ``regenerate_run`` call."""

    run_id: str
    case_name: str
    added: tuple[str, ...]
    modified: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged: tuple[str, ...]
    work_exists: bool

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.removed)
