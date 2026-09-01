"""Application services for the minimal research workspace."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import tomli_w

from runops.application.run_creation.staging import move_path_noreplace
from runops.application.state_root import require_project_state_root
from runops.core.exceptions import SimctlError
from runops.core.research.workspace import ResearchBudget

JST = timezone(timedelta(hours=9), name="JST")
_JOURNAL_HEADER = "# Research Journal\n\n"
_RESULT_ID = re.compile(r"^R(?P<number>\d{4})-")
_RESULT_DIRECTORY = re.compile(r"^R\d{4}-[A-Za-z0-9._-]+$")
_DUPLICATE_FORMATS = frozenset({".csv", ".json", ".md"})
_CHRONOLOGICAL_HEADING = re.compile(
    r"^\s{0,3}#{1,6}\s+(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}:\d{2}\b)",
    re.MULTILINE,
)
_PATH_PREFIXES = (
    "./",
    "../",
    "/",
    ".runops/",
    "analysis/",
    "exports/",
    "materials/",
    "research/",
    "runs/",
)


class ResearchWorkspaceError(Exception):
    """Raised when the research workspace is invalid or unsafe to mutate."""


@dataclass(frozen=True)
class WorkspaceIssue:
    """One deterministic workspace budget or layout issue."""

    severity: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable issue."""
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class ResearchWorkspaceStatus:
    """Quantity metrics and issues for the active research workspace."""

    root: Path
    current_chars: int
    current_lines: int
    current_path_references: int
    current_chronological_headings: int
    journal_chars: int
    active_result_count: int
    result_readme_chars: int
    artifact_files: int
    artifact_bytes: int
    issues: tuple[WorkspaceIssue, ...]
    budget: ResearchBudget

    @property
    def ok(self) -> bool:
        """Return whether the workspace has no error-level issue."""
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON shape used by CLI and agent context."""
        return {
            "root": str(self.root),
            "ok": self.ok,
            "current_chars": self.current_chars,
            "current_lines": self.current_lines,
            "current_path_references": self.current_path_references,
            "current_chronological_headings": self.current_chronological_headings,
            "journal_chars": self.journal_chars,
            "active_result_count": self.active_result_count,
            "result_readme_chars": self.result_readme_chars,
            "artifact_files": self.artifact_files,
            "artifact_bytes": self.artifact_bytes,
            "budget": self.budget.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class JournalAppendResult:
    """Result of appending one entry to the active journal."""

    path: Path
    chars: int
    rotated_to: Path | None = None


@dataclass(frozen=True)
class ResultWorkspace:
    """A newly created result workspace."""

    result_id: str
    path: Path


@dataclass(frozen=True)
class ResultWorkspaceInspection:
    """Result-local narrative, artifact quantities, and layout issues."""

    path: Path
    readme_chars: int
    artifact_files: int
    artifact_bytes: int
    issues: tuple[WorkspaceIssue, ...]

    @property
    def ok(self) -> bool:
        """Return whether the Result has no error-level local issue."""
        return not any(issue.severity == "error" for issue in self.issues)


@dataclass(frozen=True)
class LegacyMigration:
    """Deterministic, reversible relocation of one legacy workspace path."""

    source: Path
    destination: Path

    def to_dict(self, root: Path) -> dict[str, str]:
        """Return project-relative paths for CLI and the recovery manifest."""
        return {
            "source": _relative(self.source, root),
            "destination": _relative(self.destination, root),
        }


def plan_legacy_migration(project_root: Path) -> tuple[LegacyMigration, ...]:
    """Plan legacy relocations without interpreting or deleting research content."""
    root = project_root.resolve()
    legacy_root = root / "research" / "archive" / "legacy"
    candidates = [
        (root / "notes", legacy_root / "notes"),
        (root / "exports", legacy_root / "exports"),
        (root / ".harnessops", legacy_root / "harnessops" / ".harnessops"),
        (root / "harness-feedback", legacy_root / "harnessops" / "harness-feedback"),
        (root / "analysis" / "cross_run", legacy_root / "analysis" / "cross_run"),
    ]
    for name in (
        "README.md",
        "agenda.md",
        "experiments.toml",
        "paper_requests.toml",
        "proposals",
        "reviews",
    ):
        candidates.append((root / "research" / name, legacy_root / "research" / name))

    cross_run = root / "analysis" / "cross_run"
    analysis = root / "analysis"
    if analysis.is_dir() and not analysis.is_symlink():
        for markdown in sorted(analysis.rglob("*.md")):
            if cross_run in markdown.parents:
                continue
            candidates.append(
                (
                    markdown,
                    legacy_root / "analysis" / markdown.relative_to(analysis),
                )
            )

    planned: list[LegacyMigration] = []
    for source, destination in candidates:
        if not source.exists() and not source.is_symlink():
            continue
        if source.is_symlink():
            raise ResearchWorkspaceError(
                f"legacy migration refuses symlink source: {_relative(source, root)}"
            )
        if destination.exists() or destination.is_symlink():
            raise ResearchWorkspaceError(
                "legacy migration destination already exists: "
                f"{_relative(destination, root)}"
            )
        planned.append(LegacyMigration(source, destination))
    return tuple(planned)


def migrate_legacy_workspace(project_root: Path) -> tuple[LegacyMigration, ...]:
    """Relocate legacy paths intact and record enough information to restore them."""
    root = project_root.resolve()
    with _research_workspace_lock(root):
        legacy_root = root / "research" / "archive" / "legacy"
        manifest = legacy_root / "MIGRATION.json"
        if manifest.exists() or manifest.is_symlink():
            payload, moves, completed, restored = _load_legacy_migration_manifest(
                root,
                manifest,
            )
            if restored or payload.get("status") in {"restoring", "restored"}:
                raise ResearchWorkspaceError(
                    "legacy restore is already in progress; resume restore instead"
                )
        else:
            moves = plan_legacy_migration(root)
            if not moves:
                return ()
            _ensure_safe_directory(legacy_root, root=root, label="legacy archive")
            completed = ()
            payload = {
                "schema_version": 1,
                "status": "moving",
                "moves": [item.to_dict(root) for item in moves],
                "completed": [],
                "restored": [],
            }
            _write_json_new(manifest, payload)
        return _resume_legacy_migration_locked(
            root,
            manifest,
            payload,
            moves,
            completed,
        )


def restore_legacy_workspace(project_root: Path) -> tuple[LegacyMigration, ...]:
    """Restore every completed legacy relocation and retain no hidden deletion."""
    root = project_root.resolve()
    with _research_workspace_lock(root):
        manifest = root / "research" / "archive" / "legacy" / "MIGRATION.json"
        payload, moves, completed, restored = _load_legacy_migration_manifest(
            root,
            manifest,
        )
        try:
            completed = _reconcile_uncheckpointed_migration_moves(
                root,
                manifest,
                payload,
                moves,
                completed,
            )
            payload["status"] = "restoring"
            payload["completed"] = [item.to_dict(root) for item in completed]
            payload["restored"] = [item.to_dict(root) for item in restored]
            _write_json_replace(manifest, payload)
            restored_set = set(restored)
            for item in reversed(completed):
                if item in restored_set:
                    _require_restored_legacy_state(item, root=root)
                    continue
                source_present = _path_present(item.source)
                destination_present = _path_present(item.destination)
                if source_present and not destination_present:
                    _require_safe_legacy_path(item.source, label="restored legacy path")
                elif not source_present and destination_present:
                    _require_safe_legacy_path(
                        item.destination,
                        label="archived legacy path",
                    )
                    _ensure_safe_directory(
                        item.source.parent,
                        root=root,
                        label="legacy restore parent",
                    )
                    move_path_noreplace(item.destination, item.source)
                elif source_present and destination_present:
                    raise ResearchWorkspaceError(
                        "restore destination already exists: "
                        f"{_relative(item.source, root)}"
                    )
                else:
                    raise ResearchWorkspaceError(
                        "archived legacy path is missing: "
                        f"{_relative(item.destination, root)}"
                    )
                restored_set.add(item)
                restored = (*restored, item)
                payload["restored"] = [
                    restored_item.to_dict(root) for restored_item in restored
                ]
                _write_json_replace(manifest, payload)
            payload["status"] = "restored"
            _write_json_replace(manifest, payload)
            manifest.unlink()
            _fsync_directory(manifest.parent)
        except (OSError, SimctlError, ResearchWorkspaceError) as exc:
            raise ResearchWorkspaceError(
                f"legacy restore stopped; resume with MIGRATION.json: {exc}"
            ) from exc
        return completed


def _resume_legacy_migration_locked(
    root: Path,
    manifest: Path,
    payload: dict[str, Any],
    moves: tuple[LegacyMigration, ...],
    completed: tuple[LegacyMigration, ...],
) -> tuple[LegacyMigration, ...]:
    """Resume migration from its last durable per-move checkpoint."""
    completed_set = set(completed)
    try:
        for item in moves:
            if item in completed_set:
                _require_migrated_legacy_state(item, root=root)
                continue
            source_present = _path_present(item.source)
            destination_present = _path_present(item.destination)
            if not source_present and destination_present:
                _require_safe_legacy_path(
                    item.destination,
                    label="archived legacy path",
                )
            elif source_present and not destination_present:
                _require_safe_legacy_path(item.source, label="legacy source")
                _ensure_safe_directory(
                    item.destination.parent,
                    root=root,
                    label="legacy archive parent",
                )
                move_path_noreplace(item.source, item.destination)
            elif source_present and destination_present:
                raise ResearchWorkspaceError(
                    "legacy migration destination already exists: "
                    f"{_relative(item.destination, root)}"
                )
            else:
                raise ResearchWorkspaceError(
                    "legacy migration source is missing: "
                    f"{_relative(item.source, root)}"
                )
            completed_set.add(item)
            completed = (*completed, item)
            payload["completed"] = [
                completed_item.to_dict(root) for completed_item in completed
            ]
            _write_json_replace(manifest, payload)
        payload["status"] = "complete"
        _write_json_replace(manifest, payload)
    except (OSError, SimctlError, ResearchWorkspaceError) as exc:
        raise ResearchWorkspaceError(
            f"legacy migration stopped; resume with MIGRATION.json: {exc}"
        ) from exc
    return moves


def _reconcile_uncheckpointed_migration_moves(
    root: Path,
    manifest: Path,
    payload: dict[str, Any],
    moves: tuple[LegacyMigration, ...],
    completed: tuple[LegacyMigration, ...],
) -> tuple[LegacyMigration, ...]:
    """Checkpoint moves that became visible before a prior manifest write."""
    completed_set = set(completed)
    for item in moves:
        if item in completed_set:
            continue
        source_present = _path_present(item.source)
        destination_present = _path_present(item.destination)
        if not source_present and destination_present:
            _require_safe_legacy_path(
                item.destination,
                label="archived legacy path",
            )
            completed_set.add(item)
            completed = (*completed, item)
            payload["completed"] = [
                completed_item.to_dict(root) for completed_item in completed
            ]
            _write_json_replace(manifest, payload)
        elif source_present and destination_present:
            raise ResearchWorkspaceError(
                "legacy migration destination already exists: "
                f"{_relative(item.destination, root)}"
            )
        elif not source_present and not destination_present:
            raise ResearchWorkspaceError(
                f"legacy migration source is missing: {_relative(item.source, root)}"
            )
    return completed


def _load_legacy_migration_manifest(
    root: Path,
    manifest: Path,
) -> tuple[
    dict[str, Any],
    tuple[LegacyMigration, ...],
    tuple[LegacyMigration, ...],
    tuple[LegacyMigration, ...],
]:
    """Load and validate one resumable legacy migration manifest."""
    try:
        raw = json.loads(_read_safe_regular_text(manifest, label="migration manifest"))
    except json.JSONDecodeError as exc:
        raise ResearchWorkspaceError(
            f"invalid legacy migration manifest: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise ResearchWorkspaceError("invalid legacy migration manifest: expected map")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise ResearchWorkspaceError(
            "invalid legacy migration manifest: schema_version must be integer 1"
        )
    status_value = raw.get("status")
    if status_value not in {"moving", "complete", "restoring", "restored"}:
        raise ResearchWorkspaceError(
            f"invalid legacy migration manifest status: {status_value!r}"
        )
    moves = _parse_legacy_migration_entries(root, raw.get("moves"), label="moves")
    completed = _parse_legacy_migration_entries(
        root,
        raw.get("completed"),
        label="completed",
    )
    restored = _parse_legacy_migration_entries(
        root,
        raw.get("restored", []),
        label="restored",
    )
    move_set = set(moves)
    completed_set = set(completed)
    if not completed_set.issubset(move_set):
        raise ResearchWorkspaceError(
            "invalid legacy migration manifest: completed is not a subset of moves"
        )
    if not set(restored).issubset(completed_set):
        raise ResearchWorkspaceError(
            "invalid legacy migration manifest: restored is not a subset of completed"
        )
    if status_value == "complete" and completed_set != move_set:
        raise ResearchWorkspaceError(
            "invalid legacy migration manifest: complete status has pending moves"
        )
    if status_value == "restored" and set(restored) != completed_set:
        raise ResearchWorkspaceError(
            "invalid legacy migration manifest: restored status has pending moves"
        )
    return dict(raw), moves, completed, restored


def _parse_legacy_migration_entries(
    root: Path,
    value: object,
    *,
    label: str,
) -> tuple[LegacyMigration, ...]:
    if not isinstance(value, list):
        raise ResearchWorkspaceError(
            f"invalid legacy migration manifest: missing {label}"
        )
    entries: list[LegacyMigration] = []
    for raw_entry in value:
        if not isinstance(raw_entry, dict):
            raise ResearchWorkspaceError(
                f"invalid legacy migration manifest {label} entry"
            )
        source_text = raw_entry.get("source")
        destination_text = raw_entry.get("destination")
        if (
            not isinstance(source_text, str)
            or not source_text
            or not isinstance(destination_text, str)
            or not destination_text
        ):
            raise ResearchWorkspaceError(
                f"invalid legacy migration manifest {label} paths"
            )
        source = _safe_manifest_path(root, source_text)
        destination = _safe_manifest_path(root, destination_text)
        if source == destination:
            raise ResearchWorkspaceError(
                f"invalid legacy migration manifest {label}: identical paths"
            )
        entry = LegacyMigration(source, destination)
        if entry in entries:
            raise ResearchWorkspaceError(
                f"invalid legacy migration manifest: duplicate {label} entry"
            )
        entries.append(entry)
    return tuple(entries)


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _require_safe_legacy_path(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ResearchWorkspaceError(f"missing {label}: {path}") from exc
    if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
        raise ResearchWorkspaceError(f"unsafe {label}: {path}")


def _require_migrated_legacy_state(
    item: LegacyMigration,
    *,
    root: Path,
) -> None:
    if _path_present(item.source):
        raise ResearchWorkspaceError(
            "completed legacy source unexpectedly exists: "
            f"{_relative(item.source, root)}"
        )
    _require_safe_legacy_path(item.destination, label="archived legacy path")


def _require_restored_legacy_state(
    item: LegacyMigration,
    *,
    root: Path,
) -> None:
    _require_safe_legacy_path(item.source, label="restored legacy path")
    if _path_present(item.destination):
        raise ResearchWorkspaceError(
            "restored legacy archive unexpectedly exists: "
            f"{_relative(item.destination, root)}"
        )


def inspect_workspace(
    project_root: Path,
    *,
    budget: ResearchBudget | None = None,
) -> ResearchWorkspaceStatus:
    """Inspect active prose and artifacts without changing the workspace."""
    root = project_root.resolve()
    selected_budget = budget or ResearchBudget()
    research = root / "research"
    issues: list[WorkspaceIssue] = []

    current = research / "CURRENT.md"
    current_text = _read_text(current, root=root, issues=issues)
    current_chars = len(current_text or "")
    if current_chars > selected_budget.current_chars:
        issues.append(
            _limit_issue(
                "current.too_large",
                current,
                root,
                current_chars,
                selected_budget.current_chars,
            )
        )
    current_lines, current_paths, current_chronological = _current_guidance_metrics(
        current_text or ""
    )
    if current_lines > selected_budget.current_lines:
        issues.append(
            _guidance_issue(
                "current.too_many_lines",
                current,
                root,
                current_lines,
                selected_budget.current_lines,
            )
        )
    if current_paths > selected_budget.current_path_references:
        issues.append(
            _guidance_issue(
                "current.too_many_paths",
                current,
                root,
                current_paths,
                selected_budget.current_path_references,
            )
        )
    if current_chronological > selected_budget.current_chronological_headings:
        issues.append(
            _guidance_issue(
                "current.looks_chronological",
                current,
                root,
                current_chronological,
                selected_budget.current_chronological_headings,
            )
        )

    journal = research / "journal" / "active.md"
    journal_chars = _text_chars(journal, root=root, issues=issues)
    if journal_chars > selected_budget.journal_segment_chars:
        issues.append(
            _limit_issue(
                "journal.rotation_required",
                journal,
                root,
                journal_chars,
                selected_budget.journal_segment_chars,
            )
        )

    results_root = research / "results"
    result_dirs = _safe_child_directories(results_root, root=root, issues=issues)
    if len(result_dirs) > selected_budget.active_results:
        issues.append(
            _limit_issue(
                "results.too_many_active",
                results_root,
                root,
                len(result_dirs),
                selected_budget.active_results,
            )
        )

    total_result_chars = 0
    total_artifact_files = 0
    total_artifact_bytes = 0
    for result_dir in result_dirs:
        result_status = inspect_result_workspace(
            root,
            result_dir,
            budget=selected_budget,
        )
        total_result_chars += result_status.readme_chars
        total_artifact_files += result_status.artifact_files
        total_artifact_bytes += result_status.artifact_bytes
        issues.extend(result_status.issues)

    return ResearchWorkspaceStatus(
        root=root,
        current_chars=current_chars,
        current_lines=current_lines,
        current_path_references=current_paths,
        current_chronological_headings=current_chronological,
        journal_chars=journal_chars,
        active_result_count=len(result_dirs),
        result_readme_chars=total_result_chars,
        artifact_files=total_artifact_files,
        artifact_bytes=total_artifact_bytes,
        issues=tuple(issues),
        budget=selected_budget,
    )


def inspect_result_workspace(
    project_root: Path,
    result_dir: Path,
    *,
    budget: ResearchBudget | None = None,
) -> ResultWorkspaceInspection:
    """Inspect hard limits and artifact layout for one Result.

    This is the shared Result-local gate used by the project-wide workspace
    inspection and by Result check/seal operations.  It deliberately reports
    issues instead of mutating or normalizing the Result.
    """
    root = project_root.resolve()
    selected_budget = budget or ResearchBudget()
    result_path = result_dir if result_dir.is_absolute() else root / result_dir
    issues: list[WorkspaceIssue] = []

    readme = result_path / "README.md"
    readme_chars = _text_chars(readme, root=root, issues=issues)
    if readme_chars > selected_budget.result_readme_chars:
        issues.append(
            _limit_issue(
                "result.readme_too_large",
                readme,
                root,
                readme_chars,
                selected_budget.result_readme_chars,
            )
        )

    artifacts = result_path / "artifacts"
    files, byte_count = _inspect_artifacts(artifacts, root=root, issues=issues)
    if files > selected_budget.result_artifact_files:
        issues.append(
            _limit_issue(
                "artifact.too_many_files",
                artifacts,
                root,
                files,
                selected_budget.result_artifact_files,
            )
        )
    if byte_count > selected_budget.result_artifact_bytes:
        issues.append(
            _limit_issue(
                "artifact.too_large",
                artifacts,
                root,
                byte_count,
                selected_budget.result_artifact_bytes,
            )
        )

    return ResultWorkspaceInspection(
        path=result_path,
        readme_chars=readme_chars,
        artifact_files=files,
        artifact_bytes=byte_count,
        issues=tuple(issues),
    )


def append_journal(
    project_root: Path,
    *,
    title: str,
    body: str,
    kind: str | None = None,
    subject: str | None = None,
    budget: ResearchBudget | None = None,
    now: datetime | None = None,
) -> JournalAppendResult:
    """Append one entry, rotating first when the character budget is exceeded."""
    clean_title = " ".join(title.split())
    clean_body = body.strip()
    if not clean_title:
        raise ResearchWorkspaceError("journal title must not be empty")
    if not clean_body:
        raise ResearchWorkspaceError("journal body must not be empty")
    clean_kind = _optional_journal_label(kind, label="kind")
    clean_subject = _optional_journal_label(subject, label="subject")

    root = project_root.resolve()
    selected_budget = budget or ResearchBudget()
    timestamp = (now or datetime.now(tz=JST)).astimezone(JST)
    metadata = ""
    if clean_kind is not None:
        metadata += f"- Kind: `{clean_kind}`\n"
    if clean_subject is not None:
        metadata += f"- Subject: `{clean_subject}`\n"
    if metadata:
        metadata += "\n"
    entry = (
        f"## {timestamp.isoformat(timespec='seconds')} {clean_title}\n\n"
        f"{metadata}{clean_body}\n\n"
    )
    if len(_JOURNAL_HEADER) + len(entry) > selected_budget.journal_segment_chars:
        raise ResearchWorkspaceError(
            "journal entry exceeds research.workspace.journal_segment_chars"
        )

    with _research_workspace_lock(root):
        active = _ensure_journal(root)
        existing = _read_safe_regular_text(active, label="active journal")
        rotated_to: Path | None = None
        if len(existing) + len(entry) > selected_budget.journal_segment_chars:
            rotated_to = _rotate_journal_locked(
                root,
                budget=selected_budget,
                force=True,
            )
            existing = _read_safe_regular_text(active, label="active journal")

        _append_text(active, entry)
        return JournalAppendResult(
            path=active,
            chars=len(existing) + len(entry),
            rotated_to=rotated_to,
        )


def rotate_journal(
    project_root: Path,
    *,
    budget: ResearchBudget | None = None,
    force: bool = False,
) -> Path | None:
    """Rotate the active journal intact into the next sequence-numbered segment."""
    root = project_root.resolve()
    selected_budget = budget or ResearchBudget()
    with _research_workspace_lock(root):
        return _rotate_journal_locked(root, budget=selected_budget, force=force)


def _rotate_journal_locked(
    root: Path,
    *,
    budget: ResearchBudget,
    force: bool,
) -> Path | None:
    """Rotate a journal while the shared Research Workspace lock is held."""
    active = _ensure_journal(root)
    text = _read_safe_regular_text(active, label="active journal")
    if not force and len(text) <= budget.journal_segment_chars:
        return None

    archive = root / "research" / "journal" / "archive"
    _ensure_safe_directory(archive, root=root, label="journal archive")
    destination = archive / _next_journal_name(archive)
    _write_new_file(destination, text)
    _replace_text(active, _JOURNAL_HEADER)
    return destination


def create_result(
    project_root: Path,
    name: str,
    *,
    budget: ResearchBudget | None = None,
) -> ResultWorkspace:
    """Create one durable result with exactly one narrative entry point."""
    clean_name = name.strip()
    if not clean_name:
        raise ResearchWorkspaceError("result name must not be empty")
    slug = _slugify(clean_name)
    if not slug:
        raise ResearchWorkspaceError("result name must contain a letter or number")

    root = project_root.resolve()
    results_root = root / "research" / "results"
    archive_root = root / "research" / "archive" / "results"
    _ensure_safe_directory(results_root, root=root, label="results")
    _ensure_safe_directory(archive_root, root=root, label="result archive")
    with _result_allocation_lock(root):
        _enforce_active_result_capacity(
            results_root,
            (budget or ResearchBudget()).active_results,
            additional=1,
        )
        number = _next_result_number(results_root, archive_root)
        if number > 9_999:
            raise ResearchWorkspaceError("Result RNNNN sequence is exhausted")
        result_id = f"R{number:04d}-{slug}"
        result_dir = results_root / result_id
        if result_dir.exists() or result_dir.is_symlink():
            raise ResearchWorkspaceError(
                f"result destination already exists: {result_id}"
            )
        staging = Path(tempfile.mkdtemp(prefix=".tmp-result-", dir=results_root))
        try:
            (staging / "artifacts").mkdir()
            _write_new_file(
                staging / "README.md",
                (
                    f"# {clean_name}\n\n"
                    "## Question\n\n"
                    "## Result\n\n"
                    "## Evidence\n\n"
                    "## Caveats\n\n"
                    "## Reproduction\n"
                ),
            )
            _write_new_file(
                staging / "manifest.toml",
                tomli_w.dumps(
                    {
                        "result": {
                            "schema_version": 1,
                            "id": result_id,
                            "status": "draft",
                            "title": clean_name,
                            "claim": "",
                            "outcome": "",
                        }
                    }
                ),
            )
            if result_dir.exists() or result_dir.is_symlink():
                raise ResearchWorkspaceError(
                    f"result destination already exists: {result_id}"
                )
            move_path_noreplace(staging, result_dir)
        except (OSError, SimctlError) as exc:
            if staging.exists() and not staging.is_symlink():
                shutil.rmtree(staging)
            raise ResearchWorkspaceError(f"cannot create Result: {exc}") from exc
        except BaseException:
            if staging.exists() and not staging.is_symlink():
                shutil.rmtree(staging)
            raise
    return ResultWorkspace(result_id=result_id, path=result_dir)


def archive_result(project_root: Path, result_id: str) -> Path:
    """Move an active result intact to the recovery-only archive."""
    return _move_result(project_root, result_id, restore=False)


def restore_result(
    project_root: Path,
    result_id: str,
    *,
    budget: ResearchBudget | None = None,
) -> Path:
    """Restore an archived result without rewriting its contents."""
    return _move_result(project_root, result_id, restore=True, budget=budget)


def _move_result(
    project_root: Path,
    result_id: str,
    *,
    restore: bool,
    budget: ResearchBudget | None = None,
) -> Path:
    if not _RESULT_DIRECTORY.fullmatch(result_id):
        raise ResearchWorkspaceError(f"invalid result ID: {result_id}")
    root = project_root.resolve()
    results_root = root / "research" / "results"
    archive_root = root / "research" / "archive" / "results"
    _ensure_safe_directory(results_root, root=root, label="results")
    _ensure_safe_directory(archive_root, root=root, label="result archive")
    source_root, destination_root = (
        (archive_root, results_root) if restore else (results_root, archive_root)
    )
    with _result_allocation_lock(root):
        if restore:
            _enforce_active_result_capacity(
                results_root,
                (budget or ResearchBudget()).active_results,
                additional=1,
            )
        source = source_root / result_id
        destination = destination_root / result_id
        if source.is_symlink() or not source.is_dir():
            raise ResearchWorkspaceError(f"result not found: {result_id}")
        if destination.exists() or destination.is_symlink():
            raise ResearchWorkspaceError(
                f"result destination already exists: {result_id}"
            )
        try:
            move_path_noreplace(source, destination)
        except (OSError, SimctlError) as exc:
            operation = "restore" if restore else "archive"
            raise ResearchWorkspaceError(
                f"cannot {operation} Result {result_id}: {exc}"
            ) from exc
        return destination


def _enforce_active_result_capacity(
    results_root: Path,
    limit: int,
    *,
    additional: int,
) -> None:
    active = 0
    for candidate in results_root.iterdir():
        if candidate.name.startswith(".tmp-result-"):
            continue
        if candidate.is_symlink():
            raise ResearchWorkspaceError(
                f"unsafe active Result entry: {candidate.name}"
            )
        if candidate.is_dir():
            active += 1
    if active + additional > limit:
        raise ResearchWorkspaceError(
            "active Result limit reached: "
            f"{active}/{limit}; archive a Result before creating or restoring one"
        )


def _inspect_artifacts(
    artifacts: Path,
    *,
    root: Path,
    issues: list[WorkspaceIssue],
) -> tuple[int, int]:
    if not artifacts.exists():
        return 0, 0
    if artifacts.is_symlink() or not artifacts.is_dir():
        issues.append(
            WorkspaceIssue(
                "error",
                "artifact.unsafe_directory",
                _relative(artifacts, root),
                "artifacts path must be a real directory",
            )
        )
        return 0, 0

    file_count = 0
    byte_count = 0
    formats: dict[str, set[str]] = {}
    for current_root, directories, filenames in os.walk(artifacts, followlinks=False):
        current = Path(current_root)
        safe_directories: list[str] = []
        for dirname in directories:
            child = current / dirname
            if child.is_symlink():
                issues.append(
                    WorkspaceIssue(
                        "error",
                        "artifact.symlink_forbidden",
                        _relative(child, root),
                        "artifact symlinks are not allowed",
                    )
                )
            else:
                safe_directories.append(dirname)
        directories[:] = safe_directories

        for filename in filenames:
            path = current / filename
            if path.is_symlink() or not path.is_file():
                issues.append(
                    WorkspaceIssue(
                        "error",
                        "artifact.unsafe_file",
                        _relative(path, root),
                        "artifact must be a regular non-symlink file",
                    )
                )
                continue
            file_count += 1
            byte_count += path.stat().st_size
            if path.suffix.casefold() == ".md":
                issues.append(
                    WorkspaceIssue(
                        "error",
                        "artifact.markdown_forbidden",
                        _relative(path, root),
                        "human narrative belongs in the result README.md",
                    )
                )
            suffix = path.suffix.casefold()
            if suffix in _DUPLICATE_FORMATS:
                key = str(path.relative_to(artifacts).with_suffix(""))
                formats.setdefault(key, set()).add(suffix)

    for stem, suffixes in sorted(formats.items()):
        if len(suffixes) > 1:
            issues.append(
                WorkspaceIssue(
                    "warning",
                    "artifact.duplicate_formats",
                    _relative(artifacts / stem, root),
                    "one logical artifact has multiple stored formats: "
                    + ", ".join(sorted(suffixes)),
                )
            )
    return file_count, byte_count


def _safe_child_directories(
    parent: Path,
    *,
    root: Path,
    issues: list[WorkspaceIssue],
) -> list[Path]:
    if not parent.exists():
        return []
    if parent.is_symlink() or not parent.is_dir():
        issues.append(
            WorkspaceIssue(
                "error",
                "results.unsafe_directory",
                _relative(parent, root),
                "results path must be a real directory",
            )
        )
        return []
    result: list[Path] = []
    for child in sorted(parent.iterdir()):
        if child.is_symlink():
            issues.append(
                WorkspaceIssue(
                    "error",
                    "result.symlink_forbidden",
                    _relative(child, root),
                    "result symlinks are not allowed",
                )
            )
        elif child.is_dir():
            result.append(child)
    return result


def _text_chars(
    path: Path,
    *,
    root: Path,
    issues: list[WorkspaceIssue],
) -> int:
    text = _read_text(path, root=root, issues=issues)
    return len(text) if text is not None else 0


def _read_text(
    path: Path,
    *,
    root: Path,
    issues: list[WorkspaceIssue],
) -> str | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        issues.append(
            WorkspaceIssue(
                "error",
                "narrative.unsafe_file",
                _relative(path, root),
                "narrative must be a regular non-symlink file",
            )
        )
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        issues.append(
            WorkspaceIssue(
                "error",
                "narrative.unreadable",
                _relative(path, root),
                f"cannot read UTF-8 narrative: {exc}",
            )
        )
        return None


def _current_guidance_metrics(text: str) -> tuple[int, int, int]:
    lines = len(text.splitlines())
    paths = sum(1 for token in _path_candidates(text) if _looks_like_local_path(token))
    chronological = len(_CHRONOLOGICAL_HEADING.findall(text))
    return lines, paths, chronological


def _path_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for raw in text.split():
        token = raw.strip("`*_[]{}<>,;:'\"")
        if "](" in token:
            token = token.rsplit("](", maxsplit=1)[1]
        token = token.strip("`*_[](){}<>,;:'\".")
        if token:
            candidates.append(token)
    return candidates


def _looks_like_local_path(token: str) -> bool:
    lowered = token.casefold()
    if lowered.startswith(("http://", "https://", "mailto:")):
        return False
    if token in {"/", "//"} or "/" not in token:
        return False
    return token.startswith(_PATH_PREFIXES) or bool(Path(token).suffix)


def _limit_issue(
    code: str,
    path: Path,
    root: Path,
    actual: int,
    limit: int,
) -> WorkspaceIssue:
    return WorkspaceIssue(
        "error",
        code,
        _relative(path, root),
        f"quantity {actual} exceeds configured limit {limit}",
    )


def _guidance_issue(
    code: str,
    path: Path,
    root: Path,
    actual: int,
    limit: int,
) -> WorkspaceIssue:
    return WorkspaceIssue(
        "warning",
        code,
        _relative(path, root),
        f"guidance quantity {actual} exceeds configured target {limit}",
    )


def _ensure_journal(root: Path) -> Path:
    journal_root = root / "research" / "journal"
    archive = journal_root / "archive"
    _ensure_safe_directory(journal_root, root=root, label="journal")
    _ensure_safe_directory(archive, root=root, label="journal archive")
    active = journal_root / "active.md"
    if not active.exists():
        _write_new_file(active, _JOURNAL_HEADER)
    return active


def _ensure_safe_directory(path: Path, *, root: Path, label: str) -> None:
    """Create a project-local directory without following ancestor symlinks."""
    canonical_root = root.resolve()
    try:
        relative = path.relative_to(canonical_root)
    except ValueError as exc:
        raise ResearchWorkspaceError(
            f"unsafe {label} directory outside project: {path}"
        ) from exc
    current = canonical_root
    for component in relative.parts:
        current = current / component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            try:
                current.mkdir()
            except FileExistsError:
                pass
            except OSError as exc:
                raise ResearchWorkspaceError(
                    f"cannot create {label} directory {current}: {exc}"
                ) from exc
            try:
                metadata = current.lstat()
            except OSError as exc:
                raise ResearchWorkspaceError(
                    f"cannot inspect {label} directory {current}: {exc}"
                ) from exc
        except OSError as exc:
            raise ResearchWorkspaceError(
                f"cannot inspect {label} directory {current}: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ResearchWorkspaceError(f"unsafe {label} directory: {current}")


def _read_safe_regular_text(path: Path, *, label: str) -> str:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ResearchWorkspaceError(f"missing {label}: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ResearchWorkspaceError(f"unsafe {label}: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ResearchWorkspaceError(f"cannot read {label}: {exc}") from exc


def _append_text(path: Path, text: str) -> None:
    try:
        with path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise ResearchWorkspaceError(f"cannot append journal: {exc}") from exc


def _replace_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        _write_new_file(temporary, text)
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ResearchWorkspaceError(f"cannot reset active journal: {exc}") from exc


def _write_new_file(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o664)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ResearchWorkspaceError(f"refusing to overwrite: {path}") from exc
    except OSError as exc:
        raise ResearchWorkspaceError(f"cannot write {path}: {exc}") from exc


def _write_json_replace(path: Path, payload: object) -> None:
    """Atomically replace a small recovery manifest in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    try:
        _write_new_file(
            temporary,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
        temporary.replace(path)
        _fsync_directory(path.parent)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ResearchWorkspaceError(f"cannot update {path}: {exc}") from exc


def _write_json_new(path: Path, payload: object) -> None:
    """Create a recovery manifest without replacing a competing writer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_new_file(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    _fsync_directory(path.parent)


def _safe_manifest_path(root: Path, relative: str) -> Path:
    path = root / relative
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ResearchWorkspaceError(
            f"migration manifest path escapes project: {relative}"
        ) from exc
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ResearchWorkspaceError(f"unsafe migration manifest path: {relative}")
    return path


def _next_journal_name(archive: Path) -> str:
    numbers = []
    for path in archive.glob("J[0-9][0-9][0-9][0-9].md"):
        try:
            numbers.append(int(path.stem[1:]))
        except ValueError:
            continue
    return f"J{max(numbers, default=0) + 1:04d}.md"


def _next_result_number(*roots: Path) -> int:
    numbers: list[int] = []
    for root in roots:
        for path in root.iterdir():
            match = _RESULT_ID.match(path.name)
            if match is not None:
                numbers.append(int(match.group("number")))
    return max(numbers, default=0) + 1


@contextmanager
def _research_workspace_lock(root: Path) -> Iterator[None]:
    """Serialize journal and legacy migration mutations across processes."""
    try:
        runops_root = require_project_state_root(root)
    except SimctlError as exc:
        raise ResearchWorkspaceError(str(exc)) from exc
    locks_root = runops_root / "locks"
    _ensure_safe_directory(locks_root, root=root, label="research locks")
    lock_path = locks_root / "research-workspace.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o664)
    except OSError as exc:
        raise ResearchWorkspaceError(
            f"cannot open Research Workspace lock: {exc}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ResearchWorkspaceError("unsafe Research Workspace lock file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise ResearchWorkspaceError(
                f"cannot lock Research Workspace: {exc}"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


@contextmanager
def _result_allocation_lock(root: Path) -> Iterator[None]:
    """Serialize Result ID allocation across active and archived workspaces.

    ``create_comparison_workspace`` still has a legacy allocator.  It should be
    migrated to this lock/staging protocol when that experimental surface is
    folded into canonical Results; changing its manifest here would break the
    supported legacy ``[comparison]`` reader.
    """
    # TODO(result-allocator): route create_comparison_workspace through this
    # allocator without rewriting its supported legacy [comparison] manifest.
    try:
        runops_root = require_project_state_root(root)
    except SimctlError as exc:
        raise ResearchWorkspaceError(str(exc)) from exc
    locks_root = runops_root / "locks"
    _ensure_safe_directory(locks_root, root=root, label="result locks")
    lock_path = locks_root / "research-results.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o664)
    except OSError as exc:
        raise ResearchWorkspaceError(
            f"cannot open Result allocator lock: {exc}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ResearchWorkspaceError("unsafe Result allocator lock file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:64].rstrip("-")


def _optional_journal_label(value: str | None, *, label: str) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        raise ResearchWorkspaceError(f"journal {label} must not be empty")
    if any(character in cleaned for character in ("\n", "\r", "`")):
        raise ResearchWorkspaceError(
            f"journal {label} must be a single line without backticks"
        )
    return cleaned


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)
