"""Read-only project triage before creating more experiment state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.application.run_query import RunQueryEntry, query_runs
from runops.core.exceptions import SimctlError
from runops.core.experiment import (
    ExperimentData,
    experiment_is_expired,
    load_experiment,
)
from runops.core.manifest import read_manifest
from runops.core.research.result import read_result_manifest
from runops.core.run.curation import has_valid_run_review
from runops.core.state import RunState
from runops.core.test_attempt import (
    TEST_ATTEMPT_TERMINAL_STATES,
    TestAttemptData,
    load_test_attempt,
    parse_test_timestamp,
)

DEFAULT_TEST_ATTEMPT_AGE_DAYS = 14
DEFAULT_STAGING_AGE_HOURS = 24
_MAX_ADOPTION_RECEIPT_BYTES = 8 * 1024 * 1024
_MAX_LIFECYCLE_RECEIPT_BYTES = 8 * 1024 * 1024
_MAX_BUNDLE_MARKER_BYTES = 1024 * 1024

_TEST_ATTEMPT_ID = re.compile(r"^T\d{8}-\d{4}$")
_RUN_ID = re.compile(r"^R\d{8}-\d{4}$")
_ADOPTION_TRANSACTION = re.compile(r"^\.tmp-adopt-(.+)-[0-9a-f]{12}$")
_VALID_RUN_STATES = frozenset(state.value for state in RunState)
_COMPLETED_EQUIVALENT_STATES = frozenset({"completed", "archived", "purged"})
_UNASSIGNED_EXPERIMENT = "<unassigned>"


@dataclass(frozen=True)
class TriageDiagnostic:
    """One malformed or unsafe record encountered during best-effort triage."""

    section: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """Return a deterministic JSON representation."""
        return {
            "section": self.section,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class ActiveExperimentTriage:
    """One active Experiment with the formal Runs currently assigned to it."""

    experiment_id: str
    title: str
    decision: str
    expires_at: str
    expired: bool
    run_count: int | None
    run_status_counts: dict[str, int] | None

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON representation."""
        return {
            "id": self.experiment_id,
            "title": self.title,
            "decision": self.decision,
            "expires_at": self.expires_at,
            "expired": self.expired,
            "run_count": self.run_count,
            "run_status_counts": self.run_status_counts,
        }


@dataclass(frozen=True)
class TriageReport:
    """Bounded, JSON-serializable project triage snapshot."""

    project_root: Path
    generated_at: str
    test_attempt_age_days: int
    active_experiments: tuple[ActiveExperimentTriage, ...]
    active_experiment_count: int
    pending_decision_count: int
    active_formal_run_count: int | None
    run_status_counts: dict[str, int] | None
    run_experiment_counts: dict[str, int] | None
    run_experiment_status_counts: dict[str, dict[str, int]] | None
    unreviewed_completed_count: int | None
    test_attempt_count: int
    test_attempt_state_counts: dict[str, int]
    old_test_attempt_count: int
    old_terminal_test_attempt_count: int
    old_active_test_attempt_count: int
    active_result_count: int
    archived_result_count: int
    result_status_counts: dict[str, int]
    diagnostics: tuple[TriageDiagnostic, ...]
    suggested_actions: tuple[str, ...]
    run_namespace_available: bool = True

    def to_dict(self) -> dict[str, object]:
        """Return the stable machine-readable report shape."""
        by_experiment = (
            {
                experiment_id: {
                    "total": self.run_experiment_counts[experiment_id],
                    "by_status": (self.run_experiment_status_counts or {}).get(
                        experiment_id,
                        {},
                    ),
                }
                for experiment_id in self.run_experiment_counts
            }
            if self.run_experiment_counts is not None
            else None
        )
        return {
            "project_root": str(self.project_root),
            "generated_at": self.generated_at,
            "experiments": {
                "active_count": self.active_experiment_count,
                "pending_decision_count": self.pending_decision_count,
                "items": [item.to_dict() for item in self.active_experiments],
            },
            "runs": {
                "namespace_available": self.run_namespace_available,
                "active_formal_count": self.active_formal_run_count,
                "by_status": self.run_status_counts,
                "by_experiment": by_experiment,
                "unreviewed_completed_count": self.unreviewed_completed_count,
            },
            "test_attempts": {
                "total": self.test_attempt_count,
                "by_state": self.test_attempt_state_counts,
                "older_than_days": self.test_attempt_age_days,
                "old_count": self.old_test_attempt_count,
                "old_terminal_count": self.old_terminal_test_attempt_count,
                "old_active_count": self.old_active_test_attempt_count,
            },
            "results": {
                "total": self.active_result_count + self.archived_result_count,
                "active_count": self.active_result_count,
                "archived_count": self.archived_result_count,
                "active_by_status": self.result_status_counts,
            },
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "suggested_actions": list(self.suggested_actions),
        }


@dataclass(frozen=True)
class _RunSummary:
    total: int | None
    by_status: dict[str, int] | None
    by_experiment: dict[str, int] | None
    by_experiment_status: dict[str, dict[str, int]] | None
    unreviewed_completed: int | None
    available: bool


@dataclass(frozen=True)
class _TestAttemptSummary:
    total: int
    by_state: dict[str, int]
    old_total: int
    old_terminal: int
    old_active: int


