"""Knowledge layer: local insights and structured facts."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

_SIMCTL_DIR = ".runops"
_INSIGHTS_DIR = "insights"
_KNOWLEDGE_DIR = "knowledge"
_CANDIDATE_FACTS_DIR = "candidates/facts"

# Valid insight types
INSIGHT_TYPES = frozenset(
    {
        "constraint",  # Stability/constraint findings
        "result",  # Experiment result summaries
        "analysis",  # Physical interpretation / discussion
        "dependency",  # Parameter dependency trends
    }
)

# Valid fact types
FACT_TYPES = frozenset(
    {
        "observation",  # Directly observed from run output
        "constraint",  # Stability / CFL / resolution constraint
        "dependency",  # Parameter dependency relationship
        "policy",  # Operational rule (e.g. "always use dt < X")
        "hypothesis",  # Unverified conjecture
    }
)

Insight = knowledge_records.Insight
Fact = knowledge_records.Fact


def get_runops_dir(project_root: Path) -> Path:
    """Return the .runops directory for a project, creating if needed."""
    d = project_root / _SIMCTL_DIR
    d.mkdir(exist_ok=True)
    return d


def get_insights_dir(project_root: Path) -> Path:
    """Return the .runops/insights directory, creating if needed."""
    d = get_runops_dir(project_root) / _INSIGHTS_DIR
    d.mkdir(exist_ok=True)
    return d


def get_knowledge_dir(project_root: Path) -> Path:
    """Return the .runops/knowledge directory, creating if needed."""
    d = get_runops_dir(project_root) / _KNOWLEDGE_DIR
    d.mkdir(exist_ok=True)
    return d


def get_candidate_facts_dir(project_root: Path) -> Path:
    """Return the candidate fact transport directory, creating if needed."""
    d = get_knowledge_dir(project_root) / _CANDIDATE_FACTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- Insight I/O ----------


def parse_insight(path: Path) -> Insight | None:
    """Parse an insight markdown file with YAML-like frontmatter.

    The frontmatter is delimited by ``---`` lines and contains
    key-value pairs.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    # Find closing ---
    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx < 0:
        return None

    # Parse frontmatter
    meta: dict[str, Any] = {}
    for line in lines[1:end_idx]:
        if ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        stripped = raw_value.strip()
        # Handle list values: [a, b, c]
        if stripped.startswith("[") and stripped.endswith("]"):
            meta[key] = [
                v.strip().strip("\"'") for v in stripped[1:-1].split(",") if v.strip()
            ]
        else:
            meta[key] = stripped

    content = "\n".join(lines[end_idx + 1 :]).strip()

    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    return Insight(
        name=path.stem,
        type=meta.get("type", "result"),
        simulator=meta.get("simulator", ""),
        tags=tags,
        source_project=meta.get("source_project", ""),
        created=meta.get("created", ""),
        content=content,
    )


def write_insight(insights_dir: Path, insight: Insight) -> Path:
    """Write an insight to a markdown file.

    Returns:
        Path to the written file.
    """
    tags_str = ", ".join(insight.tags) if insight.tags else ""
    created = insight.created or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    frontmatter = [
        "---",
        f"type: {insight.type}",
        f"simulator: {insight.simulator}",
    ]
    if tags_str:
        frontmatter.append(f"tags: [{tags_str}]")
    if insight.source_project:
        frontmatter.append(f"source_project: {insight.source_project}")
    frontmatter.append(f"created: {created}")
    frontmatter.append("---")

    text = "\n".join(frontmatter) + "\n\n" + insight.content + "\n"
    filepath = insights_dir / f"{insight.name}.md"
    existed_before = filepath.exists()
    filepath.write_text(text, encoding="utf-8")
    emit_artifact_event(
        filepath,
        operation="update" if existed_before else "create",
        artifact_kind="insight",
        summary=f"{'Update' if existed_before else 'Create'} insight {filepath.name}",
    )
    return filepath


def list_insights(
    project_root: Path,
    *,
    simulator: str = "",
    insight_type: str = "",
    tag: str = "",
) -> list[Insight]:
    """List insights, optionally filtered."""
    insights_dir = project_root / _SIMCTL_DIR / _INSIGHTS_DIR
    if not insights_dir.is_dir():
        return []

    results: list[Insight] = []
    for md_file in sorted(insights_dir.glob("*.md")):
        insight = parse_insight(md_file)
        if insight is None:
            continue
        if simulator and insight.simulator != simulator:
            continue
        if insight_type and insight.type != insight_type:
            continue
        if tag and tag not in insight.tags:
            continue
        results.append(insight)
    return results


# ---------- Structured Facts ----------

_FACTS_FILE = "facts.toml"
_FACT_ID_RE = re.compile(r"f(\d+)")


def _load_facts_document(path: Path) -> dict[str, Any]:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    if not isinstance(raw, dict):
        msg = f"Invalid facts document: {path}"
        raise RuntimeError(msg)
    return raw


