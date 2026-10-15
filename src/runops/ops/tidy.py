"""``tidy``, ``archive``, ``restore``, ``delete``, purge-work (SPEC §7.5)."""

from __future__ import annotations

import fnmatch
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from runops.adapters.registry import optional
from runops.errors import RunopsError, UsageError
from runops.manifest import ACTIVE_STATES, MANIFEST_FILE, Manifest, RunState
from runops.ops.common import inside, run_sim_context
from runops.ops.sync import sync_run
from runops.project import ARCHIVE_DIR, Project
from runops.slurm import CommandRunner, default_runner, query
from runops.util import move_noreplace, now_iso, parse_iso

KINDS = (
    "expired-scratch",
    "stale-failed",
    "old-completed",
    "orphan-job",
    "unused-build",
)


@dataclass
class Candidate:
    kind: str
    target: str  # run id or build dir
    path: str
    reason: str


@dataclass
class TidyReport:
    candidates: list[Candidate] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def find_candidates(
    project: Project,
    *,
    older_than: timedelta,
    now: datetime | None = None,
    runner: CommandRunner = default_runner,
    check_slurm: bool = True,
) -> list[Candidate]:
    now = now or datetime.now().astimezone()
    out: list[Candidate] = []
    referenced: set[str] = set()
    for m in project.iter_runs():
        build_dir = str(m.section("simulator").get("build_dir", ""))
        if build_dir and m.status != RunState.ARCHIVED:
            referenced.add(Path(build_dir).name)
        created = m.created_datetime()
        age = now - created if created else timedelta(0)
        rel = project.rel(m.run_dir)
        if m.scratch and not m.pinned and m.status not in ACTIVE_STATES:
            expires = parse_iso(str(m.run.get("expires_at", "")))
            if expires is not None and expires <= now:
                out.append(Candidate("expired-scratch", m.id, rel, f"expired {expires:%Y-%m-%d}"))
                continue
        if (
            m.status in (RunState.FAILED, RunState.CANCELLED)
            and not m.pinned
            and age > older_than
            and not m.why
            and not m.notes
            and not (m.run_dir / "notes.md").exists()
        ):
            out.append(
                Candidate(
                    "stale-failed",
                    m.id,
                    rel,
                    f"{m.status.value}, {age.days}d old, no why/notes",
                )
            )
        elif m.status == RunState.COMPLETED and not m.pinned and age > older_than * 3:
            out.append(Candidate("old-completed", m.id, rel, f"completed, {age.days}d old"))
        elif m.status in ACTIVE_STATES and check_slurm and m.job_id:
            try:
                state = query(m.job_id, runner=runner)
            except RunopsError:
                state = None
                continue
            if state is None:
                out.append(Candidate("orphan-job", m.id, rel, f"job {m.job_id} unknown to Slurm"))
    if project.build_dir.is_dir():
        for build in sorted(project.build_dir.iterdir()):
            if build.is_dir() and not build.name.startswith(".") and build.name not in referenced:
                out.append(
                    Candidate(
                        "unused-build",
                        build.name,
                        project.rel(build),
                        "no non-archived run uses it",
                    )
                )
    return out


def apply_candidates(
    project: Project,
    candidates: list[Candidate],
    *,
    runner: CommandRunner = default_runner,
) -> TidyReport:
    report = TidyReport(candidates=list(candidates))
    for c in candidates:
        try:
            if c.kind == "unused-build":
                shutil.rmtree(project.build_dir / c.target)
            else:
                manifest = project.resolve_run(c.target)
                if c.kind in ("expired-scratch", "stale-failed"):
                    delete_run(project, manifest)
                elif c.kind == "old-completed":
                    archive_run(project, manifest)
                elif c.kind == "orphan-job":
                    sync_run(project, manifest, runner=runner)
            report.applied.append(f"{c.kind}: {c.target}")
        except (RunopsError, OSError) as exc:
            report.errors.append(f"{c.kind}: {c.target}: {exc}")
            break
    return report


# ---- archive / restore / delete --------------------------------------


