"""Tests for pure Story audit rendering."""

from __future__ import annotations

from runops.application.analysis.story.models import (
    ArtifactEvidence,
    ArtifactRecord,
    StepAudit,
    StoryAudit,
    StorySource,
    StorySpec,
)
from runops.application.analysis.story.render import (
    audit_payload,
    render_audit_markdown,
)


def _audit() -> StoryAudit:
    artifact = ArtifactRecord(
        kind="figure",
        path="runs/scan/analysis/figures/surface.png",
        status="main",
        present_fields=frozenset({"kind", "path", "status"}),
    )
    step = StepAudit(
        id="surface",
        title="Surface field",
        status="partial",
        required_artifacts=("figure:surface", "data:density"),
        acceptable_status=("main",),
        matched_artifacts=(ArtifactEvidence("figure:surface", artifact),),
        weak_artifacts=(),
        missing_artifacts=("data:density",),
        claim_ceiling="static evidence",
    )
    return StoryAudit(
        spec=StorySpec(
            schema_version=1,
            id="surface-story",
            title="Surface story",
            status="draft",
            sources=(StorySource(kind="survey", path="runs/scan"),),
            steps=(),
        ),
        generated_at="2026-07-11T12:34:56+00:00",
        story_path="analysis/stories/surface-story/story.toml",
        overall_status="partial",
        warnings=("No artifact index found for source: runs/extra",),
        steps=(step,),
    )


def test_audit_payload_matches_legacy_shape() -> None:
    assert audit_payload(_audit()) == {
        "schema_version": 1,
        "generated_at": "2026-07-11T12:34:56+00:00",
        "story": {
            "id": "surface-story",
            "title": "Surface story",
            "status": "draft",
            "path": "analysis/stories/surface-story/story.toml",
        },
        "sources": [{"kind": "survey", "path": "runs/scan"}],
        "overall_status": "partial",
        "warnings": ["No artifact index found for source: runs/extra"],
        "steps": [
            {
                "id": "surface",
                "title": "Surface field",
                "status": "partial",
                "required_artifacts": ["figure:surface", "data:density"],
                "acceptable_status": ["main"],
                "matched_artifacts": [
                    {
                        "kind": "figure",
                        "path": "runs/scan/analysis/figures/surface.png",
                        "status": "main",
                        "selector": "figure:surface",
                    }
                ],
                "weak_artifacts": [],
                "missing_artifacts": ["data:density"],
                "claim_ceiling": "static evidence",
                "notes": "",
            }
        ],
    }


def test_render_audit_markdown_matches_legacy_text() -> None:
    assert render_audit_markdown(_audit()) == (
        "# Story Acceptance Audit: Surface story\n"
        "\n"
        "- Overall status: `partial`\n"
        "- Generated at: `2026-07-11T12:34:56+00:00`\n"
        "\n"
        "## Warnings\n"
        "- No artifact index found for source: runs/extra\n"
        "\n"
        "## Steps\n"
        "\n"
        "### Surface field\n"
        "\n"
        "- Step id: `surface`\n"
        "- Status: `partial`\n"
        "- Claim ceiling: static evidence\n"
        "- Covered evidence:\n"
        "  - `figure:surface` -> "
        "`runs/scan/analysis/figures/surface.png` (main)\n"
        "- Missing evidence:\n"
        "  - `data:density`\n"
    )
