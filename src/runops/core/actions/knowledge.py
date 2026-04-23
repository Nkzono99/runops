"""Knowledge-store action implementations."""

from __future__ import annotations

from pathlib import Path

from runops.core.actions.helpers import _error, _precondition_fail
from runops.core.actions.result import ActionResult, ActionStatus


def save_insight(
    project_root: Path,
    *,
    name: str,
    content: str,
    insight_type: str = "result",
    simulator: str = "",
    tags: list[str] | None = None,
    source_project: str = "",
) -> ActionResult:
    """Record a markdown knowledge insight."""
    from runops.core.knowledge import (
        INSIGHT_TYPES,
        Insight,
        get_insights_dir,
        write_insight,
    )

    if insight_type not in INSIGHT_TYPES:
        return _error(
            "save_insight",
            "Invalid insight type "
            f"{insight_type!r}. Must be one of: {', '.join(sorted(INSIGHT_TYPES))}",
        )

    insight = Insight(
        name=name,
        type=insight_type,
        simulator=simulator,
        tags=tags or [],
        source_project=source_project or project_root.name,
        content=content.strip(),
    )

    try:
        path = write_insight(get_insights_dir(project_root), insight)
    except OSError as e:
        return _error("save_insight", str(e))

    return ActionResult(
        action="save_insight",
        status=ActionStatus.SUCCESS,
        message=f"Saved insight {name}",
        data={
            "name": name,
            "path": str(path),
            "insight_type": insight_type,
            "simulator": simulator,
            "tags": list(tags or []),
        },
    )


def add_fact(
    project_root: Path,
    *,
    claim: str,
    fact_type: str = "observation",
    simulator: str = "",
    scope_case: str = "",
    scope_text: str = "",
    param_name: str = "",
    confidence: str = "medium",
    source_run: str = "",
    evidence_kind: str = "",
    evidence_ref: str = "",
    tags: list[str] | None = None,
    supersedes: str = "",
) -> ActionResult:
    """Record a structured knowledge fact.

    This delegates to the knowledge module's save_fact function.
    """
    from runops.core.knowledge import Fact, next_fact_id, save_fact

    fact_id = next_fact_id(project_root)

    fact = Fact(
        id=fact_id,
        claim=claim,
        fact_type=fact_type,
        simulator=simulator,
        scope_case=scope_case,
        scope_text=scope_text,
        param_name=param_name,
        confidence=confidence,
        source_run=source_run,
        source_project=project_root.name,
        evidence_kind=evidence_kind,
        evidence_ref=evidence_ref,
        tags=tags or [],
        supersedes=supersedes,
    )
    try:
        save_fact(project_root, fact)
    except (RuntimeError, OSError) as e:
        return _error("add_fact", str(e))

    return ActionResult(
        action="add_fact",
        status=ActionStatus.SUCCESS,
        message=f"Saved fact {fact_id}: {claim}",
        data={"fact_id": fact_id},
    )


def promote_fact(project_root: Path, fact_id: str) -> ActionResult:
    """Promote an imported candidate fact into local curated facts."""
    from runops.core.knowledge import promote_candidate_fact

    try:
        promoted = promote_candidate_fact(project_root, fact_id)
    except LookupError as exc:
        return _precondition_fail("promote_fact", str(exc))
    except RuntimeError as exc:
        return _error("promote_fact", str(exc))

    return ActionResult(
        action="promote_fact",
        status=ActionStatus.SUCCESS,
        message=f"Promoted fact {fact_id} -> {promoted.id}",
        data={
            "fact_id": promoted.id,
            "source_fact_id": fact_id,
            "confidence": promoted.confidence,
            "fact_type": promoted.fact_type,
        },
    )