def archive_run(project: Project, manifest: Manifest) -> Path:
    status = manifest.status
    if status not in (RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED):
        raise UsageError(f"{manifest.id} is {status.value}; only terminal runs can be archived")
    src = manifest.run_dir.resolve()
    archive_root = project.runs_dir / ARCHIVE_DIR
    if inside(src, archive_root):
        raise UsageError(f"{manifest.id} is already under runs/{ARCHIVE_DIR}")
    rel = (
        src.relative_to(project.runs_dir.resolve())
        if inside(src, project.runs_dir)
        else Path(src.name)
    )
    dst = archive_root / rel
    if dst.exists():
        raise UsageError(f"{dst} already exists")
    move_noreplace(src, dst)
    moved = Manifest.load(dst / MANIFEST_FILE)
    moved.run["status_before_archive"] = status.value
    moved.section("path").update(
        {
            "run_dir": project.rel(dst),
            "archived_from": project.rel(src),
            "archived_at": now_iso(),
        }
    )
    moved.set_status(RunState.ARCHIVED)
    moved.save()
    project.update_index(moved.id, dst)
    _prune_empty(src.parent, project.runs_dir)
    return dst


def restore_run(project: Project, manifest: Manifest) -> Path:
    if manifest.status != RunState.ARCHIVED:
        raise UsageError(f"{manifest.id} is {manifest.status.value}, not archived")
    archived_from = str(manifest.section("path").get("archived_from", ""))
    if not archived_from:
        raise UsageError(f"{manifest.id}: [path].archived_from is empty; move it manually")
    dst = project.root / archived_from
    if dst.exists():
        raise UsageError(f"cannot restore {manifest.id}: {dst} already exists")
    src = manifest.run_dir.resolve()
    move_noreplace(src, dst)
    moved = Manifest.load(dst / MANIFEST_FILE)
    previous = RunState(str(moved.run.pop("status_before_archive", "completed")))
    moved.set_status(previous)
    moved.section("path").update(
        {"run_dir": project.rel(dst), "archived_from": "", "archived_at": ""}
    )
    moved.save()
    project.update_index(moved.id, dst)
    _prune_empty(src.parent, project.runs_dir / ARCHIVE_DIR)
    return dst


def check_deletable(manifest: Manifest) -> None:
    if manifest.pinned:
        raise UsageError(f"{manifest.id} is pinned; refusing to delete")
    status = manifest.status
    if status in ACTIVE_STATES:
        raise UsageError(f"{manifest.id} is {status.value}; cancel it first")
    allowed = {RunState.CREATED, RunState.FAILED, RunState.CANCELLED}
    if not manifest.scratch and status not in allowed:
        raise UsageError(
            f"{manifest.id} is {status.value}; only created/failed/cancelled or scratch "
            "runs can be deleted (archive completed runs instead)"
        )


def delete_run(project: Project, manifest: Manifest) -> None:
    check_deletable(manifest)
    run_dir = manifest.run_dir.resolve()
    if not inside(run_dir, project.runs_dir):
        raise UsageError(f"{run_dir} is outside runs/; refusing to delete")
    shutil.rmtree(run_dir)
    project.update_index(manifest.id, None)
    _prune_empty(run_dir.parent, project.runs_dir)


def purge_work(project: Project, manifest: Manifest) -> list[str]:
    if manifest.status != RunState.COMPLETED:
        raise UsageError(f"{manifest.id} is {manifest.status.value}; purge-work needs completed")
    try:
        keep = list(optional(run_sim_context(project, manifest).adapter, "keep_patterns", []) or [])
    except RunopsError:
        keep = []
    work = manifest.run_dir / "work"
    removed: list[str] = []
    if work.is_dir():
        for path in sorted(work.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            rel = path.relative_to(work).as_posix()
            if path.is_file() or path.is_symlink():
                if any(
                    fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(path.name, pat) for pat in keep
                ):
                    continue
                path.unlink()
                removed.append(rel)
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    manifest.section("storage")["work_purged_at"] = now_iso()
    manifest.save()
    return removed


def _prune_empty(directory: Path, stop: Path) -> None:
    stop = stop.resolve()
    current = directory.resolve()
    while current != stop and inside(current, stop):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
