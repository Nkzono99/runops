"""Pure JSON payload and Markdown rendering for Story audits."""

from __future__ import annotations

from .models import StoryAudit


def audit_payload(audit: StoryAudit) -> dict[str, object]:
    """Return the legacy JSON-serializable audit payload."""
    return {
        "schema_version": 1,
        "generated_at": audit.generated_at,
        "story": {
            "id": audit.spec.id,
            "title": audit.spec.title,
            "status": audit.spec.status,
            "path": audit.story_path,
        },
        "sources": [
            {"kind": source.kind, "path": source.path} for source in audit.spec.sources
        ],
        "overall_status": audit.overall_status,
        "warnings": list(audit.warnings),
        "steps": [step.to_dict() for step in audit.steps],
    }


def render_audit_markdown(audit: StoryAudit) -> str:
    """Render the legacy human-readable Story audit report."""
    lines = [
        f"# Story Acceptance Audit: {audit.spec.title}",
        "",
        f"- Overall status: `{audit.overall_status}`",
        f"- Generated at: `{audit.generated_at}`",
    ]
    if audit.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in audit.warnings)

    lines.extend(["", "## Steps"])
    for step in audit.steps:
        lines.extend(
            [
                "",
                f"### {step.title}",
                "",
                f"- Step id: `{step.id}`",
                f"- Status: `{step.status}`",
            ]
        )
        if step.claim_ceiling:
            lines.append(f"- Claim ceiling: {step.claim_ceiling}")
        if step.matched_artifacts:
            lines.append("- Covered evidence:")
            lines.extend(
                _evidence_line(item.to_dict()) for item in step.matched_artifacts
            )
        if step.weak_artifacts:
            lines.append("- Weak evidence:")
            lines.extend(_evidence_line(item.to_dict()) for item in step.weak_artifacts)
        if step.missing_artifacts:
            lines.append("- Missing evidence:")
            lines.extend(f"  - `{selector}`" for selector in step.missing_artifacts)
    return "\n".join(lines) + "\n"


def _evidence_line(evidence: dict[str, object]) -> str:
    return (
        "  - "
        f"`{evidence.get('selector', '')}` -> "
        f"`{evidence.get('path', '')}` "
        f"({evidence.get('status', 'draft')})"
    )
