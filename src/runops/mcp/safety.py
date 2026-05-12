"""Safety metadata for the runops MCP provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SafetyClass = Literal["read", "inspect", "plan", "write", "external", "destructive"]


@dataclass(frozen=True)
class SafetyMetadata:
    """Tool safety metadata advertised through MCP capabilities."""

    level: int
    safety_class: SafetyClass
    side_effects: bool = False
    requires_confirmation: bool = False
    requires_clean_git: bool = False
    writes_files: bool = False
    external_effects: bool = False
    destructive: bool = False
    confirmation_field: str = ""
    confirmation_value: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return JSON-serializable safety metadata."""
        data: dict[str, object] = {
            "safety_level": self.level,
            "safety_class": self.safety_class,
            "side_effects": self.side_effects,
            "requires_confirmation": self.requires_confirmation,
            "requires_clean_git": self.requires_clean_git,
            "writes_files": self.writes_files,
            "external_effects": self.external_effects,
            "destructive": self.destructive,
        }
        if self.confirmation_field:
            data["confirmation_field"] = self.confirmation_field
            data["confirmation_value"] = self.confirmation_value
        return data


READ = SafetyMetadata(level=0, safety_class="read")
INSPECT = SafetyMetadata(level=1, safety_class="inspect")
PLAN = SafetyMetadata(level=2, safety_class="plan")
EXTERNAL_DISABLED = SafetyMetadata(
    level=4,
    safety_class="external",
    side_effects=True,
    requires_confirmation=True,
    requires_clean_git=True,
    external_effects=True,
    confirmation_field="confirm",
    confirmation_value=True,
)
DESTRUCTIVE_DISABLED = SafetyMetadata(
    level=5,
    safety_class="destructive",
    side_effects=True,
    requires_confirmation=True,
    destructive=True,
    confirmation_field="confirm",
    confirmation_value=True,
)
