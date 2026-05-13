"""Versioned runops project upgrade planning."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version


class UpgradePlanError(ValueError):
    """Raised when an upgrade chain cannot be planned safely."""


@dataclass(frozen=True)
class UpgradeStep:
    """One exact-version update-harness invocation in an upgrade chain."""

    from_version: str
    to_version: str


@dataclass(frozen=True)
class UpgradePlan:
    """A planned project upgrade chain."""

    applied_version: str
    current_runtime_version: str
    target_version: str
    steps: tuple[UpgradeStep, ...]


def build_upgrade_plan(
    *,
    applied_version: str | None,
    current_runtime_version: str,
    target_version: str | None = None,
    available_versions: Iterable[str] = (),
    allow_major: bool = False,
) -> UpgradePlan:
    """Build a checkpoint-based upgrade plan.

    The plan advances by release line (major.minor) instead of every patch.
    Each intermediate line uses the latest known version in that line, while
    the final step targets ``target_version`` exactly.
    """
    current = _parse_version(current_runtime_version, "current_runtime_version")
    target = _parse_version(target_version or current_runtime_version, "target_version")
    applied_text = applied_version or current_runtime_version
    applied = _parse_version(applied_text, "applied_version")

    if target.major != applied.major and not allow_major:
        msg = (
            f"Major upgrade requires --allow-major: "
            f"{applied_text} -> {target_version or current_runtime_version}"
        )
        raise UpgradePlanError(msg)

    if target <= applied:
        return UpgradePlan(
            applied_version=applied_text,
            current_runtime_version=current_runtime_version,
            target_version=str(target),
            steps=(),
        )

    releases = _candidate_release_versions(
        available_versions=available_versions,
        applied=applied,
        target=target,
    )
    release_lines = sorted(
        {(version.major, version.minor) for version in releases}
        | {(target.major, target.minor)}
    )

    cursor = applied
    steps: list[UpgradeStep] = []
    for major, minor in release_lines:
        if (major, minor) < (applied.major, applied.minor):
            continue
        if (major, minor) > (target.major, target.minor):
            continue

        if (major, minor) == (target.major, target.minor):
            checkpoint = target
        else:
            line_versions = [
                version
                for version in releases
                if (version.major, version.minor) == (major, minor)
                and cursor < version <= target
            ]
            if not line_versions:
                continue
            checkpoint = max(line_versions)

        if checkpoint > cursor:
            steps.append(
                UpgradeStep(
                    from_version=str(cursor),
                    to_version=str(checkpoint),
                )
            )
            cursor = checkpoint

    if cursor < target:
        steps.append(
            UpgradeStep(
                from_version=str(cursor),
                to_version=str(target),
            )
        )

    return UpgradePlan(
        applied_version=applied_text,
        current_runtime_version=str(current),
        target_version=str(target),
        steps=tuple(steps),
    )


def latest_version_in_versions(versions: Iterable[str]) -> str | None:
    """Return the latest stable PEP 440 version from ``versions``."""
    parsed = _stable_versions(versions)
    if not parsed:
        return None
    return str(max(parsed))


def _candidate_release_versions(
    *,
    available_versions: Iterable[str],
    applied: Version,
    target: Version,
) -> list[Version]:
    versions = [
        version
        for version in _stable_versions(available_versions)
        if applied < version <= target
    ]
    if target not in versions:
        versions.append(target)
    return sorted(set(versions))


def _stable_versions(versions: Iterable[str]) -> list[Version]:
    parsed: list[Version] = []
    for raw in versions:
        try:
            version = _parse_version(raw, "available_version")
        except UpgradePlanError:
            continue
        if version.is_prerelease or version.is_devrelease:
            continue
        parsed.append(version)
    return parsed


def _parse_version(value: str, label: str) -> Version:
    normalized = value.strip()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    try:
        return Version(normalized)
    except InvalidVersion as exc:
        raise UpgradePlanError(f"Invalid {label}: {value}") from exc
