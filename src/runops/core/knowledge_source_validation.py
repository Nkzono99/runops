"""Validation helpers for external knowledge sources."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.core.exceptions import KnowledgeSourceError
from runops.core.knowledge_source import (
    _ENTRYPOINTS_FILE,
    _parse_import_directives,
    _profile_markdown_path,
    _resolve_import_target,
    load_entrypoints,
)


def _validate_import_paths(
    source_path: Path,
    import_paths: list[str],
    *,
    context: str,
) -> list[str]:
    issues: list[str] = []
    for rel_path in import_paths:
        try:
            target = _resolve_import_target(source_path, rel_path)
        except KnowledgeSourceError as exc:
            issues.append(f"{context}: {exc}")
            continue
        if not target.exists():
            issues.append(f"{context}: missing import target: {rel_path}")
        elif not target.is_file():
            issues.append(f"{context}: import target is not a file: {rel_path}")
    return issues


def _validate_analysis_file(
    path: Path,
    *,
    source_path: Path,
    kind: str,
) -> list[str]:
    issues: list[str] = []
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        issues.append(
            f"{kind} schema parse failed: "
            f"{path.relative_to(source_path).as_posix()} ({exc})"
        )
        return issues
    except OSError as exc:
        issues.append(
            f"{kind} schema not readable: "
            f"{path.relative_to(source_path).as_posix()} ({exc})"
        )
        return issues

    rel = path.relative_to(source_path).as_posix()
    if kind == "observables":
        observable = raw.get("observable")
        observables = raw.get("observables")
        if isinstance(observable, dict):
            if not any(key in observable for key in ("source", "path", "metric")):
                issues.append(f"observables schema missing source/path/metric in {rel}")
            return issues
        if isinstance(observables, dict) and observables:
            for name, entry in observables.items():
                if not isinstance(entry, dict):
                    issues.append(f"observables.{name} must be a table in {rel}")
                    continue
                if not any(key in entry for key in ("source", "path", "metric")):
                    issues.append(
                        f"observables.{name} missing source/path/metric in {rel}"
                    )
            return issues
        issues.append(
            f"observables schema must define [observable] or [observables] in {rel}"
        )
        return issues

    recipe = raw.get("recipe")
    recipes = raw.get("recipes")
    required_recipe_keys = ("plot", "steps", "imports", "kind", "x", "y")
    if isinstance(recipe, dict):
        if not any(key in recipe for key in required_recipe_keys):
            issues.append(f"recipe schema missing recipe definition keys in {rel}")
        return issues
    if isinstance(recipes, dict) and recipes:
        for name, entry in recipes.items():
            if not isinstance(entry, dict):
                issues.append(f"recipes.{name} must be a table in {rel}")
                continue
            if not any(key in entry for key in required_recipe_keys):
                issues.append(f"recipes.{name} missing recipe definition keys in {rel}")
        return issues
    issues.append(f"recipe schema must define [recipe] or [recipes] in {rel}")
    return issues


def validate_source_structure(source_path: Path) -> list[str]:
    """Validate that a knowledge source has the expected structure."""
    issues: list[str] = []

    if not source_path.is_dir():
        issues.append(f"Source directory not found: {source_path}")
        return issues

    if not (source_path / "profiles").is_dir():
        issues.append("Missing required directory: profiles/")

    if not (source_path / "README.md").is_file():
        issues.append("Missing required file: README.md")

    profile_paths = sorted((source_path / "profiles").glob("*.md"))
    if (source_path / "profiles").is_dir() and not profile_paths:
        issues.append("Missing required profile markdown files under profiles/*.md")

    for profile_path in profile_paths:
        try:
            content = profile_path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(f"Profile not readable: {profile_path} ({exc})")
            continue
        if not content.strip():
            issues.append(
                f"Profile is empty: {profile_path.relative_to(source_path).as_posix()}"
            )
            continue
        issues.extend(
            _validate_import_paths(
                source_path,
                _parse_import_directives(content),
                context=profile_path.relative_to(source_path).as_posix(),
            )
        )

    try:
        manifest = load_entrypoints(source_path)
    except KnowledgeSourceError as exc:
        issues.append(str(exc))
    else:
        if manifest is not None:
            issues.extend(
                _validate_import_paths(
                    source_path,
                    list(manifest.imports),
                    context=_ENTRYPOINTS_FILE,
                )
            )
            for profile_name, imports in manifest.profile_imports.items():
                if not _profile_markdown_path(source_path, profile_name).is_file():
                    issues.append(
                        f"{_ENTRYPOINTS_FILE}: profile '{profile_name}' has no "
                        "matching profiles/<name>.md"
                    )
                issues.extend(
                    _validate_import_paths(
                        source_path,
                        list(imports),
                        context=f"{_ENTRYPOINTS_FILE}: profiles.{profile_name}",
                    )
                )

    for agent_doc in sorted(source_path.rglob("agent-*.md")):
        try:
            content = agent_doc.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(f"Agent doc not readable: {agent_doc} ({exc})")
            continue
        if not content.strip():
            issues.append(
                f"Agent doc is empty: {agent_doc.relative_to(source_path).as_posix()}"
            )

    analysis_dir = source_path / "analysis"
    for kind in ("observables", "recipes"):
        kind_dir = analysis_dir / kind
        if not kind_dir.is_dir():
            continue
        for file_path in sorted(kind_dir.rglob("*.toml")):
            issues.extend(
                _validate_analysis_file(
                    file_path,
                    source_path=source_path,
                    kind=kind,
                )
            )

    return issues


def discover_profiles(source_path: Path) -> list[str]:
    """List available profile names from a knowledge source."""
    profiles_dir = source_path / "profiles"
    if not profiles_dir.is_dir():
        return []
    return sorted(p.stem for p in profiles_dir.glob("*.md"))
