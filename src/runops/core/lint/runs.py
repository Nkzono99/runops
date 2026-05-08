"""Run integrity and provenance checks for ``runo lint``."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError
from runops.core.lint.models import LintContext, LintIssue
from runops.core.manifest import ManifestData, read_manifest


def check_runs(context: LintContext) -> list[LintIssue]:
    """Check manifest integrity and run_id uniqueness."""
    issues: list[LintIssue] = []
    manifests = _read_manifests(context, issues)
    id_to_paths: defaultdict[str, list[Path]] = defaultdict(list)

    for run_dir, manifest in manifests:
        run_id = str(manifest.run.get("id", "")).strip()
        if not run_id:
            issues.append(
                LintIssue(
                    severity="error",
                    issue_id="runs.run_id_missing",
                    path=run_dir / "manifest.toml",
                    message="manifest.toml has no [run].id.",
                    recommendation="Regenerate this run or assign a stable run_id.",
                )
            )
            continue
        id_to_paths[run_id].append(run_dir)
        issues.extend(_status_consistency_issues(run_dir, manifest))

    for run_id, paths in id_to_paths.items():
        if len(paths) <= 1:
            continue
        path_list = ", ".join(context.relpath(path).as_posix() for path in paths)
        issues.append(
            LintIssue(
                severity="error",
                issue_id="runs.run_id_duplicate",
                path=paths[0] / "manifest.toml",
                message=f"run_id {run_id!r} is used by multiple runs: {path_list}.",
                recommendation="Keep run_id immutable and unique before submitting.",
            )
        )

    return issues


def _status_consistency_issues(
    run_dir: Path,
    manifest: ManifestData,
) -> list[LintIssue]:
    status = str(manifest.run.get("status", "")).strip()
    slurm_state = str(manifest.run.get("last_slurm_state", "")).strip().upper()
    if not status or not slurm_state:
        return []

    active_statuses = {"submitted", "running"}
    terminal_slurm_states = {
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMEOUT",
        "OUT_OF_MEMORY",
    }
    failed_slurm_states = {"FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY"}
    issues: list[LintIssue] = []

    if status in active_statuses and slurm_state in terminal_slurm_states:
        issues.append(
            LintIssue(
                severity="warning",
                issue_id="runs.status_sync_stale",
                path=run_dir / "manifest.toml",
                message=(
                    f"manifest status is {status!r}, but last Slurm state is "
                    f"{slurm_state!r}."
                ),
                recommendation=f"Run `runo runs sync {run_dir.as_posix()}`.",
            )
        )
    if status == "completed" and slurm_state in failed_slurm_states:
        issues.append(
            LintIssue(
                severity="error",
                issue_id="runs.status_slurm_conflict",
                path=run_dir / "manifest.toml",
                message=(
                    f"manifest status is 'completed', but last Slurm state is "
                    f"{slurm_state!r}."
                ),
                recommendation=(
                    "Inspect the run log and rerun `runo runs sync` before treating "
                    "this run as completed."
                ),
            )
        )
    return issues


def check_provenance(context: LintContext) -> list[LintIssue]:
    """Check whether completed runs have core provenance fields."""
    issues: list[LintIssue] = []
    manifests = _read_manifests(context, issues)

    for run_dir, manifest in manifests:
        status = str(manifest.run.get("status", "")).strip()
        if status != "completed":
            continue
        source = manifest.simulator_source
        if not str(source.get("git_commit", "")).strip():
            issues.append(
                _provenance_issue(
                    run_dir,
                    "provenance.git_commit_missing",
                    "completed run is missing simulator_source.git_commit.",
                )
            )
        if not _first_non_empty(source, ("exe_hash", "executable_hash")):
            issues.append(
                _provenance_issue(
                    run_dir,
                    "provenance.executable_hash_missing",
                    "completed run is missing simulator executable hash.",
                )
            )
        if not _first_non_empty(
            source,
            ("package_version", "simulator_version", "version"),
        ):
            issues.append(
                _provenance_issue(
                    run_dir,
                    "provenance.simulator_version_missing",
                    "completed run is missing simulator version metadata.",
                )
            )

    return issues


def load_valid_manifests(context: LintContext) -> list[tuple[Path, ManifestData]]:
    """Return readable run manifests under the project."""
    issues: list[LintIssue] = []
    return _read_manifests(context, issues)


def _read_manifests(
    context: LintContext,
    issues: list[LintIssue],
) -> list[tuple[Path, ManifestData]]:
    run_dirs = discover_runs(context.project_root / "runs")
    manifests: list[tuple[Path, ManifestData]] = []

    for run_dir in run_dirs:
        try:
            manifests.append((run_dir, read_manifest(run_dir)))
        except SimctlError as exc:
            issues.append(
                LintIssue(
                    severity="error",
                    issue_id="runs.manifest_invalid",
                    path=run_dir / "manifest.toml",
                    message=str(exc),
                    recommendation="Fix manifest.toml before using this run.",
                )
            )
    return manifests


def _provenance_issue(run_dir: Path, issue_id: str, message: str) -> LintIssue:
    return LintIssue(
        severity="warning",
        issue_id=issue_id,
        path=run_dir / "manifest.toml",
        message=message,
        recommendation=(
            "Recreate or refresh the run with current provenance collection before "
            "using it as evidence."
        ),
    )


def _first_non_empty(data: dict[str, object], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(data.get(key, "")).strip()
        if value:
            return value
    return ""