@dataclass(frozen=True)
class _ResultSummary:
    active_total: int
    archived_total: int
    active_by_status: dict[str, int]


def build_triage_report(
    project_root: Path,
    *,
    test_attempt_age_days: int = DEFAULT_TEST_ATTEMPT_AGE_DAYS,
    now: datetime | None = None,
) -> TriageReport:
    """Inspect bounded project state without creating or updating any files."""
    if (
        isinstance(test_attempt_age_days, bool)
        or not isinstance(test_attempt_age_days, int)
        or test_attempt_age_days < 0
    ):
        raise ValueError("test_attempt_age_days must be a non-negative integer")
    timestamp = now or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("triage timestamp must include a UTC offset")
    timestamp = timestamp.astimezone(timezone.utc)
    root = project_root.resolve()
    diagnostics: list[TriageDiagnostic] = []

    experiments = _collect_experiments(root, diagnostics)
    run_summary = _collect_runs(root, diagnostics)
    for experiment in experiments:
        if experiment.lifecycle == "active" and experiment_is_expired(
            experiment,
            now=timestamp,
        ):
            diagnostics.append(
                _diagnostic(
                    root,
                    section="experiments",
                    code="experiment.expired",
                    path=experiment.experiment_file,
                    message=(
                        f"Active Experiment {experiment.id} expired at "
                        f"{experiment.budget.expires_at}; close it or admit a successor"
                    ),
                )
            )
    active_experiments = tuple(
        ActiveExperimentTriage(
            experiment_id=experiment.id,
            title=experiment.title,
            decision=experiment.decision,
            expires_at=experiment.budget.expires_at,
            expired=experiment_is_expired(experiment, now=timestamp),
            run_count=(
                run_summary.by_experiment.get(experiment.id, 0)
                if run_summary.by_experiment is not None
                else None
            ),
            run_status_counts=(
                run_summary.by_experiment_status.get(experiment.id, {})
                if run_summary.by_experiment_status is not None
                else None
            ),
        )
        for experiment in experiments
        if experiment.lifecycle == "active"
    )
    cutoff = timestamp - timedelta(days=test_attempt_age_days)
    test_summary = _collect_test_attempts(root, cutoff, diagnostics)
    result_summary = _collect_results(root, diagnostics)
    _collect_lifecycle_receipt_diagnostics(root, diagnostics)
    _collect_staging_diagnostics(
        root,
        cutoff=timestamp - timedelta(hours=DEFAULT_STAGING_AGE_HOURS),
        diagnostics=diagnostics,
    )
    ordered_diagnostics = tuple(
        sorted(
            diagnostics,
            key=lambda item: (item.section, item.path, item.code, item.message),
        )
    )
    suggested_actions = _suggest_actions(
        active_experiments=active_experiments,
        run_summary=run_summary,
        test_summary=test_summary,
        test_attempt_age_days=test_attempt_age_days,
        diagnostic_count=len(ordered_diagnostics),
        expired_experiment_count=sum(item.expired for item in active_experiments),
        stale_staging_count=sum(
            item.code == "staging.orphan_candidate" for item in ordered_diagnostics
        ),
    )

    return TriageReport(
        project_root=root,
        generated_at=timestamp.isoformat(),
        test_attempt_age_days=test_attempt_age_days,
        active_experiments=active_experiments,
        active_experiment_count=len(active_experiments),
        pending_decision_count=sum(
            item.decision == "pending" for item in active_experiments
        ),
        active_formal_run_count=run_summary.total,
        run_status_counts=run_summary.by_status,
        run_experiment_counts=run_summary.by_experiment,
        run_experiment_status_counts=run_summary.by_experiment_status,
        unreviewed_completed_count=run_summary.unreviewed_completed,
        test_attempt_count=test_summary.total,
        test_attempt_state_counts=test_summary.by_state,
        old_test_attempt_count=test_summary.old_total,
        old_terminal_test_attempt_count=test_summary.old_terminal,
        old_active_test_attempt_count=test_summary.old_active,
        active_result_count=result_summary.active_total,
        archived_result_count=result_summary.archived_total,
        result_status_counts=result_summary.active_by_status,
        diagnostics=ordered_diagnostics,
        suggested_actions=suggested_actions,
        run_namespace_available=run_summary.available,
    )


def _collect_experiments(
    root: Path,
    diagnostics: list[TriageDiagnostic],
) -> tuple[ExperimentData, ...]:
    experiments_root = root / "experiments"
    if not experiments_root.exists() and not experiments_root.is_symlink():
        return ()
    if experiments_root.is_symlink() or not experiments_root.is_dir():
        diagnostics.append(
            _diagnostic(
                root,
                section="experiments",
                code="experiment.root_invalid",
                path=experiments_root,
                message="Experiment root must be a real directory",
            )
        )
        return ()
    try:
        candidates = sorted(experiments_root.rglob("*.toml"))
    except OSError as exc:
        diagnostics.append(
            _diagnostic(
                root,
                section="experiments",
                code="experiment.discovery_failed",
                path=experiments_root,
                message=str(exc),
            )
        )
        return ()

    experiments: list[ExperimentData] = []
    by_id: dict[str, Path] = {}
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            diagnostics.append(
                _diagnostic(
                    root,
                    section="experiments",
                    code="experiment.file_unsafe",
                    path=path,
                    message="Experiment definition must be a regular non-symlink file",
                )
            )
            continue
        try:
            experiment = load_experiment(path)
        except (SimctlError, OSError, TypeError, ValueError) as exc:
            diagnostics.append(
                _diagnostic(
                    root,
                    section="experiments",
                    code="experiment.definition_invalid",
                    path=path,
                    message=str(exc),
                )
            )
            continue
        previous = by_id.get(experiment.id)
        if previous is not None:
            diagnostics.append(
                _diagnostic(
                    root,
                    section="experiments",
                    code="experiment.id_duplicate",
                    path=path,
                    message=(
                        f"Experiment ID {experiment.id} is also defined at "
                        f"{_relative(previous, root)}"
                    ),
                )
            )
            continue
        by_id[experiment.id] = path
        experiments.append(experiment)
    return tuple(sorted(experiments, key=lambda item: item.id))


