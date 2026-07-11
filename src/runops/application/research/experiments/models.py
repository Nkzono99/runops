"""Typed experiment ledger values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ExperimentStage = Literal["pilot", "full"]
ExperimentDecision = Literal["WAIT", "EXPAND", "REVISE", "STOP"]
IssueSeverity = Literal["error", "warning"]
ExperimentPhase = Literal[
    "blocked",
    "proposed",
    "pilot-planned",
    "pilot-ready",
    "pilot-active",
    "review-pending",
    "full-authorized",
    "full-active",
    "revising",
    "stopped",
    "completed",
]


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


@dataclass(frozen=True)
class ExperimentIssue:
    """One deterministic integrity finding."""

    severity: IssueSeverity
    code: str
    message: str
    path: Path | None = None

    def to_dict(self, project_root: Path) -> dict[str, str]:
        data = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.path is not None:
            data["path"] = (
                self.path.resolve().relative_to(project_root.resolve()).as_posix()
            )
        return data


@dataclass(frozen=True)
class ExperimentProjection:
    """Read-only operational view derived from canonical project state."""

    experiment: ExperimentRecord
    phase: ExperimentPhase
    surveys: tuple[Path, ...]
    run_counts: Mapping[str, int]
    required_artifacts: int
    present_artifacts: int
    blockers: tuple[ExperimentIssue, ...]
    warnings: tuple[ExperimentIssue, ...]
    next_actions: tuple[str, ...]
    next_commands: tuple[str, ...]

    def to_dict(self, project_root: Path) -> dict[str, Any]:
        def display(path: Path) -> str:
            return path.resolve().relative_to(project_root.resolve()).as_posix()

        return {
            "experiment": {
                "id": self.experiment.id,
                "title": self.experiment.title,
                "question": self.experiment.question,
                "decision": self.experiment.decision,
                "selected_candidate": self.experiment.selected_candidate,
            },
            "phase": self.phase,
            "surveys": [display(path) for path in self.surveys],
            "run_counts": dict(self.run_counts),
            "artifact_readiness": {
                "required": self.required_artifacts,
                "present": self.present_artifacts,
            },
            "blockers": [item.to_dict(project_root) for item in self.blockers],
            "warnings": [item.to_dict(project_root) for item in self.warnings],
            "next_actions": list(self.next_actions),
            "next_commands": list(self.next_commands),
        }
