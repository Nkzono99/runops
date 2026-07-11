"""Typed experiment ledger values."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ExperimentStage = Literal["pilot", "full"]
ExperimentDecision = Literal["WAIT", "EXPAND", "REVISE", "STOP"]


@dataclass(frozen=True)
class ExperimentCandidate:
    """One candidate compared by an experiment."""

    id: str
    information_gain: str
    falsification: str
    estimated_core_hours: float
    operational_risk: str


@dataclass(frozen=True)
class ExperimentAuthorizationScope:
    """Explicit scope authorizing a survey operation."""

    stage: ExperimentStage
    survey: Path
    review: Path
    max_core_hours: float


@dataclass(frozen=True)
class ExperimentAuthorization:
    """Validated authorization attached to a survey bulk operation."""

    experiment_id: str
    stage: ExperimentStage
    decision: ExperimentDecision
    proposal_path: Path
    review_path: Path | None
    selected_candidate: str


@dataclass(frozen=True)
class ExperimentRecord:
    """One experiment as represented in the canonical ledger."""

    id: str
    title: str | None
    question: str | None
    decision: ExperimentDecision
    proposal: Path
    review: Path | None
    selected_candidate: str
    cost_ceiling_core_hours: float | None
    candidates: tuple[ExperimentCandidate, ...]
    authorization: ExperimentAuthorizationScope | None = None
    migration_blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentLedger:
    """Loaded ledger plus an identity suitable for optimistic checks."""

    path: Path
    schema_version: int
    experiments: tuple[ExperimentRecord, ...]
    identity: tuple[int, int, int]


@dataclass(frozen=True)
class ExperimentCreateSpec:
    """Validated input for creating an experiment workspace."""

    title: str
    question: str
    selected_candidate: str
    cost_ceiling_core_hours: float
    candidates: tuple[ExperimentCandidate, ...]