def _collect_runs(
    root: Path,
    diagnostics: list[TriageDiagnostic],
) -> _RunSummary:
    try:
        # Prove the exhaustive view first so an apparently complete active
        # summary cannot hide an unreadable archive or namespace subtree.
        all_entries = query_runs(root, view="all", strict_manifests=True)
        entries = query_runs(root, view="active", strict_manifests=True)
    except (SimctlError, OSError) as exc:
        diagnostics.append(
            _diagnostic(
                root,
                section="runs",
                code="run.namespace_unreadable",
                path=root / "runs",
                message=(
                    "Run totals are unavailable because the formal namespace "
                    f"could not be enumerated safely: {exc}"
                ),
            )
        )
        return _RunSummary(
            total=None,
            by_status=None,
            by_experiment=None,
            by_experiment_status=None,
            unreviewed_completed=None,
            available=False,
        )
    active_paths = {entry.run_dir for entry in entries}
    invalid_manifest = False
    for entry in all_entries:
        if entry.run_dir not in active_paths:
            status, _experiment_id, _review_status = _read_run_fields(
                root,
                entry,
                diagnostics,
            )
            invalid_manifest = invalid_manifest or status == "invalid"
    entries.sort(key=lambda entry: entry.run_dir)
    statuses: Counter[str] = Counter()
    experiments: Counter[str] = Counter()
    experiment_statuses: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for entry in entries:
        status, experiment_id, _review_status = _read_run_fields(
            root,
            entry,
            diagnostics,
        )
        if status == "invalid":
            invalid_manifest = True
            continue
        statuses[status] += 1
        group = experiment_id or _UNASSIGNED_EXPERIMENT
        experiments[group] += 1
        experiment_statuses[group][status] += 1
    if invalid_manifest:
        diagnostics.append(
            _diagnostic(
                root,
                section="runs",
                code="run.namespace_unreadable",
                path=root / "runs",
                message=(
                    "Run totals are unavailable because at least one formal "
                    "Run manifest is invalid"
                ),
            )
        )
        return _RunSummary(
            total=None,
            by_status=None,
            by_experiment=None,
            by_experiment_status=None,
            unreviewed_completed=None,
            available=False,
        )

    unreviewed_completed = sum(
        entry.manifest is not None
        and entry.status in _COMPLETED_EQUIVALENT_STATES
        and not has_valid_run_review(entry.manifest.curation)
        for entry in all_entries
    )

    return _RunSummary(
        total=sum(statuses.values()),
        by_status=_sorted_counts(statuses),
        by_experiment=_sorted_counts(experiments),
        by_experiment_status={
            experiment_id: _sorted_counts(counts)
            for experiment_id, counts in sorted(experiment_statuses.items())
        },
        unreviewed_completed=unreviewed_completed,
        available=True,
    )


def _read_run_fields(
    root: Path,
    entry: RunQueryEntry,
    diagnostics: list[TriageDiagnostic],
) -> tuple[str, str, str]:
    manifest = entry.manifest
    if manifest is None:
        try:
            read_manifest(entry.run_dir)
        except (SimctlError, OSError, TypeError, ValueError) as exc:
            message = str(exc)
        else:  # pragma: no cover - protects against a concurrent file replacement
            message = "manifest became readable after discovery"
        diagnostics.append(
            _diagnostic(
                root,
                section="runs",
                code="run.manifest_invalid",
                path=entry.run_dir / "manifest.toml",
                message=message,
            )
        )
        return "invalid", "", ""

    run_id = manifest.run.get("id")
    raw_status = manifest.run.get("status")
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        diagnostics.append(
            _diagnostic(
                root,
                section="runs",
                code="run.identity_invalid",
                path=entry.run_dir / "manifest.toml",
                message="run.id must match RYYYYMMDD-NNNN",
            )
        )
        return "invalid", "", ""
    if not isinstance(raw_status, str) or raw_status not in _VALID_RUN_STATES:
        diagnostics.append(
            _diagnostic(
                root,
                section="runs",
                code="run.status_invalid",
                path=entry.run_dir / "manifest.toml",
                message=(
                    f"run.status is not a recognized lifecycle state: {raw_status!r}"
                ),
            )
        )
        return "invalid", "", ""

    raw_experiment = manifest.intent.get("experiment_id", "")
    if not isinstance(raw_experiment, str):
        diagnostics.append(
            _diagnostic(
                root,
                section="runs",
                code="run.experiment_invalid",
                path=entry.run_dir / "manifest.toml",
                message="intent.experiment_id must be a string",
            )
        )
        raw_experiment = ""
    raw_review = manifest.curation.get("review_status", "unreviewed")
    if not isinstance(raw_review, str):
        diagnostics.append(
            _diagnostic(
                root,
                section="runs",
                code="run.review_invalid",
                path=entry.run_dir / "manifest.toml",
                message="curation.review_status must be a string",
            )
        )
        raw_review = "unreviewed"
    return raw_status, raw_experiment.strip(), raw_review


