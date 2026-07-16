"""Application services for the minimal research workspace."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from runops.core.research.workspace import ResearchBudget

JST = timezone(timedelta(hours=9), name="JST")
_JOURNAL_HEADER = "# Research Journal\n\n"
_RESULT_ID = re.compile(r"^R(?P<number>\d{4})-")
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
        (root / "_handoff", legacy_root / "_handoff"),
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
    planned = plan_legacy_migration(root)
    if not planned:
        return ()
    legacy_root = root / "research" / "archive" / "legacy"
    _ensure_safe_directory(legacy_root, label="legacy archive")
    manifest = legacy_root / "MIGRATION.json"
    if manifest.exists() or manifest.is_symlink():
        raise ResearchWorkspaceError(
            "legacy migration manifest already exists; "
            "restore it before migrating again"
        )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "moving",
        "moves": [item.to_dict(root) for item in planned],
        "completed": [],
    }
    _write_json_replace(manifest, payload)
    try:
        for item in planned:
            item.destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item.source), str(item.destination))
            payload["completed"].append(item.to_dict(root))
            _write_json_replace(manifest, payload)
    except (OSError, shutil.Error) as exc:
        raise ResearchWorkspaceError(
            f"legacy migration stopped; use MIGRATION.json for recovery: {exc}"
        ) from exc
    payload["status"] = "complete"
    _write_json_replace(manifest, payload)
    return planned


def restore_legacy_workspace(project_root: Path) -> tuple[LegacyMigration, ...]:
    """Restore every completed legacy relocation and retain no hidden deletion."""
    root = project_root.resolve()
    manifest = root / "research" / "archive" / "legacy" / "MIGRATION.json"
    try:
        raw = json.loads(_read_safe_regular_text(manifest, label="migration manifest"))
    except json.JSONDecodeError as exc:
        raise ResearchWorkspaceError(
            f"invalid legacy migration manifest: {exc}"
        ) from exc
    completed = raw.get("completed") if isinstance(raw, dict) else None
    if not isinstance(completed, list):
        raise ResearchWorkspaceError(
            "invalid legacy migration manifest: missing completed"
        )
    moves: list[LegacyMigration] = []
    for entry in completed:
        if not isinstance(entry, dict):
            raise ResearchWorkspaceError("invalid legacy migration manifest entry")
        source_text = entry.get("source")
        destination_text = entry.get("destination")
        if not isinstance(source_text, str) or not isinstance(destination_text, str):
            raise ResearchWorkspaceError("invalid legacy migration manifest paths")
        source = _safe_manifest_path(root, source_text)
        destination = _safe_manifest_path(root, destination_text)
        if source.exists() or source.is_symlink():
            raise ResearchWorkspaceError(
                f"restore destination already exists: {_relative(source, root)}"
            )
        if destination.is_symlink() or not destination.exists():
            raise ResearchWorkspaceError(
                "archived legacy path is missing or unsafe: "
                f"{_relative(destination, root)}"
            )
        moves.append(LegacyMigration(source, destination))

    for item in reversed(moves):
        item.source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item.destination), str(item.source))
    manifest.unlink()
    return tuple(moves)


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
        readme = result_dir / "README.md"
        readme_chars = _text_chars(readme, root=root, issues=issues)
        total_result_chars += readme_chars
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

        artifacts = result_dir / "artifacts"
        files, byte_count = _inspect_artifacts(artifacts, root=root, issues=issues)
        total_artifact_files += files
        total_artifact_bytes += byte_count
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


def append_journal(
    project_root: Path,
    *,
    title: str,
    body: str,
    budget: ResearchBudget | None = None,
    now: datetime | None = None,
) -> JournalAppendResult:
    """Append one entry, rotating first when the character budget is exceeded."""
    clean_title = title.strip()
    clean_body = body.strip()
    if not clean_title:
        raise ResearchWorkspaceError("journal title must not be empty")
    if not clean_body:
        raise ResearchWorkspaceError("journal body must not be empty")

    root = project_root.resolve()
    selected_budget = budget or ResearchBudget()
    active = _ensure_journal(root)
    timestamp = (now or datetime.now(tz=JST)).astimezone(JST)
    entry = f"## {timestamp:%H:%M} {clean_title}\n\n{clean_body}\n\n"
    if len(_JOURNAL_HEADER) + len(entry) > selected_budget.journal_segment_chars:
        raise ResearchWorkspaceError(
            "journal entry exceeds research.workspace.journal_segment_chars"
        )

    existing = _read_safe_regular_text(active, label="active journal")
    rotated_to: Path | None = None
    if len(existing) + len(entry) > selected_budget.journal_segment_chars:
        rotated_to = rotate_journal(root, budget=selected_budget, force=True)
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
    active = _ensure_journal(root)
    text = _read_safe_regular_text(active, label="active journal")
    if not force and len(text) <= selected_budget.journal_segment_chars:
        return None

    archive = root / "research" / "journal" / "archive"
    _ensure_safe_directory(archive, label="journal archive")
    destination = archive / _next_journal_name(archive)
    _write_new_file(destination, text)
    _replace_text(active, _JOURNAL_HEADER)
    return destination


def create_result(project_root: Path, name: str) -> ResultWorkspace:
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
    _ensure_safe_directory(results_root, label="results")
    _ensure_safe_directory(archive_root, label="result archive")
    number = _next_result_number(results_root, archive_root)
    result_id = f"R{number:04d}-{slug}"
    result_dir = results_root / result_id
    result_dir.mkdir()
    try:
        (result_dir / "artifacts").mkdir()
        _write_new_file(
            result_dir / "README.md",
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
            result_dir / "manifest.toml",
            (
                "schema_version = 1\n"
                f'id = "{result_id}"\n'
                f'title = "{_toml_escape(clean_name)}"\n'
                'status = "active"\n'
            ),
        )
    except Exception:
        _remove_empty_result(result_dir)
        raise
    return ResultWorkspace(result_id=result_id, path=result_dir)


def archive_result(project_root: Path, result_id: str) -> Path:
    """Move an active result intact to the recovery-only archive."""
    return _move_result(project_root, result_id, restore=False)


def restore_result(project_root: Path, result_id: str) -> Path:
    """Restore an archived result without rewriting its contents."""
    return _move_result(project_root, result_id, restore=True)


def _move_result(project_root: Path, result_id: str, *, restore: bool) -> Path:
    root = project_root.resolve()
    results_root = root / "research" / "results"
    archive_root = root / "research" / "archive" / "results"
    _ensure_safe_directory(results_root, label="results")
    _ensure_safe_directory(archive_root, label="result archive")
    source_root, destination_root = (
        (archive_root, results_root) if restore else (results_root, archive_root)
    )
    source = source_root / result_id
    destination = destination_root / result_id
    if source.is_symlink() or not source.is_dir():
        raise ResearchWorkspaceError(f"result not found: {result_id}")
    if destination.exists() or destination.is_symlink():
        raise ResearchWorkspaceError(f"result destination already exists: {result_id}")
    source.rename(destination)
    return destination


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
    _ensure_safe_directory(journal_root, label="journal")
    _ensure_safe_directory(archive, label="journal archive")
    active = journal_root / "active.md"
    if not active.exists():
        _write_new_file(active, _JOURNAL_HEADER)
    return active


def _ensure_safe_directory(path: Path, *, label: str) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_dir():
            raise ResearchWorkspaceError(f"unsafe {label} directory: {path}")
        return
    path.mkdir(parents=True)


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
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ResearchWorkspaceError(f"cannot update {path}: {exc}") from exc


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


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:64].rstrip("-")


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _remove_empty_result(result_dir: Path) -> None:
    for child in sorted(result_dir.glob("**/*"), reverse=True):
        if child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            child.rmdir()
    result_dir.rmdir()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)
