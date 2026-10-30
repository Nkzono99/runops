"""Progress samples from the adapter's optional ``progress()`` hook (SPEC §6.4, §8.1).

``runo sync`` asks the adapter how far each active run is (``done`` of ``total`` in some
``unit``) and appends a timestamped sample to ``submit/progress.<job_id>.jsonl``. From the
samples it derives, per attempt, the recent rate, the rate since the program started
(counting from the adapter's ``start``, e.g. the batch a resumed run began at) and the
remaining time, and keeps that summary in ``[[job.attempts]].progress`` so ``status`` and
``list`` show it without reading files.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

from runops.adapters.registry import optional
from runops.errors import RunopsError
from runops.manifest import Manifest
from runops.ops.common import run_sim_context
from runops.project import Project
from runops.util import parse_iso

SAMPLES_KEPT = 1000  # per attempt; older samples are dropped when the file doubles
RECENT_WINDOW = timedelta(minutes=10)
STALL_WINDOW = timedelta(hours=1)  # no change across this much observed time -> stalled
_START_MARK = "runops: start "


def samples_path(run_dir: Path, job_id: str) -> Path:
    return run_dir / "submit" / f"progress.{job_id}.jsonl"


def read_progress(project: Project, manifest: Manifest) -> dict[str, Any] | None:
    """The adapter's ``progress(run_dir)`` as ``{done, total, unit, start}``, or ``None``."""
    try:
        ctx = run_sim_context(project, manifest)
        raw = optional(ctx.adapter, "progress", None, manifest.run_dir)
    except (RunopsError, OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("done"), (int, float)):
        return None
    total = raw.get("total")
    start = raw.get("start")
    return {
        "done": raw["done"],
        "total": total if isinstance(total, (int, float)) and total > 0 else None,
        "unit": str(raw.get("unit") or "step"),
        "start": start if isinstance(start, (int, float)) else None,
    }


def record_progress(
    project: Project, manifest: Manifest, *, at: datetime, final: bool = False
) -> None:
    """Append one sample for the latest attempt and refresh its summary in *manifest*.

    Call under ``run.lock``; the caller saves the manifest. *final* marks the sample
    taken when the run left the queue; *at* is then its finish time, so the rate does
    not include the time after the job ended.
    """
    attempts = manifest.job.get("attempts") or []
    if not attempts or not manifest.job_id:
        return
    current = read_progress(project, manifest)
    if current is None:
        return
    path = samples_path(manifest.run_dir, manifest.job_id)
    samples = _read_samples(path)
    samples.append({"at": at.isoformat(timespec="seconds"), "done": current["done"]})
    _write_samples(path, samples)
    attempt = attempts[-1]
    if not attempt.get("started_at"):
        started = program_start(manifest)
        if started:
            attempt["started_at"] = started
    attempt["progress"] = summarize(
        samples,
        total=current["total"],
        unit=current["unit"],
        start=current["start"],
        started_at=parse_iso(str(attempt.get("started_at", ""))),
        final=final,
    )


def summarize(
    samples: list[dict[str, Any]],
    *,
    total: float | None,
    unit: str,
    start: float | None,
    started_at: datetime | None,
    final: bool = False,
) -> dict[str, Any]:
    points = [(t, float(s["done"])) for s in samples if (t := parse_iso(str(s.get("at", ""))))]
    last_at, done = points[-1]
    raw_done = samples[-1]["done"]
    # Origin for the attempt's average: the program start and the adapter's start value
    # (a resumed run starts at its checkpoint, not at 0); else the first sample.
    if started_at is not None and start is not None and started_at <= last_at:
        origin = (started_at, float(start))
    else:
        origin = points[0]
    earlier = [p for p in points[:-1] if p[0] <= last_at - RECENT_WINDOW]
    reference = earlier[-1] if earlier else (points[0] if len(points) > 1 else origin)
    rate_attempt = _rate(origin, points[-1])
    rate_recent = _rate(reference, points[-1]) or rate_attempt
    # When done last moved: the first sample, then every sample that exceeds the one before.
    last_change_at = points[0][0]
    for (_, prev_done), (at, now_done) in pairwise(points):
        if now_done > prev_done:
            last_change_at = at
    stalled = last_at - last_change_at
    summary: dict[str, Any] = {
        "done": raw_done,
        "total": total,
        "unit": unit,
        "at": last_at.isoformat(timespec="seconds"),
        "last_change_at": last_change_at.isoformat(timespec="seconds"),
        "stalled_hours": (
            round(stalled.total_seconds() / 3600, 1)
            if not final and stalled >= STALL_WINDOW
            else None
        ),
        "fraction": round(done / total, 4) if total else None,
        "rate_recent_per_hour": _round(rate_recent),
        "rate_attempt_per_hour": _round(rate_attempt),
        "eta_hours": None,
    }
    if start is not None:
        summary["start"] = start
    if not final and total and rate_recent:
        summary["eta_hours"] = round(max(total - done, 0.0) / rate_recent, 2)
    # TOML has no null: leave unknown values out.
    return {k: v for k, v in summary.items() if v is not None}


def program_start(manifest: Manifest) -> str:
    """When the program of the latest job started: job.sh prints it in stdout."""
    from runops.ops.sync import log_paths

    stdout, _ = log_paths(manifest)
    if stdout is None:
        return ""
    try:
        with stdout.open("rb") as handle:
            head = handle.read(8192).decode("utf-8", errors="replace")
    except OSError:
        return ""
    for line in head.splitlines():
        if line.startswith(_START_MARK):
            stamp = line[len(_START_MARK) :].split()[0]
            return stamp if parse_iso(stamp) else ""
    return ""


def format_progress(progress: dict[str, Any] | None) -> str:
    """Short text for tables: ``62% 0.198 s/batch eta 3.1h``."""
    if not progress:
        return ""
    parts = []
    if progress.get("fraction") is not None:
        parts.append(f"{progress['fraction']:.0%}")
    else:
        parts.append(f"{progress['done']} {progress['unit']}")
    rate = progress.get("rate_recent_per_hour")
    if rate:
        parts.append(f"{3600 / rate:.3g} s/{progress['unit']}")
    if progress.get("eta_hours") is not None:
        parts.append(f"eta {progress['eta_hours']:.1f}h")
    if progress.get("stalled_hours") is not None:
        parts.append(f"stalled {progress['stalled_hours']:.1f}h")
    return " ".join(parts)


def _rate(a: tuple[datetime, float], b: tuple[datetime, float]) -> float | None:
    hours = (b[0] - a[0]).total_seconds() / 3600
    if hours <= 0 or b[1] < a[1]:
        return None
    return (b[1] - a[1]) / hours


def _round(value: float | None) -> float | None:
    return float(f"{value:.4g}") if value else None


def _read_samples(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and "at" in item and "done" in item:
            out.append(item)
    return out


def _write_samples(path: Path, samples: list[dict[str, Any]]) -> None:
    if len(samples) > 2 * SAMPLES_KEPT:
        samples = samples[-SAMPLES_KEPT:]
        path.write_text("".join(json.dumps(s) + "\n" for s in samples), encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(samples[-1]) + "\n")
