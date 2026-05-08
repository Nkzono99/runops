"""Registry and execution helpers for project-state migrations."""

from __future__ import annotations

import re
from pathlib import Path

from runops.core.migrations.models import (
    Migration,
    MigrationContext,
    MigrationError,
    MigrationNotFoundError,
    MigrationResult,
)
from runops.core.migrations.v0 import registered_migrations as v0_migrations


def available_migrations(version: str | None = None) -> tuple[Migration, ...]:
    """Return registered migrations, optionally filtered by major version."""
    migrations = _all_migrations()
    if version is None:
        return migrations
    normalized_version = normalize_version(version)
    return tuple(item for item in migrations if item.version == normalized_version)


def get_migration(version: str, number: str) -> Migration:
    """Return a registered migration by version and number.

    Args:
        version: Major version, such as ``v0`` or ``0.7.0``.
        number: Migration number, such as ``1``, ``0001``, or ``M0-0001``.

    Raises:
        MigrationNotFoundError: If no matching migration is registered.
    """
    normalized_version = normalize_version(version)
    normalized_number = normalize_number(number, version=normalized_version)
    for migration in _all_migrations():
        if (
            migration.version == normalized_version
            and migration.number == normalized_number
        ):
            return migration
    raise MigrationNotFoundError(
        f"No migration registered for {normalized_version} {normalized_number}"
    )


def run_migration(
    version: str,
    number: str,
    *,
    project_root: Path,
    dry_run: bool = False,
    force: bool = False,
    yes: bool = False,
) -> MigrationResult:
    """Run one registered project-state migration."""
    migration = get_migration(version, number)
    if migration.human_gate and not dry_run and not yes:
        raise MigrationError(
            f"{migration.migration_id} requires a human gate. Re-run with --yes "
            "after reviewing docs/migrations/."
        )
    context = MigrationContext(
        project_root=project_root.resolve(),
        dry_run=dry_run,
        force=force,
    )
    return migration.apply(context)


def parse_migration_reference(
    reference: str, number: str | None = None
) -> tuple[str, str]:
    """Parse a migration reference into normalized ``(version, number)``.

    ``reference`` may be a canonical id like ``M0-0001``. When ``number`` is
    provided, ``reference`` is treated as the major version and ``number`` as
    the migration number.
    """
    if number is not None:
        version = normalize_version(reference)
        return version, normalize_number(number, version=version)

    raw = reference.strip().upper()
    migration_id = re.fullmatch(r"M(\d+)-(\d+)", raw)
    if migration_id is None:
        raise MigrationError(
            f"Invalid migration reference {reference!r}. Use M0-0001 or v0 0001."
        )
    major, digits = migration_id.groups()
    version = f"v{int(major)}"
    return version, normalize_number(digits, version=version)


def normalize_version(version: str) -> str:
    """Normalize a version argument into a major key like ``v0``."""
    raw = version.strip().lower()
    if not raw:
        raise MigrationError("Migration version must not be empty.")
    if raw.startswith("v"):
        raw = raw[1:]
    major = raw.split(".", 1)[0]
    if not major.isdigit():
        raise MigrationError(
            f"Invalid migration version {version!r}. Use v0, 0, or 0.x style."
        )
    return f"v{int(major)}"


def normalize_number(number: str, *, version: str) -> str:
    """Normalize a migration number into four digits."""
    raw = number.strip().upper()
    if not raw:
        raise MigrationError("Migration number must not be empty.")

    migration_id = re.fullmatch(r"M(\d+)-(\d+)", raw)
    if migration_id is not None:
        major, digits = migration_id.groups()
        if f"v{int(major)}" != version:
            raise MigrationError(
                f"Migration id {number!r} does not belong to {version}."
            )
        return f"{int(digits):04d}"

    if raw.isdigit():
        return f"{int(raw):04d}"

    raise MigrationError(
        f"Invalid migration number {number!r}. Use 1, 0001, or M0-0001 style."
    )


def _all_migrations() -> tuple[Migration, ...]:
    return (*v0_migrations(),)