def _collect_test_attempts(
    root: Path,
    cutoff: datetime,
    diagnostics: list[TriageDiagnostic],
) -> _TestAttemptSummary:
    test_root = root / ".runops" / "test-runs"
    if not test_root.exists() and not test_root.is_symlink():
        return _TestAttemptSummary(0, {}, 0, 0, 0)
    if test_root.is_symlink() or not test_root.is_dir():
        diagnostics.append(
            _diagnostic(
                root,
                section="test_attempts",
                code="test_attempt.root_invalid",
                path=test_root,
                message="TestAttempt root must be a real directory",
            )
        )
        return _TestAttemptSummary(0, {}, 0, 0, 0)
    try:
        candidates = [
            path
            for path in sorted(test_root.iterdir(), key=lambda item: item.name)
            if _TEST_ATTEMPT_ID.fullmatch(path.name)
        ]
    except OSError as exc:
        diagnostics.append(
            _diagnostic(
                root,
                section="test_attempts",
                code="test_attempt.discovery_failed",
                path=test_root,
                message=str(exc),
            )
        )
        return _TestAttemptSummary(0, {}, 0, 0, 0)

    attempts: list[TestAttemptData] = []
    for path in candidates:
        try:
            attempts.append(load_test_attempt(path))
        except (SimctlError, OSError, TypeError, ValueError) as exc:
            diagnostics.append(
                _diagnostic(
                    root,
                    section="test_attempts",
                    code="test_attempt.receipt_invalid",
                    path=path / "test-receipt.toml",
                    message=str(exc),
                )
            )

    states: Counter[str] = Counter(attempt.state for attempt in attempts)
    old = [
        attempt
        for attempt in attempts
        if parse_test_timestamp(attempt.finished_at or attempt.updated_at).astimezone(
            timezone.utc
        )
        <= cutoff
    ]
    old_terminal = sum(attempt.state in TEST_ATTEMPT_TERMINAL_STATES for attempt in old)
    return _TestAttemptSummary(
        total=len(attempts),
        by_state=_sorted_counts(states),
        old_total=len(old),
        old_terminal=old_terminal,
        old_active=len(old) - old_terminal,
    )


def _collect_results(
    root: Path,
    diagnostics: list[TriageDiagnostic],
) -> _ResultSummary:
    active, active_statuses = _collect_result_root(
        root,
        root / "research" / "results",
        diagnostics,
        code_prefix="result.active",
    )
    archived, _archived_statuses = _collect_result_root(
        root,
        root / "research" / "archive" / "results",
        diagnostics,
        code_prefix="result.archived",
    )
    return _ResultSummary(
        active_total=active,
        archived_total=archived,
        active_by_status=active_statuses,
    )


def _collect_result_root(
    project_root: Path,
    result_root: Path,
    diagnostics: list[TriageDiagnostic],
    *,
    code_prefix: str,
) -> tuple[int, dict[str, int]]:
    if not result_root.exists() and not result_root.is_symlink():
        return 0, {}
    if result_root.is_symlink() or not result_root.is_dir():
        diagnostics.append(
            _diagnostic(
                project_root,
                section="results",
                code=f"{code_prefix}_root_invalid",
                path=result_root,
                message="Result root must be a real directory",
            )
        )
        return 0, {}
    try:
        candidates = [
            path
            for path in sorted(result_root.iterdir(), key=lambda item: item.name)
            if not path.name.startswith(".tmp-result-")
            and (path.is_dir() or path.is_symlink())
        ]
    except OSError as exc:
        diagnostics.append(
            _diagnostic(
                project_root,
                section="results",
                code=f"{code_prefix}_discovery_failed",
                path=result_root,
                message=str(exc),
            )
        )
        return 0, {}

    statuses: Counter[str] = Counter()
    for result_dir in candidates:
        if result_dir.is_symlink() or not result_dir.is_dir():
            diagnostics.append(
                _diagnostic(
                    project_root,
                    section="results",
                    code=f"{code_prefix}_unsafe",
                    path=result_dir,
                    message="Result directory must be a regular non-symlink directory",
                )
            )
            continue
        try:
            manifest = read_result_manifest(result_dir)
        except (OSError, TypeError, ValueError) as exc:
            diagnostics.append(
                _diagnostic(
                    project_root,
                    section="results",
                    code=f"{code_prefix}_manifest_invalid",
                    path=result_dir / "manifest.toml",
                    message=str(exc),
                )
            )
            continue
        statuses[manifest.status] += 1
    return sum(statuses.values()), _sorted_counts(statuses)


