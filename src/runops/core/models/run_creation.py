"""Data models for run creation and regeneration workflows."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from runops.core.case import CaseData
from runops.core.run import RunInfo
from runops.core.survey import (
    SurveyData as SurveyData,
)
from runops.core.survey import (
    SurveyPoint,
    expand_survey,
    iter_survey_points,
)


@dataclass(frozen=True)
class CreatedRunResult:
    """One created run plus non-fatal validation warnings."""

    run_info: RunInfo
    warnings: tuple[str, ...] = ()
    reused: bool = False


@dataclass(frozen=True)
class SurveyExpansionPlan:
    """Lazy, deterministic survey plan shared by preview and materialization."""

    survey_data: SurveyData
    base_case: CaseData
    effective_case: CaseData
    variation_keys: tuple[str, ...]
    candidate_count: int
    plan_hash: str
    estimated_core_hours: float | None

    def iter_points(self) -> Iterator[SurveyPoint]:
        """Stream candidates with full effective parameters and stable IDs."""
        return iter_survey_points(
            self.survey_data.axes,
            self.survey_data.linked,
            base_params=self.base_case.params,
        )

    @property
    def combinations(self) -> tuple[dict[str, Any], ...]:
        """Materialize the legacy variation-only view on explicit access."""
        return tuple(expand_survey(self.survey_data.axes, self.survey_data.linked))


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
