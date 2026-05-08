"""Helpers for deriving a new run from an existing run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runops.core.manifest import ManifestData
from runops.core.run.records import RunInfo
from runops.core.state import RunState

_TRANSIENT_RUN_KEYS = frozenset(
    {
        "failure_reason",
        "last_slurm_state",
        "partial_outputs",
        "retry_note",
        "retry_status",
    }
)

_TRANSIENT_JOB_KEYS = frozenset(
    {
        "afterok",
        "attempt",
        "attempts",
        "dependency_afterok",
        "job_id",
        "next_attempt",
        "qos",
        "queue",
        "retry_adjustments",
        "submitted_at",
    }
)

_STANDARD_FILE_DIRS = {
    "input_dir": "input",
    "submit_dir": "submit",
    "work_dir": "work",
    "analysis_dir": "analysis",
    "status_dir": "status",
}


def sanitize_derived_manifest(
    source_manifest: ManifestData,
    *,
    run_info: RunInfo,
    parent_run_id: str,
    display_name: str,
    params_snapshot: dict[str, Any] | None = None,
    variation_keys: list[str] | None = None,
) -> ManifestData:
    """Build a manifest for a copied or derived run.

    The new manifest preserves stable provenance and configuration from the
    source run, but clears scheduler/runtime state that belongs only to the
    original execution attempt.
    """
    new_manifest = ManifestData.from_dict(source_manifest.to_dict())

    new_manifest.run = {
        key: value
        for key, value in new_manifest.run.items()
        if key not in _TRANSIENT_RUN_KEYS
    }
    new_manifest.run.update(
        {
            "id": run_info.run_id,
            "display_name": display_name,
            "status": RunState.CREATED.value,
            "created_at": run_info.created_at,
        }
    )

    new_manifest.path = dict(new_manifest.path)
    new_manifest.path["run_dir"] = str(run_info.run_dir)

    new_manifest.origin = dict(new_manifest.origin)
    new_manifest.origin["survey"] = ""
    new_manifest.origin["parent_run"] = parent_run_id

    job = {
        key: value
        for key, value in new_manifest.job.items()
        if key not in _TRANSIENT_JOB_KEYS
    }
    job["scheduler"] = str(job.get("scheduler", "slurm") or "slurm")
    job["job_id"] = ""
    job["submitted_at"] = ""
    new_manifest.job = job

    new_manifest.variation = {"changed_keys": list(variation_keys or [])}
    if params_snapshot is None:
        new_manifest.params_snapshot = dict(source_manifest.params_snapshot)
    else:
        new_manifest.params_snapshot = dict(params_snapshot)

    files = dict(new_manifest.files)
    for key, value in _STANDARD_FILE_DIRS.items():
        files.setdefault(key, value)
    new_manifest.files = files

    return new_manifest


def rewrite_job_script_references(
    job_script: Path,
    *,
    source_dir: Path,
    target_dir: Path,
    source_run_id: str,
    target_run_id: str,
) -> None:
    """Rewrite obvious source-run references in a copied job script."""
    if not job_script.is_file():
        return

    content = job_script.read_text(encoding="utf-8")
    replacements = (
        (str(source_dir.resolve()), str(target_dir.resolve())),
        (str(source_dir), str(target_dir)),
        (source_run_id, target_run_id),
    )
    for old, new in replacements:
        if old and old != new:
            content = content.replace(old, new)

    job_script.write_text(content, encoding="utf-8")