def _collect_lifecycle_receipt_diagnostics(
    root: Path,
    diagnostics: list[TriageDiagnostic],
) -> None:
    """Surface pending per-Run archive/restore transactions immediately."""
    state_root = root / ".runops"
    lifecycle_root = state_root / "lifecycle"
    if not os.path.lexists(state_root):
        return
    if state_root.is_symlink() or not state_root.is_dir():
        diagnostics.append(
            _diagnostic(
                root,
                section="staging",
                code="lifecycle.state_root_unsafe",
                path=state_root,
                message="Run lifecycle state root must be a real directory",
            )
        )
        return
    if not os.path.lexists(lifecycle_root):
        return
    if lifecycle_root.is_symlink() or not lifecycle_root.is_dir():
        diagnostics.append(
            _diagnostic(
                root,
                section="staging",
                code="lifecycle.receipt_root_unsafe",
                path=lifecycle_root,
                message="Run lifecycle receipt root must be a real directory",
            )
        )
        return
    try:
        candidates = sorted(lifecycle_root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        diagnostics.append(
            _diagnostic(
                root,
                section="staging",
                code="lifecycle.receipt_root_unreadable",
                path=lifecycle_root,
                message=str(exc),
            )
        )
        return

    for receipt in candidates:
        try:
            action, command = _read_lifecycle_retry_command(root, receipt)
        except (OSError, SimctlError, ValueError) as exc:
            diagnostics.append(
                _diagnostic(
                    root,
                    section="staging",
                    code="lifecycle.receipt_invalid",
                    path=receipt,
                    message=str(exc),
                )
            )
            continue
        operation = "archive" if action == "archive_run" else "restore"
        diagnostics.append(
            _diagnostic(
                root,
                section="staging",
                code=f"run.{operation}_pending",
                path=receipt,
                message=(
                    f"Run {operation} transaction requires recovery; rerun `{command}`"
                ),
            )
        )


def _read_lifecycle_retry_command(root: Path, receipt: Path) -> tuple[str, str]:
    """Validate the routing fields needed to print one safe retry command."""
    payload = _read_bounded_receipt(
        receipt,
        label="Run lifecycle receipt",
        maximum_bytes=_MAX_LIFECYCLE_RECEIPT_BYTES,
    )
    try:
        raw = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid Run lifecycle receipt {receipt}: {exc}") from exc
    expected_fields = {
        "schema_version",
        "kind",
        "action",
        "run_id",
        "source",
        "destination",
        "transition_at",
        "manifest_snapshot_b64",
        "manifest_sha256",
        "state_present",
        "state_snapshot_b64",
        "state_sha256",
    }
    if not isinstance(raw, dict) or set(raw) != expected_fields:
        raise ValueError(f"invalid Run lifecycle receipt schema: {receipt}")
    action = raw.get("action")
    run_id = raw.get("run_id")
    transition_at = raw.get("transition_at")
    if (
        type(raw.get("schema_version")) is not int
        or raw.get("schema_version") != 1
        or raw.get("kind") != "run-lifecycle-v1"
        or action not in {"archive_run", "restore_run"}
        or not isinstance(run_id, str)
        or _RUN_ID.fullmatch(run_id) is None
        or not isinstance(transition_at, str)
        or not transition_at
        or type(raw.get("state_present")) is not bool
    ):
        raise ValueError(f"invalid Run lifecycle receipt fields: {receipt}")
    try:
        timestamp = datetime.fromisoformat(transition_at)
    except ValueError as exc:
        raise ValueError(f"invalid lifecycle transition_at: {receipt}") from exc
    if timestamp.tzinfo is None:
        raise ValueError(f"lifecycle transition_at lacks timezone: {receipt}")

    source = _canonical_receipt_path(raw.get("source"), field="source")
    assert source is not None
    destination = _canonical_receipt_path(
        raw.get("destination"),
        field="destination",
        allow_empty=True,
    )
    expected_name = (
        f"{action}-{hashlib.sha256(str(source).encode('utf-8')).hexdigest()[:24]}.json"
    )
    if receipt.name != expected_name:
        raise ValueError(f"lifecycle receipt filename does not match source: {receipt}")
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"lifecycle receipt source is outside this project: {source}"
        ) from exc

    runs_root = (root / "runs").resolve()
    try:
        source_relative = source.relative_to(runs_root)
    except ValueError as exc:
        raise ValueError(
            f"lifecycle receipt source is outside the Run namespace: {source}"
        ) from exc
    if not source_relative.parts:
        raise ValueError(f"lifecycle receipt source is the runs/ root: {source}")

    from runops.application.actions.admin import (
        default_archive_destination,
        inspect_archive_recovery,
        inspect_restore_recovery,
    )

    if action == "restore_run":
        if destination is not None:
            try:
                destination_relative = destination.relative_to(runs_root)
            except ValueError as exc:
                raise ValueError(
                    "lifecycle restore destination escapes the Run namespace: "
                    f"{destination}"
                ) from exc
            if (
                not destination_relative.parts
                or destination_relative.parts[0] == "_archive"
            ):
                raise ValueError(
                    "lifecycle restore destination is not in the active Run view: "
                    f"{destination}"
                )
        recovery = inspect_restore_recovery(source)
        if recovery is None or recovery[1] != run_id:
            raise ValueError(
                "lifecycle restore receipt is not authoritatively recoverable: "
                f"{receipt}"
            )
        return action, f"runo runs restore {shlex.quote(str(source))}"

    if source_relative.parts[0] == "_archive":
        raise ValueError(
            f"lifecycle archive source is already in cold storage: {source}"
        )

    command = f"runo runs archive {shlex.quote(str(source))} --yes"
    if destination is None:
        if inspect_archive_recovery(source, move_to=None) != run_id:
            raise ValueError(
                "lifecycle archive receipt is not authoritatively recoverable: "
                f"{receipt}"
            )
        return action, command + " --keep-in-place"

    managed_archive_root = (root / "runs" / "_archive").resolve()
    try:
        destination.relative_to(managed_archive_root)
    except ValueError as exc:
        raise ValueError(
            f"lifecycle archive destination escapes managed storage: {destination}"
        ) from exc

    if default_archive_destination(source) == destination:
        if inspect_archive_recovery(source, move_to=destination) != run_id:
            raise ValueError(
                "lifecycle archive receipt is not authoritatively recoverable: "
                f"{receipt}"
            )
        return action, command
    relative = source_relative
    if relative.parts and relative.parts[0] == "_archive":
        relative = Path(*relative.parts[1:])
    if not relative.parts:
        raise ValueError(
            f"cannot derive archive root from lifecycle receipt: {receipt}"
        )
    archive_root = destination
    for _part in relative.parts:
        archive_root = archive_root.parent
    if default_archive_destination(source, archive_root=archive_root) != destination:
        raise ValueError(f"cannot verify archive root in lifecycle receipt: {receipt}")
    if inspect_archive_recovery(source, move_to=destination) != run_id:
        raise ValueError(
            f"lifecycle archive receipt is not authoritatively recoverable: {receipt}"
        )
    return action, command + f" --move-to {shlex.quote(str(archive_root))}"


