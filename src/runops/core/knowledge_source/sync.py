"""Synchronization helpers for external knowledge sources."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from runops.core.exceptions import KnowledgeSourceError
from runops.core.models.knowledge_source import KnowledgeConfig, KnowledgeSource

from .paths import mount_path, resolve_path_source

logger = logging.getLogger(__name__)


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def mirror_directory(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)

    source_names = {entry.name for entry in source_dir.iterdir()}
    for existing in list(target_dir.iterdir()):
        if existing.name not in source_names:
            remove_path(existing)

    for source_entry in source_dir.iterdir():
        target_entry = target_dir / source_entry.name

        if source_entry.is_symlink():
            resolved_entry = source_entry.resolve()
            if resolved_entry.is_dir():
                if target_entry.exists() and (
                    not target_entry.is_dir() or target_entry.is_symlink()
                ):
                    remove_path(target_entry)
                mirror_directory(resolved_entry, target_entry)
            else:
                if target_entry.exists():
                    remove_path(target_entry)
                shutil.copy2(resolved_entry, target_entry)
            continue

        if source_entry.is_dir():
            if target_entry.exists() and (
                not target_entry.is_dir() or target_entry.is_symlink()
            ):
                remove_path(target_entry)
            mirror_directory(source_entry, target_entry)
            continue

        if target_entry.exists():
            remove_path(target_entry)
        shutil.copy2(source_entry, target_entry)


def sync_source(project_root: Path, source: KnowledgeSource) -> str:
    """Synchronize a single knowledge source."""
    if source.source_type == "path":
        resolved = resolve_path_source(project_root, source.url)
        if not resolved.is_dir():
            raise KnowledgeSourceError(f"Knowledge source path not found: {resolved}")
        if source.kind != "profiles":
            return "available"

        resolved_mount = mount_path(project_root, source)
        if resolved_mount is None:
            raise KnowledgeSourceError(
                f"Knowledge source '{source.name}' requires a mount path"
            )
        resolved_mount.parent.mkdir(parents=True, exist_ok=True)

        if resolved_mount.exists():
            if resolved_mount.is_symlink():
                return "exists"
            if resolved_mount.is_dir():
                mirror_directory(resolved, resolved_mount)
                return "updated-copy"
            return "exists"

        try:
            resolved_mount.symlink_to(resolved, target_is_directory=True)
            return "linked"
        except OSError as e:
            logger.info(
                "Symlink unavailable for knowledge source %s (%s); "
                "falling back to directory copy",
                source.name,
                e,
            )
            mirror_directory(resolved, resolved_mount)
            return "copied"

    resolved_mount = mount_path(project_root, source)
    if resolved_mount is None:
        raise KnowledgeSourceError(
            f"Knowledge source '{source.name}' requires a mount path"
        )
    if resolved_mount.is_dir() and (resolved_mount / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(resolved_mount), "pull", "--ff-only"],
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

    resolved_mount.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", source.url, str(resolved_mount)]
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
    """Synchronize all knowledge sources."""
    results: list[tuple[str, str]] = []
    for source in config.sources:
        try:
            status = sync_source(project_root, source)
        except KnowledgeSourceError as e:
            logger.warning("Failed to sync %s: %s", source.name, e)
            status = f"error: {e}"
        results.append((source.name, status))
    return results