def _coerce_fact_entry(
    d: dict[str, Any],
    *,
    storage: str,
    transport_source: str,
    transport_kind: str,
    transport_path: str,
) -> Fact:
    raw_id = str(d.get("id", "")).strip()
    fact_id = raw_id
    upstream_id = ""
    if storage != "local" and transport_source:
        fact_id = f"{transport_source}:{raw_id}" if raw_id else transport_source
        upstream_id = raw_id

    # Migrate legacy "scope" string -> scope_text
    scope_case = d.get("scope_case", "")
    scope_text = d.get("scope_text", "")
    if not scope_case and not scope_text:
        legacy_scope = d.get("scope", "")
        if legacy_scope:
            scope_text = legacy_scope

    # Migrate legacy "evidence" string -> evidence_kind
    evidence_kind = d.get("evidence_kind", "")
    evidence_ref = d.get("evidence_ref", "")
    if not evidence_kind and not evidence_ref:
        legacy_evidence = d.get("evidence", "")
        if legacy_evidence:
            evidence_kind = legacy_evidence

    supersedes = str(d.get("supersedes", "")).strip()
    if supersedes and storage != "local" and transport_source:
        supersedes = f"{transport_source}:{supersedes}"

    return Fact(
        id=fact_id,
        claim=d.get("claim", ""),
        fact_type=d.get("fact_type", "observation"),
        simulator=d.get("simulator", ""),
        scope_case=scope_case,
        scope_text=scope_text,
        param_name=d.get("param_name", ""),
        confidence=d.get("confidence", "medium"),
        source_run=d.get("source_run", ""),
        source_project=d.get("source_project", ""),
        evidence_kind=evidence_kind,
        evidence_ref=evidence_ref,
        created_at=d.get("created_at", ""),
        tags=list(d.get("tags", [])),
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
    """Load facts from an arbitrary facts TOML document.

    Handles both the new structured schema (with ``fact_type``,
    ``simulator``, ``scope_case``, etc.) and the legacy flat schema
    (with ``scope`` and ``evidence`` as plain strings).
    """
    raw = _load_facts_document(path)
    transport = raw.get("transport", {})
    resolved_source = transport_source or str(transport.get("source", "")).strip()
    resolved_kind = transport_kind or str(transport.get("kind", "")).strip()
    resolved_path = transport_path or str(transport.get("source_path", "")).strip()

    facts: list[Fact] = []
    for d in raw.get("facts", []):
        if not isinstance(d, dict):
            continue
        facts.append(
            _coerce_fact_entry(
                d,
                storage=storage,
                transport_source=resolved_source,
                transport_kind=resolved_kind,
                transport_path=resolved_path,
            )
        )
    return facts


def load_facts(project_root: Path) -> list[Fact]:
    """Load structured facts from .runops/facts.toml."""
    facts_file = project_root / _SIMCTL_DIR / _FACTS_FILE
    if not facts_file.is_file():
        return []
    return load_facts_file(facts_file)


def load_candidate_facts(project_root: Path) -> list[Fact]:
    """Load imported candidate facts from .runops/knowledge/candidates/facts/."""
    facts_dir = project_root / _SIMCTL_DIR / _KNOWLEDGE_DIR / _CANDIDATE_FACTS_DIR
    if not facts_dir.is_dir():
        return []

    facts: list[Fact] = []
    for facts_file in sorted(facts_dir.glob("*.toml")):
        facts.extend(load_facts_file(facts_file, storage="candidate"))
    return facts


def save_fact(project_root: Path, fact: Fact) -> None:
    """Append a structured fact to .runops/facts.toml.

    Uses the new structured schema.  Facts are append-only by convention;
    to supersede an existing fact, create a new one with ``supersedes``
    set to the old fact's ID.
    """
    if tomli_w is None:
        msg = "tomli_w is required to write facts.toml"
        raise RuntimeError(msg)

    runops_dir = project_root / _SIMCTL_DIR
    runops_dir.mkdir(exist_ok=True)
    facts_file = runops_dir / _FACTS_FILE
    existed_before = facts_file.exists()

    # Load existing
    existing: list[dict[str, Any]] = []
    if facts_file.is_file():
        with open(facts_file, "rb") as f:
            raw = tomllib.load(f)
        existing = list(raw.get("facts", []))

    # Build new entry (structured schema)
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
    """Return the next sequential fact ID.

    Fact IDs follow the ``fNNN`` convention used throughout the docs.
    Non-matching IDs are ignored when computing the next value.
    """
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
    """Query facts with optional filters.

    Args:
        project_root: Project root directory.
        scope: Free-text scope substring match (searches scope property).
        tag: Must appear in tags list.
        min_confidence: Minimum confidence level.
        simulator: Must match simulator field exactly.
        fact_type: Must match fact_type field exactly.
        param_name: Must match param_name field exactly.
        exclude_superseded: If True, exclude facts that have been
            superseded by newer facts.
        include_candidates: If True, include imported candidate facts
            from external knowledge transport in addition to local facts.
    """
    confidence_order = {"high": 3, "medium": 2, "low": 1}
    min_level = confidence_order.get(min_confidence, 0)

    facts = list(load_facts(project_root))
    if include_candidates:
        facts.extend(load_candidate_facts(project_root))

    # Build set of superseded IDs
    superseded_ids: set[str] = set()
    if exclude_superseded:
        for f in facts:
            if f.supersedes:
                superseded_ids.add(f.supersedes)

    results: list[Fact] = []
    for f in facts:
        if exclude_superseded and f.id in superseded_ids:
            continue
        if scope and scope not in f.scope:
            continue
        if tag and tag not in f.tags:
            continue
        if min_level and confidence_order.get(f.confidence, 0) < min_level:
            continue
        if simulator and f.simulator != simulator:
            continue
        if fact_type and f.fact_type != fact_type:
            continue
        if param_name and f.param_name != param_name:
            continue
        results.append(f)
    return results