def _canonical_receipt_path(
    raw: object,
    *,
    field: str,
    allow_empty: bool = False,
) -> Path | None:
    if allow_empty and raw == "":
        return None
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"invalid lifecycle receipt {field}")
    path = Path(raw)
    if not path.is_absolute() or str(path) != raw:
        raise ValueError(f"lifecycle receipt {field} must be an absolute path")
    canonical = path.parent.resolve() / path.name
    if canonical != path:
        raise ValueError(f"lifecycle receipt {field} is not canonical: {path}")
    return path


def _collect_staging_diagnostics(
    root: Path,
    *,
    cutoff: datetime,
    diagnostics: list[TriageDiagnostic],
) -> None:
    """Surface old unpublished transaction directories without deleting them."""
    roots = (
        root / "runs",
        root / ".runops" / "test-runs",
        root / "research" / "results",
        root / "research" / "archive" / "results",
    )
    for scan_root in roots:
        if not scan_root.is_dir() or scan_root.is_symlink():
            continue
        for dirpath, dirnames, filenames in os.walk(
            scan_root,
            topdown=True,
            onerror=lambda _error: None,
        ):
            current = Path(dirpath)
            staging_names = [
                name for name in dirnames if name.startswith((".tmp-", ".delete-"))
            ]
            for name in staging_names:
                candidate = current / name
                adoption_receipt = candidate / "receipt.toml"
                if name.startswith(".tmp-adopt-"):
                    diagnostic_path = adoption_receipt
                    try:
                        if os.path.lexists(adoption_receipt):
                            source_path = _read_pending_adoption_source(
                                root,
                                adoption_receipt,
                            )
                        else:
                            diagnostic_path = candidate
                            source_path = _read_receiptless_adoption_source(
                                root,
                                candidate,
                            )
                    except (OSError, SimctlError, ValueError) as exc:
                        diagnostics.append(
                            _diagnostic(
                                root,
                                section="staging",
                                code="bundle.adoption_receipt_invalid",
                                path=diagnostic_path,
                                message=str(exc),
                            )
                        )
                    else:
                        diagnostics.append(
                            _diagnostic(
                                root,
                                section="staging",
                                code="bundle.adoption_pending",
                                path=diagnostic_path,
                                message=(
                                    "bundle adoption requires recovery; rerun "
                                    f"`runo runs archive {shlex.quote(source_path)} "
                                    "--bundle --adopt-archived`"
                                ),
                            )
                        )
                    continue
                try:
                    metadata = candidate.lstat()
                except OSError as exc:
                    diagnostics.append(
                        _diagnostic(
                            root,
                            section="staging",
                            code="staging.inspect_failed",
                            path=candidate,
                            message=str(exc),
                        )
                    )
                    continue
                modified = datetime.fromtimestamp(metadata.st_mtime, tz=timezone.utc)
                if modified > cutoff:
                    continue
                diagnostics.append(
                    _diagnostic(
                        root,
                        section="staging",
                        code="staging.orphan_candidate",
                        path=candidate,
                        message=(
                            "unpublished transaction directory is at least "
                            f"{DEFAULT_STAGING_AGE_HOURS} hours old; inspect it "
                            "before guarded removal"
                        ),
                    )
                )
            dirnames[:] = [name for name in dirnames if name not in staging_names]
            if "manifest.toml" in filenames:
                pending_purge = current / "status" / ".purge-pending.json"
                if os.path.lexists(pending_purge):
                    diagnostics.append(
                        _diagnostic(
                            root,
                            section="staging",
                            code="purge.transaction_pending",
                            path=pending_purge,
                            message=(
                                "purge transaction requires recovery; rerun the "
                                "original command, including discard flags when used: "
                                "`runo runs purge-work "
                                f"{shlex.quote(str(current))}`"
                            ),
                        )
                    )
                dirnames[:] = []
            elif "test-receipt.toml" in filenames:
                dirnames[:] = []


