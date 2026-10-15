"""Run selection for ``list`` (SPEC §7.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from runops.manifest import ACTIVE_STATES, Manifest, RunState
from runops.ops.common import inside
from runops.project import Project


@dataclass
class ListFilter:
    path: Path | None = None
    show_all: bool = False
    since: timedelta | None = None
    cases: list[str] = field(default_factory=list)
    sweeps: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    scratch: bool = False
    archived: bool = False


def select_runs(project: Project, flt: ListFilter, now: datetime | None = None) -> list[Manifest]:
    now = now or datetime.now().astimezone()
    since = flt.since or timedelta(days=project.config.defaults.list_since_days)
    under = flt.path if flt.path is not None else None
    selected: list[Manifest] = []
    for manifest in project.iter_runs(under):
        if under is not None and not inside(manifest.run_dir, under):
            continue
        if flt.statuses and manifest.status.value not in flt.statuses:
            continue
        if flt.cases and manifest.case not in flt.cases:
            continue
        if flt.sweeps and manifest.sweep not in flt.sweeps:
            continue
        if flt.tags and not set(flt.tags) <= set(manifest.tags):
            continue
        archived = manifest.status == RunState.ARCHIVED
        explicit_status = RunState.ARCHIVED.value in flt.statuses
        if archived and not (flt.archived or explicit_status):
            continue
        if manifest.scratch and not archived and not flt.scratch:
            continue
        if not (flt.show_all or archived or manifest.scratch or flt.statuses):
            created = manifest.created_datetime()
            recent = created is not None and now - created <= since
            if not (
                manifest.status in ACTIVE_STATES
                or manifest.status == RunState.CREATED
                or recent
                or manifest.pinned
            ):
                continue
        selected.append(manifest)
    selected.sort(key=lambda m: m.created_at, reverse=True)
    return selected


def relative_age(value: str, now: datetime | None = None) -> str:
    from runops.util import parse_iso

    created = parse_iso(value)
    if created is None:
        return "?"
    seconds = int(((now or datetime.now().astimezone()) - created).total_seconds())
    if seconds < 0:
        return "now"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return f"{seconds}s ago"
