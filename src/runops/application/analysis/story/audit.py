"""Filesystem-free Story acceptance decisions."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from .models import (
    ArtifactEvidence,
    ArtifactRecord,
    OverallStatus,
    StepAudit,
    StepStatus,
    StoryStep,
)


def audit_step(
    step: StoryStep,
    artifacts: Sequence[ArtifactRecord],
    *,
    source_blocked: bool = False,
) -> StepAudit:
    """Evaluate one typed Story step against collected artifacts."""
    if source_blocked:
        return StepAudit(
            id=step.id,
            title=step.title,
            status="blocked",
            required_artifacts=step.required_artifacts,
            acceptable_status=step.acceptable_status,
            matched_artifacts=(),
            weak_artifacts=(),
            missing_artifacts=step.required_artifacts,
            claim_ceiling=step.claim_ceiling,
            notes=step.notes,
        )

    matched: list[ArtifactEvidence] = []
    weak: list[ArtifactEvidence] = []
    missing: list[str] = []
    acceptable = set(step.acceptable_status)
    for selector in step.required_artifacts:
        selector_matches = tuple(
            artifact for artifact in artifacts if artifact_matches(selector, artifact)
        )
        accepted = tuple(
            artifact
            for artifact in selector_matches
            if (artifact.status or "draft") in acceptable
        )
        if accepted:
            matched.extend(ArtifactEvidence(selector, item) for item in accepted)
        elif selector_matches:
            weak.extend(ArtifactEvidence(selector, item) for item in selector_matches)
        else:
            missing.append(selector)

    status: StepStatus
    if missing:
        status = "partial" if matched or weak else "missing"
    elif weak:
        status = "partial"
    else:
        status = "covered"
    return StepAudit(
        id=step.id,
        title=step.title,
        status=status,
        required_artifacts=step.required_artifacts,
        acceptable_status=step.acceptable_status,
        matched_artifacts=tuple(matched),
        weak_artifacts=tuple(weak),
        missing_artifacts=tuple(missing),
        claim_ceiling=step.claim_ceiling,
        notes=step.notes,
    )


def artifact_matches(selector: str, artifact: ArtifactRecord) -> bool:
    """Return whether an artifact satisfies one selector token."""
    kind, name = parse_selector(selector)
    if kind and normalize_token(kind) != normalize_token(artifact.kind):
        return False
    target = normalize_token(name)
    candidates = {
        normalize_token(artifact.name),
        normalize_token(artifact.artifact_id),
        normalize_token(artifact.title),
        normalize_token(artifact.quantity),
        normalize_token(Path(artifact.path).stem),
        *(normalize_token(tag) for tag in artifact.tags),
    }
    candidates.discard("")
    return target in candidates


def parse_selector(selector: str) -> tuple[str, str]:
    """Split an optional kind-qualified selector."""
    text = selector.strip()
    if ":" not in text:
        return "", text
    kind, name = text.split(":", 1)
    return kind.strip(), name.strip()


def normalize_token(value: str) -> str:
    """Normalize artifact metadata for selector comparison."""
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def overall_status(
    step_results: Sequence[StepAudit],
    warnings: Sequence[str],
) -> OverallStatus:
    """Combine step results and source warnings using legacy precedence."""
    if warnings and not step_results:
        return "blocked"
    statuses = {step.status for step in step_results}
    if statuses == {"covered"}:
        return "partial" if warnings else "covered"
    if statuses == {"missing"}:
        return "missing"
    if "blocked" in statuses:
        return "blocked"
    return "partial"