def _read_bounded_receipt(
    receipt: Path,
    *,
    label: str,
    maximum_bytes: int,
) -> bytes:
    """Read one bounded receipt without following or racing a link."""
    try:
        metadata = receipt.lstat()
    except OSError as exc:
        raise SimctlError(f"cannot inspect {label} {receipt}: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SimctlError(f"{label} must be a single-link regular file: {receipt}")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = -1
    try:
        descriptor = os.open(receipt, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
        ):
            raise SimctlError(f"{label} changed while opening: {receipt}")
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, 64 * 1024):
            size += len(chunk)
            if size > maximum_bytes:
                raise SimctlError(f"{label} is too large: {receipt}")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        current = os.stat(receipt, follow_symlinks=False)
    except OSError as exc:
        raise SimctlError(f"cannot safely read {label} {receipt}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        or after.st_nlink != 1
        or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
        or current.st_nlink != 1
        or not stat.S_ISREG(current.st_mode)
    ):
        raise SimctlError(f"{label} changed while being read: {receipt}")
    return b"".join(chunks)


def _read_pending_adoption_source(root: Path, receipt: Path) -> str:
    """Safely read the original source path from an adoption receipt."""
    content = _read_bounded_receipt(
        receipt,
        label="bundle adoption receipt",
        maximum_bytes=_MAX_ADOPTION_RECEIPT_BYTES,
    )
    try:
        payload = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid bundle adoption receipt {receipt}: {exc}") from exc
    adoption = payload.get("adoption")
    source_path = adoption.get("source_path") if isinstance(adoption, dict) else None
    archive_path = adoption.get("archive_path") if isinstance(adoption, dict) else None
    transaction_path = (
        adoption.get("transaction_path") if isinstance(adoption, dict) else None
    )
    if not isinstance(source_path, str) or not source_path:
        raise ValueError(
            f"bundle adoption receipt lacks adoption.source_path: {receipt}"
        )
    if not isinstance(archive_path, str) or not archive_path:
        raise ValueError(
            f"bundle adoption receipt lacks adoption.archive_path: {receipt}"
        )
    if not isinstance(transaction_path, str) or not transaction_path:
        raise ValueError(
            f"bundle adoption receipt lacks adoption.transaction_path: {receipt}"
        )
    source = _canonical_adoption_path(source_path, field="source_path")
    destination = _canonical_adoption_path(archive_path, field="archive_path")
    transaction = _canonical_adoption_path(
        transaction_path,
        field="transaction_path",
    )
    if transaction != receipt.parent.resolve():
        raise ValueError(
            "bundle adoption transaction_path does not match the receipt location: "
            f"{transaction}"
        )
    return _validate_adoption_recovery(
        root,
        source=source,
        destination=destination,
        transaction=transaction,
    )


def _read_receiptless_adoption_source(root: Path, transaction: Path) -> str:
    """Recover the source from a committed marker after receipt unlink."""
    if transaction.is_symlink() or not transaction.is_dir():
        raise ValueError(
            f"receiptless adoption transaction must be a real directory: {transaction}"
        )
    try:
        entries = list(transaction.iterdir())
    except OSError as exc:
        raise ValueError(
            f"cannot inspect receiptless adoption transaction {transaction}: {exc}"
        ) from exc
    if entries:
        raise ValueError(
            f"receiptless adoption transaction is not empty: {transaction}"
        )
    match = _ADOPTION_TRANSACTION.fullmatch(transaction.name)
    if match is None:
        raise ValueError(f"invalid adoption transaction name: {transaction}")
    destination = transaction.parent / match.group(1)
    marker = destination / ".runops-archive.toml"
    content = _read_bounded_receipt(
        marker,
        label="bundle archive marker",
        maximum_bytes=_MAX_BUNDLE_MARKER_BYTES,
    )
    try:
        payload = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid bundle archive marker {marker}: {exc}") from exc
    bundle = payload.get("bundle")
    source_path = bundle.get("archived_from") if isinstance(bundle, dict) else None
    adopted_ids = bundle.get("adopted_run_ids") if isinstance(bundle, dict) else None
    if (
        not isinstance(source_path, str)
        or not source_path
        or not isinstance(adopted_ids, list)
        or not adopted_ids
        or any(not isinstance(item, str) or not item for item in adopted_ids)
    ):
        raise ValueError(
            f"bundle marker cannot prove receiptless adoption cleanup: {marker}"
        )
    source = _canonical_adoption_path(source_path, field="source_path")
    return _validate_adoption_recovery(
        root,
        source=source,
        destination=destination.resolve(),
        transaction=transaction.resolve(),
    )


def _canonical_adoption_path(raw: str, *, field: str) -> Path:
    path = Path(raw)
    if not path.is_absolute() or str(path) != raw:
        raise ValueError(f"bundle adoption {field} must be an absolute path: {raw!r}")
    canonical = path.parent.resolve() / path.name
    if canonical != path:
        raise ValueError(f"bundle adoption {field} must be canonical: {raw!r}")
    return path


