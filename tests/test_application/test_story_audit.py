"""Tests for pure typed Story audit decisions."""

from __future__ import annotations

import pytest

from runops.application.analysis.story.audit import audit_step, overall_status
from runops.application.analysis.story.models import (
    ArtifactRecord,
    StepAudit,
    StoryStep,
)


def _step(*selectors: str) -> StoryStep:
    return StoryStep(
        id="surface",
        title="Surface",
        required_artifacts=selectors,
        acceptable_status=("main", "accepted"),
    )


def _artifact(**changes: object) -> ArtifactRecord:
    values: dict[str, object] = {
        "kind": "figure",
        "path": "figures/surface.png",
        "title": "Surface Potential",
        "status": "main",
        "quantity": "surface_potential",
        "present_fields": frozenset(
            {"kind", "path", "title", "status", "quantity"}
        ),
    }
    values.update(changes)
    return ArtifactRecord(**values)  # type: ignore[arg-type]


def test_audit_step_classifies_covered_weak_and_missing_evidence() -> None:
    result = audit_step(
        _step("figure:surface_potential", "figure:force", "data:density"),
        (
            _artifact(),
            _artifact(
                path="figures/force.png",
                title="Force",
                quantity="force",
                status="draft",
            ),
        ),
    )

    assert result.status == "partial"
    assert tuple(item.selector for item in result.matched_artifacts) == (
        "figure:surface_potential",
    )
    assert tuple(item.selector for item in result.weak_artifacts) == (
        "figure:force",
    )
    assert result.missing_artifacts == ("data:density",)


def test_audit_step_blocks_every_requirement_when_source_is_missing() -> None:
    result = audit_step(
        _step("figure:surface", "data:density"),
        (_artifact(),),
        source_blocked=True,
    )

    assert result.status == "blocked"
    assert result.matched_artifacts == ()
    assert result.missing_artifacts == ("figure:surface", "data:density")


@pytest.mark.parametrize(
    ("changes", "selector"),
    [
        ({"name": "surface"}, "surface"),
        ({"artifact_id": "surface"}, "surface"),
        ({"title": "Surface Map"}, "surface_map"),
        ({"quantity": "surface_density"}, "surface_density"),
        ({"path": "figures/surface-force.png"}, "surface_force"),
        ({"tags": ("surface-tag",)}, "surface_tag"),
    ],
)
def test_audit_step_matches_all_supported_artifact_candidates(
    changes: dict[str, object],
    selector: str,
) -> None:
    result = audit_step(_step(selector), (_artifact(**changes),))

    assert result.status == "covered"


def test_audit_step_respects_kind_qualified_selectors() -> None:
    result = audit_step(_step("data:surface_potential"), (_artifact(),))

    assert result.status == "missing"


def _audited(status: str) -> StepAudit:
    return StepAudit(
        id=status,
        title=status,
        status=status,  # type: ignore[arg-type]
        required_artifacts=("figure:x",),
        acceptable_status=("main",),
        matched_artifacts=(),
        weak_artifacts=(),
        missing_artifacts=(),
    )


@pytest.mark.parametrize(
    ("statuses", "warnings", "expected"),
    [
        (("covered",), (), "covered"),
        (("covered",), ("warning",), "partial"),
        (("missing",), (), "missing"),
        (("blocked", "covered"), (), "blocked"),
        (("covered", "missing"), (), "partial"),
        ((), ("warning",), "blocked"),
    ],
)
def test_overall_status_preserves_precedence(
    statuses: tuple[str, ...],
    warnings: tuple[str, ...],
    expected: str,
) -> None:
    assert overall_status(tuple(_audited(status) for status in statuses), warnings) == (
        expected
    )
