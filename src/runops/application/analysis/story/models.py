"""Typed records for Story Acceptance Audit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SourceKind = Literal["run", "survey", "comparison", "path"]
StepStatus = Literal["blocked", "missing", "partial", "covered"]
OverallStatus = Literal["blocked", "missing", "partial", "covered"]


@dataclass(frozen=True)
class StorySource:
    """One declared source of Story evidence."""

    kind: SourceKind
    path: str


@dataclass(frozen=True)
class StoryStep:
    """One typed acceptance requirement in a Story."""

    id: str
    title: str
    required_artifacts: tuple[str, ...]
    acceptable_status: tuple[str, ...]
    claim_ceiling: str = ""
    notes: str = ""


@dataclass(frozen=True)
class StorySpec:
    """Validated Story schema version 1 document."""

    schema_version: int
    id: str
    title: str
    status: str
    sources: tuple[StorySource, ...]
    steps: tuple[StoryStep, ...]


@dataclass(frozen=True)
class ArtifactRecord:
    """Normalized artifact fields used by Story matching."""

    kind: str = ""
    path: str = ""
    title: str = ""
    description: str = ""
    status: str = "draft"
    source_scope: str = ""
    source_index: str = ""
    run_id: str = ""
    quantity: str = ""
    name: str = ""
    artifact_id: str = ""
    tags: tuple[str, ...] = ()
    present_fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ArtifactEvidence:
    """One artifact matched to one selector."""

    selector: str
    artifact: ArtifactRecord

    def to_dict(self) -> dict[str, object]:
        """Return the legacy evidence summary mapping."""
        fields = (
            ("kind", "kind"),
            ("path", "path"),
            ("title", "title"),
            ("description", "description"),
            ("status", "status"),
            ("source_scope", "source_scope"),
            ("source_index", "source_index"),
            ("run_id", "run_id"),
            ("quantity", "quantity"),
        )
        data: dict[str, object] = {}
        for output_name, attribute_name in fields:
            if output_name in self.artifact.present_fields:
                data[output_name] = getattr(self.artifact, attribute_name)
        data["selector"] = self.selector
        return data


@dataclass(frozen=True)
class StepAudit:
    """Typed acceptance result for one Story step."""

    id: str
    title: str
    status: StepStatus
    required_artifacts: tuple[str, ...]
    acceptable_status: tuple[str, ...]
    matched_artifacts: tuple[ArtifactEvidence, ...]
    weak_artifacts: tuple[ArtifactEvidence, ...]
    missing_artifacts: tuple[str, ...]
    claim_ceiling: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return the legacy per-step audit mapping."""
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "required_artifacts": list(self.required_artifacts),
            "acceptable_status": list(self.acceptable_status),
            "matched_artifacts": [item.to_dict() for item in self.matched_artifacts],
            "weak_artifacts": [item.to_dict() for item in self.weak_artifacts],
            "missing_artifacts": list(self.missing_artifacts),
            "claim_ceiling": self.claim_ceiling,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class StoryAudit:
    """Complete typed Story audit before rendering."""

    spec: StorySpec
    generated_at: str
    story_path: str
    overall_status: OverallStatus
    warnings: tuple[str, ...]
    steps: tuple[StepAudit, ...]
