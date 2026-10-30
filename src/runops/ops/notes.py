"""``note``, ``context``, ``summarize`` (SPEC §7.3, §9)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from runops import __version__
from runops.adapters.registry import optional
from runops.errors import UsageError
from runops.manifest import ACTIVE_STATES, Manifest, RunState
from runops.ops.analysis import group_topics
from runops.ops.common import run_sim_context
from runops.ops.skills import stale_runops_skills
from runops.project import Project
from runops.util import now_iso, parse_iso


def add_note(manifest: Manifest, text: str, by: str) -> None:
    text = text.strip()
    if not text:
        raise UsageError("note text is empty")
    manifest.add_note(text, by)
    manifest.save()


def read_notes(manifest: Manifest) -> dict[str, Any]:
    notes_md = manifest.run_dir / "notes.md"
    return {
        "id": manifest.id,
        "why": manifest.why,
        "notes": manifest.notes,
        "notes_md": notes_md.read_text(encoding="utf-8") if notes_md.is_file() else "",
    }


def summarize_run(
    project: Project, manifest: Manifest, *, force: bool = False
) -> tuple[bool, dict[str, Any]]:
    """Return (written, summary)."""
    path = manifest.run_dir / "analysis" / "summary.json"
    if path.exists() and not force:
        return False, json.loads(path.read_text(encoding="utf-8"))
    ctx = run_sim_context(project, manifest)
    summary = dict(optional(ctx.adapter, "summarize", {}, manifest.run_dir) or {})
    payload = {"run_id": manifest.id, "generated_at": now_iso(), "summary": summary}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return True, payload


def project_context(project: Project, *, log_lines: int = 20) -> dict[str, Any]:
    now = datetime.now().astimezone()
    runs = list(project.iter_runs())
    counts: dict[str, int] = {}
    expired = 0
    for m in runs:
        counts[m.status.value] = counts.get(m.status.value, 0) + 1
        if m.scratch and m.status != RunState.ARCHIVED:
            expires = parse_iso(str(m.run.get("expires_at", "")))
            if expires is not None and expires <= now:
                expired += 1
    by_created = sorted(runs, key=lambda m: m.created_at, reverse=True)
    recent = [m for m in by_created if m.status != RunState.ARCHIVED][:5]
    active = [m for m in by_created if m.status in ACTIVE_STATES]
    log_path = project.root / "LOG.md"
    log_tail = ""
    if log_path.is_file():
        log_tail = "\n".join(log_path.read_text(encoding="utf-8").splitlines()[-log_lines:])
    notes_dir = project.root / "notes"
    note_files = (
        sorted(p.relative_to(notes_dir).as_posix() for p in notes_dir.rglob("*.md"))
        if notes_dir.is_dir()
        else []
    )
    return {
        "runops_version": __version__,
        "project": project.config.name,
        "root": str(project.root),
        "simulators": {
            name: {"adapter": sim.adapter, "resolver_mode": sim.resolver_mode}
            for name, sim in project.config.simulators.items()
        },
        "status_counts": counts,
        "active_runs": len(active),
        # Every submitted / running run, briefly (no params), so one call shows them all.
        "active": [m.to_summary(project.root, brief=True) for m in active],
        "expired_scratch": expired,
        "recent_runs": [m.to_summary(project.root) for m in recent],
        "notes_files": note_files,
        "group_analysis": group_topics(project),
        "log_tail": log_tail,
        "warnings": [w for w in [stale_runops_skills(project)] if w],
    }
