"""Data models for external knowledge source integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MOUNT_DIR = "refs/knowledge"
DEFAULT_DERIVED_DIR = ".runops/knowledge"


@dataclass(frozen=True)
class KnowledgeSource:
    """A single external knowledge source.

    Attributes:
        name: Source identifier (e.g. ``"shared-lab-knowledge"``).
        source_type: ``"git"`` or ``"path"``.
        kind: How the source is consumed.
            ``"profiles"`` mounts shared knowledge profiles and agent docs.
            ``"project"`` imports insights from another runops project.
            ``"insights"`` imports insights from a shared knowledge store.
        url: Git URL or filesystem path to the source.
        ref: Git ref to checkout (default ``"main"``).
        mount: Relative checkout/mount path from project root.
            Required for git sources and ``profiles`` sources.
        profiles: List of enabled profile names from this source
            (``profiles`` kind only).
    """

    name: str
    source_type: str
    url: str
    kind: str = "profiles"
    ref: str = "main"
    mount: str = ""
    profiles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeConfig:
    """Knowledge integration configuration from runops.toml.

    Attributes:
        enabled: Whether knowledge integration is active.
        mount_dir: Base directory for mounting sources.
        derived_dir: Directory for generated/derived knowledge files.
        auto_sync_on_setup: Sync sources during ``runops setup``.
        generate_claude_imports: Generate CLAUDE.md import stubs.
        sources: List of configured knowledge sources.
    """

    enabled: bool = True
    mount_dir: str = DEFAULT_MOUNT_DIR
    derived_dir: str = DEFAULT_DERIVED_DIR
    auto_sync_on_setup: bool = True
    generate_claude_imports: bool = True
    sources: list[KnowledgeSource] = field(default_factory=list)


@dataclass(frozen=True)
class ExternalKnowledgeMount:
    """Normalized view of an attached knowledge source.

    Attributes:
        name: User-facing identifier.
        source_type: Concrete transport type such as ``"git"`` or ``"path"``.
        kind: Content shape such as ``"profiles"``, ``"project"``,
            or ``"insights"``.
        path: Resolved absolute path for this source.
        display_path: Relative mount path or resolved source path to show in CLI.
        exists: Whether the source is currently available locally.
        profiles_enabled: Enabled profile names for ``profiles`` sources.
        profiles_available: Discovered profile names for ``profiles`` sources.
    """

    name: str
    source_type: str
    kind: str
    path: Path
    display_path: str
    exists: bool
    profiles_enabled: list[str] = field(default_factory=list)
    profiles_available: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeEntrypoints:
    """Entrypoints declared by a knowledge source or repo root."""

    imports: tuple[str, ...] = ()
    profile_imports: dict[str, tuple[str, ...]] = field(default_factory=dict)
