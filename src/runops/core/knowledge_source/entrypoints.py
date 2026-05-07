"""Entrypoint manifest helpers for external knowledge sources."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.core.exceptions import KnowledgeSourceError
from runops.core.models.knowledge_source import KnowledgeEntrypoints, KnowledgeSource

ENTRYPOINTS_FILE = "entrypoints.toml"


def dedupe_strings(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def normalize_import_list(value: Any, *, label: str) -> list[str]:
    if value in ("", None):
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, list):
        msg = f"{label} must be a string or list of strings"
        raise KnowledgeSourceError(msg)

    imports: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str):
            msg = f"{label}[{index}] must be a string"
            raise KnowledgeSourceError(msg)
        stripped = item.strip()
        if stripped:
            imports.append(stripped)
    return imports


def load_entrypoints(
    source_path: Path,
    *,
    manifest_name: str = ENTRYPOINTS_FILE,
) -> KnowledgeEntrypoints | None:
    """Load optional entrypoints metadata from a source root."""
    manifest_path = source_path / manifest_name
    if not manifest_path.is_file():
        return None

    try:
        with open(manifest_path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        msg = f"Invalid {manifest_name} in {source_path}: {exc}"
        raise KnowledgeSourceError(msg) from exc

    imports = normalize_import_list(
        raw.get("entrypoint", ""),
        label=f"{manifest_name}: entrypoint",
    )
    imports.extend(
        normalize_import_list(
            raw.get("imports", []),
            label=f"{manifest_name}: imports",
        )
    )

    profile_imports: dict[str, tuple[str, ...]] = {}
    profiles_raw = raw.get("profiles", {})
    if profiles_raw not in ({}, None):
        if not isinstance(profiles_raw, dict):
            msg = f"{manifest_name}: [profiles] must be a table"
            raise KnowledgeSourceError(msg)
        for profile_name, profile_entry in profiles_raw.items():
            if not isinstance(profile_entry, dict):
                msg = f"{manifest_name}: [profiles.{profile_name}] must be a table"
                raise KnowledgeSourceError(msg)
            entry_imports = normalize_import_list(
                profile_entry.get("entrypoint", ""),
                label=f"{manifest_name}: profiles.{profile_name}.entrypoint",
            )
            entry_imports.extend(
                normalize_import_list(
                    profile_entry.get("imports", []),
                    label=f"{manifest_name}: profiles.{profile_name}.imports",
                )
            )
            profile_imports[str(profile_name)] = tuple(dedupe_strings(entry_imports))

    return KnowledgeEntrypoints(
        imports=tuple(dedupe_strings(imports)),
        profile_imports=profile_imports,
    )


def discover_repo_imports(repo_root: Path) -> list[str]:
    """Return repo-root imports declared via entrypoints.toml, if present."""
    manifest = load_entrypoints(repo_root)
    if manifest is None:
        return []
    return list(manifest.imports)


def resolve_import_target(base_dir: Path, rel_path: str) -> Path:
    if os.path.isabs(rel_path):
        msg = f"Import path must be relative: {rel_path}"
        raise KnowledgeSourceError(msg)

    resolved = (base_dir / rel_path).resolve()
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError as exc:
        msg = f"Import path escapes source root: {rel_path}"
        raise KnowledgeSourceError(msg) from exc
    return resolved


def parse_import_directives(markdown_text: str) -> list[str]:
    imports: list[str] = []
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("@") or stripped.startswith("@@"):
            continue
        imports.append(stripped[1:].strip())
    return dedupe_strings(imports)


def profile_markdown_path(source_path: Path, profile_name: str) -> Path:
    return source_path / "profiles" / f"{profile_name}.md"


def resolve_profile_imports(
    source_path: Path,
    source: KnowledgeSource,
) -> list[str]:
    manifest = load_entrypoints(source_path)
    imports = list(manifest.imports) if manifest is not None else []

    if source.profiles:
        for profile_name in source.profiles:
            if manifest is not None and profile_name in manifest.profile_imports:
                imports.extend(manifest.profile_imports[profile_name])
            else:
                imports.append(f"profiles/{profile_name}.md")
    elif not imports and (source_path / "CLAUDE.md").is_file():
        imports.append("CLAUDE.md")

    return dedupe_strings(imports)
