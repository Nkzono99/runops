"""Structured fact I/O for the local knowledge layer."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]

from runops.core.event_log import emit_artifact_event
from runops.core.models import knowledge as knowledge_records

from .paths import CANDIDATE_FACTS_DIR, FACTS_FILE, KNOWLEDGE_DIR, RUNOPS_DIR

Fact = knowledge_records.Fact

FACT_TYPES = frozenset(
    {
        "observation",
        "constraint",
        "dependency",
        "policy",
        "hypothesis",
    }
)

_FACT_ID_RE = re.compile(r"f(\d+)")


def _load_facts_document(path: Path) -> dict[str, Any]:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    if not isinstance(raw, dict):
        msg = f"Invalid facts document: {path}"
        raise RuntimeError(msg)
    return raw


def _coerce_fact_entry(
    data: dict[str, Any],
    *,
    storage: str,
    transport_source: str,
    transport_kind: str,
    transport_path: str,
) -> Fact:
    raw_id = str(data.get("id", "")).strip()
    fact_id = raw_id
    upstream_id = ""
    if storage != "local" and transport_source:
        fact_id = f"{transport_source}:{raw_id}" if raw_id else transport_source
        upstream_id = raw_id

    scope_case = data.get("scope_case", "")
    scope_text = data.get("scope_text", "")
    if not scope_case and not scope_text:
        legacy_scope = data.get("scope", "")
        if legacy_scope:
            scope_text = legacy_scope

    evidence_kind = data.get("evidence_kind", "")
    evidence_ref = data.get("evidence_ref", "")
    if not evidence_kind and not evidence_ref:
        legacy_evidence = data.get("evidence", "")
        if legacy_evidence:
            evidence_kind = legacy_evidence

    supersedes = str(data.get("supersedes", "")).strip()
    if supersedes and storage != "local" and transport_source:
        supersedes = f"{transport_source}:{supersedes}"

    return Fact(
        id=fact_id,
        claim=data.get("claim", ""),
        fact_type=data.get("fact_type", "observation"),
        simulator=data.get("simulator", ""),
        scope_case=scope_case,
        scope_text=scope_text,
        param_name=data.get("param_name", ""),
        confidence=data.get("confidence", "medium"),
        source_run=data.get("source_run", ""),
        source_project=data.get("source_project", ""),
        evidence_kind=evidence_kind,
        evidence_ref=evidence_ref,
        created_at=data.get("created_at", ""),
        tags=list(data.get("tags", [])),
        supersedes=supersedes,
        storage=storage,
        transport_source=transport_source,
        transport_kind=transport_kind,
        transport_path=transport_path,
        upstream_id=upstream_id,
    )


def load_facts_file(
    path: Path,
    *,
    storage: str = "local",
    transport_source: str = "",
    transport_kind: str = "",
    transport_path: str = "",
) -> list[Fact]:
    """Load facts from an arbitrary facts TOML document."""
    raw = _load_facts_document(path)
    transport = raw.get("transport", {})
    resolved_source = transport_source or str(transport.get("source", "")).strip()
    resolved_kind = transport_kind or str(transport.get("kind", "")).strip()
    resolved_path = transport_path or str(transport.get("source_path", "")).strip()

    facts: list[Fact] = []
    for data in raw.get("facts", []):
        if not isinstance(data, dict):
            continue
        facts.append(
            _coerce_fact_entry(
                data,
                storage=storage,
                transport_source=resolved_source,
                transport_kind=resolved_kind,
                transport_path=resolved_path,
            )
        )
    return facts


def load_facts(project_root: Path) -> list[Fact]:
    """Load structured facts from .runops/facts.toml."""
    facts_file = project_root / RUNOPS_DIR / FACTS_FILE
    if not facts_file.is_file():
        return []
    return load_facts_file(facts_file)


def load_candidate_facts(project_root: Path) -> list[Fact]:
    """Load imported candidate facts from .runops/knowledge/candidates/facts/."""
    facts_dir = project_root / RUNOPS_DIR / KNOWLEDGE_DIR / CANDIDATE_FACTS_DIR
    if not facts_dir.is_dir():
        return []

    facts: list[Fact] = []
    for facts_file in sorted(facts_dir.glob("*.toml")):
        facts.extend(load_facts_file(facts_file, storage="candidate"))
    return facts


def save_fact(project_root: Path, fact: Fact) -> None:
    """Append a structured fact to .runops/facts.toml."""
    if tomli_w is None:
        msg = "tomli_w is required to write facts.toml"
        raise RuntimeError(msg)

    runops_dir = project_root / RUNOPS_DIR
    runops_dir.mkdir(exist_ok=True)
    facts_file = runops_dir / FACTS_FILE
    existed_before = facts_file.exists()

    existing: list[dict[str, Any]] = []
    if facts_file.is_file():
        with open(facts_file, "rb") as f:
            raw = tomllib.load(f)
        existing = list(raw.get("facts", []))

    entry: dict[str, Any] = {
        "id": fact.id,
        "claim": fact.claim,
        "fact_type": fact.fact_type,
    }
    if fact.simulator:
        entry["simulator"] = fact.simulator
    if fact.scope_case:
        entry["scope_case"] = fact.scope_case
    if fact.scope_text:
        entry["scope_text"] = fact.scope_text
    if fact.param_name:
        entry["param_name"] = fact.param_name
    entry["confidence"] = fact.confidence
    if fact.source_run:
        entry["source_run"] = fact.source_run
    if fact.source_project:
        entry["source_project"] = fact.source_project
    if fact.evidence_kind:
        entry["evidence_kind"] = fact.evidence_kind
    if fact.evidence_ref:
        entry["evidence_ref"] = fact.evidence_ref
    entry["created_at"] = fact.created_at or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    if fact.tags:
        entry["tags"] = fact.tags
    if fact.supersedes:
        entry["supersedes"] = fact.supersedes

    existing.append(entry)

    with open(facts_file, "wb") as f:
        tomli_w.dump({"facts": existing}, f)
    emit_artifact_event(
        facts_file,
        operation="update" if existed_before else "create",
        artifact_kind="facts",
        summary="Update .runops/facts.toml",
    )


def next_fact_id(project_root: Path) -> str:
    """Return the next sequential fact ID."""
    max_num = 0
    for fact in load_facts(project_root):
        match = _FACT_ID_RE.fullmatch(fact.id)
        if match is None:
            continue
        max_num = max(max_num, int(match.group(1)))
    return f"f{max_num + 1:03d}"


def promote_candidate_fact(project_root: Path, fact_id: str) -> Fact:
    """Copy one imported candidate fact into the local curated facts store."""
    source_fact = next(
        (fact for fact in load_candidate_facts(project_root) if fact.id == fact_id),
        None,
    )
    if source_fact is None:
        msg = f"Candidate fact not found: {fact_id}"
        raise LookupError(msg)

    promoted = Fact(
        id=next_fact_id(project_root),
        claim=source_fact.claim,
        fact_type=source_fact.fact_type,
        simulator=source_fact.simulator,
        scope_case=source_fact.scope_case,
        scope_text=source_fact.scope_text,
        param_name=source_fact.param_name,
        confidence=source_fact.confidence,
        source_run=source_fact.source_run,
        source_project=source_fact.source_project or source_fact.transport_source,
        evidence_kind=source_fact.evidence_kind
        or ("shared_fact" if source_fact.transport_source else ""),
        evidence_ref=source_fact.evidence_ref
        or (
            f"fact:{source_fact.transport_source}:{source_fact.upstream_id}"
            if source_fact.transport_source and source_fact.upstream_id
            else ""
        ),
        created_at=source_fact.created_at,
        tags=list(source_fact.tags),
    )
    save_fact(project_root, promoted)
    return promoted


def query_facts(
    project_root: Path,
    *,
    scope: str = "",
    tag: str = "",
    min_confidence: str = "",
    simulator: str = "",
    fact_type: str = "",
    param_name: str = "",
    exclude_superseded: bool = True,
    include_candidates: bool = False,
) -> list[Fact]:
    """Query facts with optional filters."""
    confidence_order = {"high": 3, "medium": 2, "low": 1}
    min_level = confidence_order.get(min_confidence, 0)

    facts = list(load_facts(project_root))
    if include_candidates:
        facts.extend(load_candidate_facts(project_root))

    superseded_ids: set[str] = set()
    if exclude_superseded:
        for fact in facts:
            if fact.supersedes:
                superseded_ids.add(fact.supersedes)

    results: list[Fact] = []
    for fact in facts:
        if exclude_superseded and fact.id in superseded_ids:
            continue
        if scope and scope not in fact.scope:
            continue
        if tag and tag not in fact.tags:
            continue
        if min_level and confidence_order.get(fact.confidence, 0) < min_level:
            continue
        if simulator and fact.simulator != simulator:
            continue
        if fact_type and fact.fact_type != fact_type:
            continue
        if param_name and fact.param_name != param_name:
            continue
        results.append(fact)
    return results
