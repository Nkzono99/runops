"""Local insight and fact records for the knowledge layer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Insight:
    """A single knowledge insight.

    Attributes:
        name: Filename stem (e.g. ``"emses_cfl_limit"``).
        type: Insight category.
        simulator: Simulator name this insight applies to.
        tags: Searchable tags.
        source_project: Project where this insight originated.
        created: ISO-format creation timestamp.
        content: Markdown body of the insight.
    """

    name: str
    type: str
    simulator: str
    tags: list[str] = field(default_factory=list)
    source_project: str = ""
    created: str = ""
    content: str = ""


@dataclass
class Fact:
    """A structured, machine-readable knowledge claim."""

    id: str
    claim: str
    fact_type: str = "observation"
    simulator: str = ""
    scope_case: str = ""
    scope_text: str = ""
    param_name: str = ""
    confidence: str = "medium"
    source_run: str = ""
    source_project: str = ""
    evidence_kind: str = ""
    evidence_ref: str = ""
    created_at: str = ""
    tags: list[str] = field(default_factory=list)
    supersedes: str = ""
    storage: str = "local"
    transport_source: str = ""
    transport_kind: str = ""
    transport_path: str = ""
    upstream_id: str = ""

    @property
    def scope(self) -> str:
        """Backward-compatible scope string."""
        parts = []
        if self.simulator:
            parts.append(self.simulator)
        if self.scope_case:
            parts.append(self.scope_case)
        if self.scope_text:
            parts.append(self.scope_text)
        return ", ".join(parts) if parts else ""

    @property
    def evidence(self) -> str:
        """Backward-compatible evidence string."""
        parts = []
        if self.evidence_kind:
            parts.append(self.evidence_kind)
        if self.evidence_ref:
            parts.append(self.evidence_ref)
        return ": ".join(parts) if parts else ""
