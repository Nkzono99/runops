"""``tidy``, ``archive``, ``restore``, ``delete``, purge-work (SPEC §7.5)."""

from __future__ import annotations

import fnmatch
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from runops.adapters.registry import optional
from runops.case import slugify
from runops.errors import RunError, RunopsError, UsageError
from runops.manifest import ACTIVE_STATES, MANIFEST_FILE, Manifest, RunState
from runops.ops.analysis import group_analysis_dirs, log_directories, old_log_pairs, plain_path
from runops.ops.common import inside, resolve_dest, run_sim_context
from runops.ops.submit import write_job_for
from runops.ops.sync import sync_run
from runops.project import ARCHIVE_DIR, Project
from runops.slurm import CommandRunner, JobState, default_runner, query_many
from runops.util import move_noreplace, now_iso, parse_iso

KINDS = (
    "expired-scratch",
    "stale-failed",
    "old-completed",
    "orphan-job",
    "unused-build",
    "analysis-logs",
)


@dataclass
class Candidate:
    kind: str
    target: str  # run id, build dir, or analysis job-name/id
    path: str
    reason: str
    files: list[str] = field(default_factory=list)  # analysis log pair, project-relative
    cutoff: str = ""  # preserve --older-than for apply-time revalidation


@dataclass
class TidyReport:
    candidates: list[Candidate] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def find_candidates(
    project: Project,
    *,
    failed_after: timedelta | None = None,
    archive_after: timedelta | None = None,
    now: datetime | None = None,
    runner: CommandRunner = default_runner,
    check_slurm: bool = True,
) -> list[Candidate]:
    now = now or datetime.now().astimezone()
    defaults = project.config.defaults
    if failed_after is None:
        failed_after = timedelta(days=defaults.tidy_failed_days)
    if archive_after is None:
        archive_after = timedelta(days=defaults.tidy_archive_days)
    out: list[Candidate] = []
    referenced: set[str] = set()
    runs = list(project.iter_runs())
    known: dict[str, JobState | None] = {}
    if check_slurm:
        try:
            known = query_many(
                [m.job_id for m in runs if m.status in ACTIVE_STATES and m.job_id], runner=runner
            )
        except RunopsError:
            check_slurm = False
    for m in runs:
        build_dir = str(m.section("simulator").get("build_dir", ""))
        if build_dir and m.status != RunState.ARCHIVED:
            referenced.add(Path(build_dir).name)
        created = m.created_datetime()
        age = now - created if created else timedelta(0)
        rel = project.rel(m.run_dir)
        # An archived scratch run was kept on purpose; archiving ends its expiry.
        if (
            m.scratch
            and not m.pinned
            and m.status not in ACTIVE_STATES
            and m.status != RunState.ARCHIVED
        ):
            expires = parse_iso(str(m.run.get("expires_at", "")))
            if expires is not None and expires <= now:
                out.append(Candidate("expired-scratch", m.id, rel, f"expired {expires:%Y-%m-%d}"))
                continue
        if (
            m.status in (RunState.FAILED, RunState.CANCELLED)
            and not m.pinned
            and age > failed_after
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
        elif m.status == RunState.COMPLETED and not m.pinned and age > archive_after:
            out.append(Candidate("old-completed", m.id, rel, f"completed, {age.days}d old"))
        elif m.status in ACTIVE_STATES and check_slurm and m.job_id and known.get(m.job_id) is None:
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
    cutoff = now - failed_after
    analysis_candidates: list[Candidate] = []
    for directory in log_directories(project, runs):
        for job, files in old_log_pairs(directory, cutoff).items():
            analysis_candidates.append(
                Candidate(
                    "analysis-logs",
                    job,
                    project.rel(directory),
                    f"older than {failed_after.days}d; newer logs for this job name exist",
                    [project.rel(p) for p in files],
                    cutoff.isoformat(),
                )
            )
    # Logs must be handled before a containing run is moved or deleted by this tidy.
    return analysis_candidates + out


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
            elif c.kind == "analysis-logs":
                _delete_analysis_logs(project, c)
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


def _delete_analysis_logs(project: Project, candidate: Candidate) -> None:
    with project.run_lock():
        directory = project.root / candidate.path
        cutoff = parse_iso(candidate.cutoff)
        allowed = set(log_directories(project, list(project.iter_runs())))
        if cutoff is None or directory not in allowed or not plain_path(directory, project.root):
            raise UsageError("analysis log directory is no longer eligible; run tidy again")
        files = old_log_pairs(directory, cutoff).get(candidate.target, [])
        if not files or {project.rel(p) for p in files} != set(candidate.files):
            raise UsageError("analysis logs changed or are now protected; run tidy again")
        for path in files:
            path.unlink()


# ---- archive / restore / delete --------------------------------------


_TERMINAL = (RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED)
# A created run has no job, so it can be archived too (a draft replaced before submit).
_ARCHIVABLE = (*_TERMINAL, RunState.CREATED)


@dataclass
class ArchivePlan:
    targets: list[Manifest] = field(default_factory=list)
    skipped: list[tuple[Manifest, str]] = field(default_factory=list)
    superseded_by: dict[str, list[str]] = field(default_factory=dict)  # old id -> new ids
    analysis_dirs: list[Path] = field(default_factory=list)


def plan_archive(project: Project, refs: list[str], *, superseded_by: str = "") -> ArchivePlan:
    """Check every target before anything moves.

    A RUN that cannot be archived is an error. A directory (a series) stands for the
    runs below it; its submitted/running and pinned runs are skipped and listed, and so
    are its created runs unless *superseded_by* says the series was replaced.
    With *superseded_by* (a RUN or a series directory), each old run records the
    replacement runs derived from it (``origin.parent_run``), or all of them when none is.
    """
    if not refs:
        raise UsageError("give at least one RUN or directory")
    explicit: dict[str, Manifest] = {}
    expanded: dict[str, Manifest] = {}
    directories: set[Path] = set()
    for ref in refs:
        runs, is_dir = project.resolve_runs(ref)
        if is_dir:
            directories.add(project.runs_subdir(ref))
        for m in runs:
            (expanded if is_dir else explicit)[m.id] = m
    plan = ArchivePlan()
    for run_id, m in {**expanded, **explicit}.items():
        if inside(m.run_dir, project.runs_dir / ARCHIVE_DIR):
            reason = "already archived"
        elif m.status not in _ARCHIVABLE:
            reason = m.status.value
        elif m.status == RunState.CREATED and run_id not in explicit and not superseded_by:
            reason = "created (name it, or give --superseded-by)"
        elif m.pinned and run_id not in explicit:
            reason = "pinned"
        else:
            plan.targets.append(m)
            continue
        if run_id in explicit:
            raise UsageError(f"{run_id} is {reason}; only created or finished runs can be archived")
        plan.skipped.append((m, reason))
    if superseded_by:
        new, _ = project.resolve_runs(superseded_by)
        old_ids = {m.id for m in plan.targets} | {m.id for m, _ in plan.skipped}
        if old_ids & {m.id for m in new}:
            raise UsageError("--superseded-by must not include the runs being archived")
        for m in plan.targets:
            derived = [r.id for r in new if r.parent_run == m.id]
            plan.superseded_by[m.id] = derived or [r.id for r in new]
    target_ids = {m.id for m in plan.targets}
    analyses = {a for d in directories for a in group_analysis_dirs(project, d)}
    for analysis in sorted(analyses):
        members = [
            m
            for m in project.iter_runs(analysis.parent)
            if not inside(m.run_dir, project.runs_dir / ARCHIVE_DIR)
        ]
        if members and all(m.id in target_ids for m in members):
            plan.analysis_dirs.append(analysis)
    return plan


def archive_run(
    project: Project,
    manifest: Manifest,
    *,
    superseded_by: list[str] | None = None,
    why: str = "",
    by: str = "",
) -> Path:
    """Move a terminal run to ``runs/_archive/``; record replacements and *why* if given."""
    with project.run_lock():
        manifest.reload()
        dst = _archive_dst(project, manifest)
        return _archive_locked(project, manifest, dst, superseded_by or [], why, by)


def archive_runs(
    project: Project,
    manifests: list[Manifest],
    *,
    superseded_by: dict[str, list[str]] | None = None,
    why: str = "",
    by: str = "",
    analysis_dirs: list[Path] | None = None,
) -> list[tuple[str, Path]]:
    """Archive several runs: all are checked under one ``run.lock`` before any moves."""
    replacements = superseded_by or {}
    done: list[tuple[str, Path]] = []
    with project.run_lock(), project.id_lock():
        for m in manifests:
            m.reload()
        dsts = [_archive_dst(project, m) for m in manifests]
        analyses = analysis_dirs or []
        analysis_dsts = [_analysis_archive_dst(project, a, manifests) for a in analyses]
        for m, dst in zip(manifests, dsts, strict=True):
            try:
                _archive_locked(project, m, dst, replacements.get(m.id, []), why, by)
            except (RunopsError, OSError) as exc:
                moved = ", ".join(run_id for run_id, _ in done)
                tail = f" (already archived: {moved})" if moved else ""
                raise RunError(f"{m.id}: {exc}{tail}") from exc
            done.append((m.id, dst))
        for src, dst in zip(analyses, analysis_dsts, strict=True):
            try:
                move_noreplace(src, dst)
            except (RunopsError, OSError) as exc:
                moved = ", ".join(run_id for run_id, _ in done)
                raise RunError(f"{project.rel(src)}: {exc} (already archived: {moved})") from exc
            _prune_empty(src.parent, project.runs_dir)
    return done


def _analysis_archive_dst(project: Project, src: Path, manifests: list[Manifest]) -> Path:
    if src not in set(group_analysis_dirs(project)):
        raise UsageError(f"{src} is no longer a group analysis directory; plan archive again")
    target_ids = {m.id for m in manifests}
    if any(
        m.id not in target_ids
        for m in project.iter_runs(src.parent)
        if not inside(m.run_dir, project.runs_dir / ARCHIVE_DIR)
    ):
        raise UsageError(f"{project.rel(src.parent)} still has runs; plan archive again")
    dst = project.runs_dir / ARCHIVE_DIR / src.relative_to(project.runs_dir)
    if dst.exists() or not plain_path(dst, project.root):
        raise UsageError(f"{dst} already exists or has a symlink component")
    if any(p.exists() and not p.is_dir() for p in dst.parents):
        raise UsageError(f"{dst} has a parent that is not a directory")
    return dst


def _archive_dst(project: Project, manifest: Manifest) -> Path:
    status = manifest.status
    if status not in _ARCHIVABLE:
        raise UsageError(
            f"{manifest.id} is {status.value}; only created or finished runs can be archived"
        )
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
    return dst


def _archive_locked(
    project: Project,
    manifest: Manifest,
    dst: Path,
    superseded_by: list[str],
    why: str,
    by: str,
) -> Path:
    status = manifest.status
    src = manifest.run_dir.resolve()
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
    if superseded_by:
        moved.run["superseded_by"] = list(superseded_by)
        text = f"superseded by {', '.join(superseded_by)}"
        moved.add_note(f"{text}: {why}" if why else text, by or "runops")
    elif why:
        moved.add_note(f"archived: {why}", by or "runops")
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


@dataclass
class MoveResult:
    run_id: str
    src: Path
    dst: Path
    warnings: list[str] = field(default_factory=list)


_MOVABLE = (RunState.CREATED, RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED)


@dataclass
class _MovePlan:
    manifest: Manifest
    status: RunState
    src: Path
    dst: Path
    label: str


def move_runs(
    project: Project,
    manifests: list[Manifest],
    *,
    dest: str = "",
    label: str | None = None,
    why: str = "",
    by: str = "",
) -> list[MoveResult]:
    """Rename and/or move runs under ``runs/``, keeping their ids, inputs and history.

    Every run is checked under one ``run.lock`` before any directory moves, so a
    refused run leaves all of them where they were. Submitted/running runs are refused
    (Slurm holds absolute paths into the run directory); archived runs move with
    ``restore``. The old path and *why* are appended to each run's notes; a created run
    gets a fresh ``job.sh``.
    """
    results: list[MoveResult] = []
    with project.run_lock():
        plans = [_plan_move(project, m, dest, label) for m in manifests]
        taken: dict[Path, str] = {}
        for plan in plans:
            other = taken.setdefault(plan.dst.resolve(), plan.manifest.id)
            if other != plan.manifest.id:
                raise UsageError(
                    f"{other} and {plan.manifest.id} would both move to {project.rel(plan.dst)}"
                )
        for plan in plans:
            try:
                results.append(_apply_move(project, plan, why, by))
            except (RunopsError, OSError) as exc:
                done = ", ".join(r.run_id for r in results)
                moved = f" (already moved: {done})" if done else ""
                raise RunError(f"{plan.manifest.id}: {exc}{moved}") from exc
            finally:
                _prune_empty(plan.src.parent, project.runs_dir)
    return results


def _plan_move(project: Project, manifest: Manifest, dest: str, label: str | None) -> _MovePlan:
    manifest.reload()
    status = manifest.status
    if status not in _MOVABLE:
        hint = "restore it first" if status == RunState.ARCHIVED else "wait or cancel it"
        raise UsageError(f"{manifest.id} is {status.value}; {hint}")
    src = manifest.run_dir.resolve()
    parent = resolve_dest(project, dest) if dest else src.parent
    if inside(parent, src):
        raise UsageError(f"--dest must not be inside {manifest.id} itself")
    new_label = (
        manifest.label
        if label is None
        else slugify(label, project.config.defaults.label_max_length)
    )
    if label and not new_label:
        raise UsageError(f"--label {label!r} has no usable characters")
    name = f"{manifest.id}--{new_label}" if new_label else manifest.id
    dst = parent / name
    if dst.resolve() == src:
        raise UsageError(f"{manifest.id} is already at {project.rel(src)}")
    if dst.exists():
        raise UsageError(f"{project.rel(dst)} already exists")
    return _MovePlan(manifest, status, src, dst, new_label)


def _apply_move(project: Project, plan: _MovePlan, why: str, by: str) -> MoveResult:
    plan.dst.parent.mkdir(parents=True, exist_ok=True)
    move_noreplace(plan.src, plan.dst)
    moved = Manifest.load(plan.dst / MANIFEST_FILE)
    moved.run["label"] = plan.label
    moved.section("path")["run_dir"] = project.rel(plan.dst)
    text = f"moved from {project.rel(plan.src)}"
    moved.add_note(f"{text}: {why}" if why else text, by or "runops")
    moved.save()
    project.update_index(moved.id, plan.dst)
    result = MoveResult(moved.id, plan.src, plan.dst)
    if plan.status == RunState.CREATED:
        try:
            write_job_for(project, moved)
        except RunopsError as exc:  # submit regenerates job.sh anyway
            result.warnings.append(f"{moved.id}: job.sh not regenerated ({exc})")
    return result


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
    nested = next(
        (p for p in run_dir.rglob(MANIFEST_FILE) if p.parent != run_dir and p.is_file()), None
    )
    if nested is not None:
        raise UsageError(
            f"{manifest.id} contains another run ({project.rel(nested.parent)}); "
            "move it out of the run directory first"
        )
    shutil.rmtree(run_dir)
    project.update_index(manifest.id, None)
    _prune_empty(run_dir.parent, project.runs_dir)


def purge_work(project: Project, manifest: Manifest) -> list[str]:
    if manifest.status != RunState.COMPLETED:
        raise UsageError(f"{manifest.id} is {manifest.status.value}; purge-work needs completed")
    try:
        adapter = run_sim_context(project, manifest).adapter
    except RunopsError as exc:
        # "No keep patterns" and "cannot tell which files to keep" differ: refuse.
        raise UsageError(
            f"{manifest.id}: cannot load the adapter to read keep_patterns; "
            f"nothing was deleted ({exc})"
        ) from None
    keep = list(optional(adapter, "keep_patterns", []) or [])
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
