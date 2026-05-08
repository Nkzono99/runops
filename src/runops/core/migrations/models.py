"""Models for project-state migrations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from runops.core.exceptions import SimctlError


class MigrationError(SimctlError):
    """Base error for project-state migration failures."""


class MigrationNotFoundError(MigrationError):
    """Raised when a requested migration is not registered."""


@dataclass(frozen=True)
class MigrationContext:
    """Runtime context passed to migration implementations.

    Attributes:
        project_root: Root directory of the target runops project.
        dry_run: If true, report planned changes without writing files.
        force: If true, allow idempotent regeneration of existing generated files.
    """

    project_root: Path
    dry_run: bool = False
    force: bool = False


@dataclass(frozen=True)
class MigrationResult:
    """Result from a project-state migration."""

    migration_id: str
    title: str
    status: str
    summary: str
    created: tuple[Path, ...] = ()
    updated: tuple[Path, ...] = ()
    deleted: tuple[Path, ...] = ()
    planned: tuple[Path, ...] = ()
    skipped: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        """Return whether the migration wrote project files."""
        return bool(self.created or self.updated or self.deleted)


MigrationHandler = Callable[[MigrationContext], MigrationResult]


@dataclass(frozen=True)
class Migration:
    """Registered migration metadata and handler."""

    version: str
    number: str
    title: str
    description: str
    migration_type: str
    impact: tuple[str, ...]
    human_gate: bool
    handler: MigrationHandler = field(repr=False)

    @property
    def migration_id(self) -> str:
        """Return canonical migration id, such as ``M0-0001``."""
        return f"M{self.version.removeprefix('v')}-{self.number}"

    def apply(self, context: MigrationContext) -> MigrationResult:
        """Apply this migration with the given context."""
        return self.handler(context)
