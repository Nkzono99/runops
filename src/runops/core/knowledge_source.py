"""Knowledge source management: external knowledge integration.

Handles attaching, syncing, validating, rendering, and importing
knowledge sources defined in runops.toml's ``[knowledge]`` section.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
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

from runops.core import _knowledge_source_config as knowledge_source_config
from runops.core.exceptions import KnowledgeSourceError
from runops.core.models import knowledge_source as knowledge_models

logger = logging.getLogger(__name__)

_ENTRYPOINTS_FILE = "entrypoints.toml"

ExternalKnowledgeMount = knowledge_models.ExternalKnowledgeMount
KnowledgeConfig = knowledge_models.KnowledgeConfig
KnowledgeEntrypoints = knowledge_models.KnowledgeEntrypoints
KnowledgeSource = knowledge_models.KnowledgeSource

load_knowledge_config = knowledge_source_config.load_knowledge_config
remove_knowledge_source = knowledge_source_config.remove_knowledge_source
save_knowledge_source = knowledge_source_config.save_knowledge_source
set_knowledge_source_profiles = knowledge_source_config.set_knowledge_source_profiles


def _resolve_path_source(project_root: Path, raw_path: str) -> Path:
    resolved = Path(raw_path).expanduser()
    if not resolved.is_absolute():
        resolved = (project_root / resolved).resolve()
    return resolved


def _mount_path(project_root: Path, source: KnowledgeSource) -> Path | None:
    if not source.mount:
        return None
    mount = Path(source.mount)
    if mount.is_absolute():
        msg = (
            f"Knowledge source '{source.name}' mount path must be relative: "
            f"{source.mount}"
        )
        raise KnowledgeSourceError(msg)

    resolved_root = project_root.resolve()
    candidate = project_root / mount
    resolved_parent = candidate.parent.resolve()
    try:
        resolved_parent.relative_to(resolved_root)
    except ValueError as exc:
        msg = (
            f"Knowledge source '{source.name}' mount path escapes project root: "
            f"{source.mount}"
        )
        raise KnowledgeSourceError(msg) from exc

    return resolved_parent / candidate.name


def _source_root(project_root: Path, source: KnowledgeSource) -> Path:
    if source.source_type == "path" and source.kind != "profiles":
        return _resolve_path_source(project_root, source.url)

    mount_path = _mount_path(project_root, source)
    if mount_path is None:
        msg = f"Knowledge source '{source.name}' requires a mount path"
        raise KnowledgeSourceError(msg)
    return mount_path


def _insight_source_dir(project_root: Path, source: KnowledgeSource) -> Path | None:
    root = _source_root(project_root, source)
    if source.kind == "project":
        return root / ".runops" / "insights"
    if source.kind == "insights":
        return root / "insights"
    return None


def _fact_source_file(project_root: Path, source: KnowledgeSource) -> Path | None:
    root = _source_root(project_root, source)
    candidates: list[Path] = []
    if source.kind == "project":
        candidates.append(root / ".runops" / "facts.toml")
    elif source.kind == "insights":
        candidates.extend(
            [
                root / "facts.toml",
                root / ".runops" / "facts.toml",
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _repo_name_from_url(url: str) -> str:
    """Extract repository name from a git URL."""
    stem = url.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if stem.endswith(".git"):
        stem = stem[:-4]
    return stem


def _safe_namespace(value: str) -> str:
    """Return a filesystem-safe namespace token for imported knowledge."""
    normalized = [ch.lower() if ch.isalnum() else "_" for ch in value.strip()]
    token = "".join(normalized).strip("_")
    while "__" in token:
        token = token.replace("__", "_")
    return token or "source"


def _namespaced_insight_filename(source: KnowledgeSource, insight_name: str) -> str:
    """Build the destination filename for an imported insight."""
    namespace = _safe_namespace(source.name)
    return f"{namespace}__{insight_name}.md"


def _dedupe_strings(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _normalize_import_list(value: Any, *, label: str) -> list[str]:
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
    manifest_name: str = _ENTRYPOINTS_FILE,
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

    imports = _normalize_import_list(
        raw.get("entrypoint", ""),
        label=f"{manifest_name}: entrypoint",
    )
    imports.extend(
        _normalize_import_list(
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
            entry_imports = _normalize_import_list(
                profile_entry.get("entrypoint", ""),
                label=f"{manifest_name}: profiles.{profile_name}.entrypoint",
            )
            entry_imports.extend(
                _normalize_import_list(
                    profile_entry.get("imports", []),
                    label=f"{manifest_name}: profiles.{profile_name}.imports",
                )
            )
            profile_imports[str(profile_name)] = tuple(_dedupe_strings(entry_imports))

    return KnowledgeEntrypoints(
        imports=tuple(_dedupe_strings(imports)),
        profile_imports=profile_imports,
    )


def discover_repo_imports(repo_root: Path) -> list[str]:
    """Return repo-root imports declared via entrypoints.toml, if present."""
    manifest = load_entrypoints(repo_root)
    if manifest is None:
        return []
    return list(manifest.imports)


def _resolve_import_target(base_dir: Path, rel_path: str) -> Path:
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


def _parse_import_directives(markdown_text: str) -> list[str]:
    imports: list[str] = []
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("@") or stripped.startswith("@@"):
            continue
        imports.append(stripped[1:].strip())
    return _dedupe_strings(imports)


def _profile_markdown_path(source_path: Path, profile_name: str) -> Path:
    return source_path / "profiles" / f"{profile_name}.md"


def _resolve_profile_imports(
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

    return _dedupe_strings(imports)


def collect_external_knowledge(project_root: Path) -> list[ExternalKnowledgeMount]:
    """Return configured knowledge sources."""
    entries: list[ExternalKnowledgeMount] = []

    config = load_knowledge_config(project_root)
    if config is not None:
        for source in config.sources:
            try:
                source_path = _source_root(project_root, source)
            except KnowledgeSourceError:
                try:
                    fallback_mount = _mount_path(project_root, source)
                except KnowledgeSourceError:
                    fallback_mount = None
                source_path = fallback_mount or project_root
            available = source_path.is_dir()
            entries.append(
                ExternalKnowledgeMount(
                    name=source.name,
                    source_type=source.source_type,
                    kind=source.kind,
                    path=source_path,
                    display_path=source.mount or str(source_path),
                    exists=available,
                    profiles_enabled=(
                        list(source.profiles) if source.kind == "profiles" else []
                    ),
                    profiles_available=(
                        discover_profiles(source_path)
                        if available and source.kind == "profiles"
                        else []
                    ),
                )
            )

    return sorted(entries, key=lambda entry: entry.name.lower())


# ---------- Source sync ----------


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _mirror_directory(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)

    source_names = {entry.name for entry in source_dir.iterdir()}
    for existing in list(target_dir.iterdir()):
        if existing.name not in source_names:
            _remove_path(existing)

    for source_entry in source_dir.iterdir():
        target_entry = target_dir / source_entry.name

        if source_entry.is_symlink():
            resolved_entry = source_entry.resolve()
            if resolved_entry.is_dir():
                if target_entry.exists() and (
                    not target_entry.is_dir() or target_entry.is_symlink()
                ):
                    _remove_path(target_entry)
                _mirror_directory(resolved_entry, target_entry)
            else:
                if target_entry.exists():
                    _remove_path(target_entry)
                shutil.copy2(resolved_entry, target_entry)
            continue

        if source_entry.is_dir():
            if target_entry.exists() and (
                not target_entry.is_dir() or target_entry.is_symlink()
            ):
                _remove_path(target_entry)
            _mirror_directory(source_entry, target_entry)
            continue

        if target_entry.exists():
            _remove_path(target_entry)
        shutil.copy2(source_entry, target_entry)


def sync_source(project_root: Path, source: KnowledgeSource) -> str:
    """Synchronize a single knowledge source.

    For git sources: clone if missing, pull if existing.
    For path sources: verify existence.

    Returns:
        Status string describing what happened.

    Raises:
        KnowledgeSourceError: If sync fails.
    """
    if source.source_type == "path":
        resolved = _resolve_path_source(project_root, source.url)
        if not resolved.is_dir():
            raise KnowledgeSourceError(f"Knowledge source path not found: {resolved}")
        if source.kind != "profiles":
            return "available"

        mount_path = _mount_path(project_root, source)
        if mount_path is None:
            raise KnowledgeSourceError(
                f"Knowledge source '{source.name}' requires a mount path"
            )
        mount_path.parent.mkdir(parents=True, exist_ok=True)

        if mount_path.exists():
            if mount_path.is_symlink():
                return "exists"
            if mount_path.is_dir():
                _mirror_directory(resolved, mount_path)
                return "updated-copy"
            return "exists"

        try:
            mount_path.symlink_to(resolved, target_is_directory=True)
            return "linked"
        except OSError as e:
            logger.info(
                "Symlink unavailable for knowledge source %s (%s); "
                "falling back to directory copy",
                source.name,
                e,
            )
            _mirror_directory(resolved, mount_path)
            return "copied"

    # git source
    mount_path = _mount_path(project_root, source)
    if mount_path is None:
        raise KnowledgeSourceError(
            f"Knowledge source '{source.name}' requires a mount path"
        )
    if mount_path.is_dir() and (mount_path / ".git").exists():
        # Pull
        result = subprocess.run(
            ["git", "-C", str(mount_path), "pull", "--ff-only"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            logger.warning("git pull failed for %s: %s", source.name, result.stderr)
            return "pull-failed"
        return "updated"

    # Clone
    mount_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", source.url, str(mount_path)]
    if source.ref:
        cmd.extend(["--branch", source.ref])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise KnowledgeSourceError(
            f"git clone failed for {source.name}: {(result.stderr or '').strip()[:300]}"
        )
    return "cloned"


def sync_all_sources(
    project_root: Path, config: KnowledgeConfig
) -> list[tuple[str, str]]:
    """Synchronize all knowledge sources.

    Returns:
        List of (source_name, status) tuples.
    """
    results: list[tuple[str, str]] = []
    for source in config.sources:
        try:
            status = sync_source(project_root, source)
        except KnowledgeSourceError as e:
            logger.warning("Failed to sync %s: %s", source.name, e)
            status = f"error: {e}"
        results.append((source.name, status))
    return results


def import_external_insights(
    project_root: Path,
    sources: list[KnowledgeSource],
    *,
    simulator: str = "",
) -> tuple[int, int]:
    """Import insights from configured external sources.

    Imported insight filenames are namespaced by source name to avoid
    collisions across multiple upstream projects or knowledge stores.
    """
    from runops.core.knowledge import get_insights_dir, parse_insight

    our_insights_dir = get_insights_dir(project_root)
    imported = 0
    skipped = 0

    for source in sources:
        source_dir = _insight_source_dir(project_root, source)
        if source_dir is None or not source_dir.is_dir():
            continue

        for md_file in sorted(source_dir.glob("*.md")):
            insight = parse_insight(md_file)
            if insight is None:
                continue
            if simulator and insight.simulator != simulator:
                continue

            dest = our_insights_dir / _namespaced_insight_filename(source, md_file.stem)
            if dest.exists():
                skipped += 1
                continue

            shutil.copy2(md_file, dest)
            imported += 1

    return imported, skipped


def import_external_facts(
    project_root: Path,
    sources: list[KnowledgeSource],
    *,
    simulator: str = "",
) -> tuple[int, int]:
    """Sync structured facts from external sources into candidate transport."""
    from runops.core.knowledge import get_candidate_facts_dir

    if tomli_w is None:
        msg = "tomli_w is required to write candidate fact transport"
        raise RuntimeError(msg)

    candidate_dir = get_candidate_facts_dir(project_root)
    synced_sources = 0
    total_facts = 0

    for source in sources:
        facts_file = _fact_source_file(project_root, source)
        dest = candidate_dir / f"{_safe_namespace(source.name)}.toml"
        if facts_file is None:
            if dest.exists():
                dest.unlink()
            continue

        with open(facts_file, "rb") as f:
            raw = tomllib.load(f)

        selected: list[dict[str, Any]] = []
        for item in raw.get("facts", []):
            if not isinstance(item, dict):
                continue
            item_simulator = str(item.get("simulator", "")).strip()
            if simulator and item_simulator not in {"", simulator}:
                continue
            selected.append(dict(item))

        if not selected:
            if dest.exists():
                dest.unlink()
            synced_sources += 1
            continue

        payload = {
            "transport": {
                "source": source.name,
                "kind": source.kind,
                "source_path": str(_source_root(project_root, source)),
                "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            "facts": selected,
        }
        with open(dest, "wb") as f:
            tomli_w.dump(payload, f)

        synced_sources += 1
        total_facts += len(selected)

    return synced_sources, total_facts


def validate_source_structure(source_path: Path) -> list[str]:
    """Validate that a knowledge source has the expected structure."""
    from runops.core.knowledge_source_validation import (
        validate_source_structure as _validate_source_structure,
    )

    return _validate_source_structure(source_path)


def discover_profiles(source_path: Path) -> list[str]:
    """List available profile names from a knowledge source."""
    from runops.core.knowledge_source_validation import (
        discover_profiles as _discover_profiles,
    )

    return _discover_profiles(source_path)


# ---------- Rendering ----------


def render_imports(
    project_root: Path,
    config: KnowledgeConfig,
    *,
    extra_imports: list[str] | None = None,
) -> Path:
    """Generate imports.md from enabled profiles."""
    from runops.core.knowledge_source_render import (
        render_imports as _render_imports,
    )

    return _render_imports(
        project_root,
        config,
        extra_imports=extra_imports,
    )