def _validate_adoption_recovery(
    root: Path,
    *,
    source: Path,
    destination: Path,
    transaction: Path,
) -> str:
    """Prove that one adoption retry is project-contained and resumable."""
    runs_root = (root / "runs").resolve()
    archive_root = (runs_root / "_archive").resolve()
    try:
        relative = source.relative_to(runs_root)
    except ValueError as exc:
        raise ValueError(
            f"bundle adoption source is outside this project: {source}"
        ) from exc
    if not relative.parts or relative.parts[0] == "_archive":
        raise ValueError(
            f"bundle adoption source is not in the active Run view: {source}"
        )
    try:
        destination.relative_to(archive_root)
    except ValueError as exc:
        raise ValueError(
            f"bundle adoption destination escapes managed storage: {destination}"
        ) from exc
    if transaction.parent != destination.parent:
        raise ValueError(
            f"bundle adoption transaction is not beside its destination: {transaction}"
        )
    match = _ADOPTION_TRANSACTION.fullmatch(transaction.name)
    if match is None or match.group(1) != destination.name:
        raise ValueError(
            f"bundle adoption transaction does not match destination: {transaction}"
        )

    selected_archive_root = destination
    for _part in relative.parts:
        selected_archive_root = selected_archive_root.parent

    from runops.application.actions.bundle_archive import (
        default_bundle_archive_destination,
        inspect_bundle_adoption_recovery,
    )

    if (
        default_bundle_archive_destination(
            source,
            archive_root=selected_archive_root,
        )
        != destination
    ):
        raise ValueError(
            f"cannot verify archive root for bundle adoption: {destination}"
        )
    recovery = inspect_bundle_adoption_recovery(
        source,
        archive_root=selected_archive_root,
    )
    if recovery is None:
        raise ValueError(
            f"bundle adoption is not authoritatively recoverable: {transaction}"
        )
    if recovery.data.get("source_path") != str(source) or recovery.data.get(
        "archive_path"
    ) != str(destination):
        raise ValueError(
            f"bundle adoption recovery identity does not match: {transaction}"
        )
    return str(source)


def _suggest_actions(
    *,
    active_experiments: tuple[ActiveExperimentTriage, ...],
    run_summary: _RunSummary,
    test_summary: _TestAttemptSummary,
    test_attempt_age_days: int,
    diagnostic_count: int,
    expired_experiment_count: int,
    stale_staging_count: int,
) -> tuple[str, ...]:
    actions: list[str] = []
    for experiment in active_experiments:
        if experiment.expired:
            actions.append(
                f"Close or supersede expired Experiment {experiment.experiment_id}: "
                f"runo experiments close {experiment.experiment_id} "
                "--decision stop --outcome inconclusive --reason WHY"
            )
        elif experiment.decision == "pending":
            actions.append(
                f"Review pending Experiment {experiment.experiment_id}: "
                f"runo experiments review {experiment.experiment_id} "
                "--decision DECISION --reason WHY"
            )
    if run_summary.unreviewed_completed:
        actions.append(
            f"Review {run_summary.unreviewed_completed} completed Run(s): "
            "runo runs review RUN --reason WHY"
        )
    if test_summary.old_active:
        actions.append(
            f"Resolve {test_summary.old_active} old active TestAttempt(s) before "
            "cleanup: runo test list --json"
        )
    if test_summary.old_terminal:
        actions.append(
            f"Clean {test_summary.old_terminal} terminal TestAttempt(s) at least "
            f"{test_attempt_age_days} days old: "
            f"runo test clean --older-than-days {test_attempt_age_days}"
        )
    unassigned = (run_summary.by_experiment or {}).get(_UNASSIGNED_EXPERIMENT, 0)
    if unassigned:
        actions.append(
            f"Classify {unassigned} active formal Run(s) without an Experiment "
            "before expanding the workspace."
        )
    if stale_staging_count:
        noun = "directory" if stale_staging_count == 1 else "directories"
        actions.append(
            f"Inspect {stale_staging_count} stale unpublished transaction {noun} "
            "listed in staging diagnostics before removing it."
        )
    invalid_count = diagnostic_count - stale_staging_count - expired_experiment_count
    if invalid_count:
        noun = "record" if invalid_count == 1 else "records"
        actions.append(
            f"Resolve {invalid_count} invalid project {noun} listed in "
            "diagnostics before creating new state."
        )
    if not actions:
        actions.append("No cleanup blockers found; proceed with bounded planning.")
    return tuple(actions)


def _diagnostic(
    root: Path,
    *,
    section: str,
    code: str,
    path: Path,
    message: str,
) -> TriageDiagnostic:
    return TriageDiagnostic(
        section=section,
        code=code,
        path=_relative(path, root),
        message=message,
    )


def _relative(path: Path, root: Path) -> str:
    try:
        return path.absolute().relative_to(root).as_posix()
    except ValueError:
        return str(path.absolute())


def _sorted_counts(values: Counter[str]) -> dict[str, int]:
    return {key: values[key] for key in sorted(values)}


__all__ = [
    "DEFAULT_STAGING_AGE_HOURS",
    "DEFAULT_TEST_ATTEMPT_AGE_DAYS",
    "ActiveExperimentTriage",
    "TriageDiagnostic",
    "TriageReport",
    "build_triage_report",
]
