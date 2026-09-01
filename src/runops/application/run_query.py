"""Shared run discovery and filtering for operator-facing views."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from runops.core.discovery import (
    discover_active_runs,
    discover_active_runs_checked,
    discover_runs,
    discover_runs_checked,
    require_run_directory,
)
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, read_manifest
from runops.core.run.curation import has_valid_run_review

RunQueryView = Literal["active", "all"]

_INACTIVE_STATUSES = frozenset({"archived", "purged"})
_VALID_RUN_STATUSES = frozenset(
    {
        "created",
        "submitted",
        "running",
        "completed",
        "failed",
        "cancelled",
        "archived",
        "purged",
    }
)
_PROJECT_FILE = "runops.toml"
_RUN_ID_PATTERN = re.compile(r"^R\d{8}-\d{4}$")


@dataclass(frozen=True)
class RunQueryEntry:
    """One discovered run and its best-effort manifest snapshot."""

    run_dir: Path
    manifest: ManifestData | None

    @property
    def status(self) -> str:
        if self.manifest is None:
            return "unknown"
        return str(self.manifest.run.get("status", "unknown"))

    @property
    def tags(self) -> tuple[str, ...]:
        if self.manifest is None:
            return ()
        raw_tags = self.manifest.classification.get("tags", [])
        if not isinstance(raw_tags, list):
            return ()
        return tuple(str(item) for item in raw_tags)

    @property
    def experiment_id(self) -> str:
        if self.manifest is None:
            return ""
        return str(self.manifest.intent.get("experiment_id", ""))

    @property
    def purpose(self) -> str:
        if self.manifest is None:
            return ""
        return str(self.manifest.intent.get("purpose", ""))

    @property
    def review_status(self) -> str:
        if self.manifest is None:
            return ""
        return (
            "reviewed" if has_valid_run_review(self.manifest.curation) else "unreviewed"
        )

    @property
    def storage_tier(self) -> str:
        if self.manifest is None:
            return ""
        return str(self.manifest.storage.get("tier", "hot"))

    @property
    def storage_form(self) -> str:
        if self.manifest is None:
            return ""
        return str(self.manifest.storage.get("form", "full"))


def resolve_run_query_view(
    *,
    include_archived: bool = False,
    status_filter: str | None = None,
    storage_tier: str | None = None,
    storage_form: str | None = None,
) -> RunQueryView:
    """Choose the view implied by public list filters.

    An explicit inactive-state filter is equivalent to asking for the all
    view.  Filters for active states retain the active traversal, preventing
    failed/cancelled runs inside archived bundles from leaking into results.
    """
    if (
        include_archived
        or status_filter in _INACTIVE_STATUSES
        or storage_tier is not None
        or storage_form is not None
    ):
        return "all"
    return "active"


def query_runs(
    scopes: Path | Iterable[Path],
    *,
    view: RunQueryView = "active",
    strict_manifests: bool = False,
) -> list[RunQueryEntry]:
    """Discover runs within safe scopes for an operator-facing view.

    A path that is itself a runops project root is narrowed to its ``runs/``
    tree.  This prevents result manifests under ``research/`` from being
    mistaken for execution runs.  Arbitrary survey/run scopes remain valid.
    ``strict_manifests`` is reserved for aggregate views that must not publish
    a partial count when even one canonical manifest is invalid/unreadable or
    any formal Run ID is duplicated anywhere in the canonical namespace.

    Exhaustive identity operations must use :func:`discover_runs` directly;
    this service is intentionally limited to list, MCP, and context views.
    """
    if view not in ("active", "all"):
        raise ValueError(f"Unknown run query view: {view!r}")

    requested_scopes = (scopes,) if isinstance(scopes, Path) else tuple(scopes)
    normalized_scopes = tuple(_safe_run_scope(scope) for scope in requested_scopes)
    namespace_roots_by_scope = {
        scope: namespace_root
        for scope in normalized_scopes
        if (namespace_root := _formal_run_namespace_root(scope)) is not None
    }
    inline_strict_roots = {
        namespace_root
        for scope, namespace_root in namespace_roots_by_scope.items()
        if strict_manifests and view == "all" and scope == namespace_root
    }
    if strict_manifests:
        for namespace_root in sorted(
            set(namespace_roots_by_scope.values()) - inline_strict_roots
        ):
            _require_strict_formal_namespace(namespace_root)

    seen: set[Path] = set()
    entries: list[RunQueryEntry] = []
    inline_run_id_paths: dict[Path, dict[str, list[Path]]] = {
        root: {} for root in inline_strict_roots
    }
    for scope in normalized_scopes:
        formal_namespace = _is_formal_run_scope(scope)
        if formal_namespace:
            discover = (
                discover_active_runs_checked
                if view == "active"
                else discover_runs_checked
            )
        else:
            discover = discover_active_runs if view == "active" else discover_runs
        for run_dir in discover(scope):
            try:
                resolved = require_run_directory(run_dir)
            except SimctlError as exc:
                # A malformed manifest under the canonical runs/ namespace is
                # still operational state and must remain visible as unknown.
                # Outside that namespace (notably research/results/) a
                # non-Run manifest is a different entity and is ignored.
                if not formal_namespace:
                    continue
                if strict_manifests:
                    raise SimctlError(
                        "Cannot summarize the formal Run namespace because "
                        f"a manifest is invalid at {run_dir}: {exc}"
                    ) from exc
                resolved = run_dir.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                manifest = read_manifest(resolved)
            except SimctlError as exc:
                if strict_manifests:
                    raise SimctlError(
                        "Cannot summarize the formal Run namespace because "
                        f"a manifest is unreadable at {resolved}: {exc}"
                    ) from exc
                manifest = None
            if strict_manifests and manifest is not None:
                run_id = _require_summary_manifest_contract(resolved, manifest)
                namespace_root = namespace_roots_by_scope.get(scope)
                if namespace_root in inline_strict_roots:
                    inline_run_id_paths[namespace_root].setdefault(run_id, []).append(
                        resolved
                    )
            entries.append(RunQueryEntry(run_dir=resolved, manifest=manifest))

    for namespace_root in sorted(inline_strict_roots):
        _require_unique_run_ids(inline_run_id_paths[namespace_root])
    return sorted(entries, key=lambda entry: entry.run_dir)


def _require_summary_manifest_contract(
    run_dir: Path,
    manifest: ManifestData,
) -> str:
    """Validate fields required before publishing strict aggregate values."""
    run_id = manifest.run.get("id")
    if not isinstance(run_id, str) or _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise SimctlError(
            "Cannot summarize the formal Run namespace because manifest "
            f"run.id is invalid at {run_dir}: {run_id!r}"
        )
    status = manifest.run.get("status")
    if not isinstance(status, str) or status not in _VALID_RUN_STATUSES:
        raise SimctlError(
            "Cannot summarize the formal Run namespace because manifest "
            f"run.status is invalid at {run_dir}: {status!r}"
        )
    return run_id


def _require_strict_formal_namespace(namespace_root: Path) -> None:
    """Prove that every formal Run identity is valid and project-unique."""
    run_id_paths: dict[str, list[Path]] = {}
    for run_dir in discover_runs_checked(namespace_root):
        try:
            resolved = require_run_directory(run_dir)
        except SimctlError as exc:
            raise SimctlError(
                "Cannot summarize the formal Run namespace because "
                f"a manifest is invalid at {run_dir}: {exc}"
            ) from exc
        try:
            manifest = read_manifest(resolved)
        except SimctlError as exc:
            raise SimctlError(
                "Cannot summarize the formal Run namespace because "
                f"a manifest is unreadable at {resolved}: {exc}"
            ) from exc
        run_id = _require_summary_manifest_contract(resolved, manifest)
        run_id_paths.setdefault(run_id, []).append(resolved)

    _require_unique_run_ids(run_id_paths)


def _require_unique_run_ids(run_id_paths: dict[str, list[Path]]) -> None:
    """Reject a strict namespace snapshot containing any duplicate identity."""
    for run_id, paths in sorted(run_id_paths.items()):
        if len(paths) < 2:
            continue
        locations = ", ".join(str(path) for path in sorted(paths))
        raise SimctlError(
            "Cannot summarize the formal Run namespace because "
            f"run.id {run_id} is duplicated at: {locations}"
        )


def filter_run_query(
    entries: Iterable[RunQueryEntry],
    *,
    status_filter: str | None = None,
    tag: str | None = None,
    experiment_id: str | None = None,
    purpose: str | None = None,
    review_status: str | None = None,
    storage_tier: str | None = None,
    storage_form: str | None = None,
) -> list[RunQueryEntry]:
    """Apply manifest filters shared by CLI and MCP list interfaces."""
    has_filter = any(
        value is not None
        for value in (
            status_filter,
            tag,
            experiment_id,
            purpose,
            review_status,
            storage_tier,
            storage_form,
        )
    )
    selected: list[RunQueryEntry] = []
    for entry in entries:
        if entry.manifest is None:
            if not has_filter:
                selected.append(entry)
            continue
        if status_filter and entry.status != status_filter:
            continue
        if tag and tag not in entry.tags:
            continue
        if experiment_id and entry.experiment_id != experiment_id:
            continue
        if purpose and entry.purpose != purpose:
            continue
        if review_status and entry.review_status != review_status:
            continue
        if storage_tier and entry.storage_tier != storage_tier:
            continue
        if storage_form and entry.storage_form != storage_form:
            continue
        selected.append(entry)
    return selected


def _safe_run_scope(scope: Path) -> Path:
    """Narrow an explicit project root to its execution-run subtree."""
    resolved = scope.resolve()
    runs_tree = resolved / "runs"
    if (resolved / _PROJECT_FILE).is_file() or runs_tree.is_dir():
        return runs_tree
    return resolved


def _is_formal_run_scope(scope: Path) -> bool:
    """Return whether a scope is the canonical runs/ tree or any subtree."""
    return any(candidate.name == "runs" for candidate in (scope, *scope.parents))


def _formal_run_namespace_root(scope: Path) -> Path | None:
    """Resolve the project-wide canonical ``runs/`` root containing a scope."""
    candidates = tuple(
        candidate for candidate in (scope, *scope.parents) if candidate.name == "runs"
    )
    for candidate in candidates:
        if (candidate.parent / _PROJECT_FILE).is_file():
            return candidate
    return candidates[-1] if candidates else None
