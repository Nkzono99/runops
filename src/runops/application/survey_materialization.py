"""Read-only Survey planning and explicitly bounded Run materialization."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import re
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runops.application.experiments import experiment_lock, resolve_experiment
from runops.application.run_budget import (
    enforce_experiment_run_budget,
    enforce_project_unreviewed_completed_budget,
    persist_manifest_budget_usage,
)
from runops.application.run_creation import (
    build_standalone_manifest_metadata,
    create_prepared_run,
    load_adapter_for_simulator,
    load_launcher_for_name,
    materialized_point_identity_is_valid,
    plan_survey_runs,
    release_unused_run_id,
    require_formal_run_target,
    reserve_run_id,
)
from runops.application.run_discovery import collect_run_manifests_strict
from runops.application.run_namespace import run_namespace_guard
from runops.application.state_root import require_project_state_root
from runops.core.case import parse_walltime_hours
from runops.core.discovery import collect_existing_run_ids
from runops.core.exceptions import SimctlError
from runops.core.experiment import (
    ExperimentData,
    discover_experiments,
    experiment_is_expired,
    load_experiment,
)
from runops.core.manifest import ManifestData, read_manifest
from runops.core.models.run_creation import SurveyExpansionPlan
from runops.core.project import ProjectConfig, load_project
from runops.core.run.curation import has_valid_run_review
from runops.core.site import load_site_profile
from runops.core.survey import (
    SurveyPoint,
    count_survey_points,
    generate_display_name,
    generate_semantic_label,
    load_survey,
    preview_run_directory_name,
)

_POINT_ALIAS = re.compile(r"^p(?P<ordinal>[1-9][0-9]*)$")
_COMPLETED_EQUIVALENT_STATES = frozenset({"completed", "archived", "purged"})


class SurveyMaterializationError(SimctlError):
    """Raised when a Survey fails a planning or materialization gate."""


@dataclass(frozen=True)
class SurveyPlanPoint:
    """Small presentation view of one lazily expanded candidate."""

    ref: str
    point_id: str
    ordinal: int
    params: dict[str, Any]
    display_name: str
    directory_preview: str


@dataclass(frozen=True)
class SurveyPlanPreview:
    """Bounded preview; candidate metadata is not a persisted plan entity."""

    plan: SurveyExpansionPlan
    points: tuple[SurveyPlanPoint, ...]
    offset: int
    limit: int
    admission_issues: tuple[str, ...]


@dataclass(frozen=True)
class MaterializedPoint:
    """Outcome for one explicitly selected Survey point."""

    ref: str
    point_id: str
    ordinal: int
    run_id: str
    run_dir: Path
    reused: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurveyMaterializationResult:
    """Idempotent result of applying one immutable Survey plan hash."""

    survey_id: str
    plan_hash: str
    candidate_count: int
    points: tuple[MaterializedPoint, ...]

    @property
    def created_count(self) -> int:
        return sum(not point.reused for point in self.points)

    @property
    def reused_count(self) -> int:
        return sum(point.reused for point in self.points)


def preview_survey_plan(
    project: ProjectConfig,
    survey_dir: Path,
    *,
    offset: int = 0,
    limit: int = 50,
) -> SurveyPlanPreview:
    """Return a bounded, read-only candidate preview with admission issues."""
    if offset < 0:
        raise SurveyMaterializationError("plan offset must be non-negative")
    if limit < 1 or limit > 1000:
        raise SurveyMaterializationError("plan limit must be between 1 and 1000")

    plan = plan_survey_runs(project, survey_dir)
    issues = _plan_admission_issues(project, plan)
    points: list[SurveyPlanPoint] = []
    stop = offset + limit
    for point in plan.iter_points():
        if point.ordinal <= offset:
            continue
        if point.ordinal > stop:
            break
        points.append(_point_preview(plan, point))
    return SurveyPlanPreview(
        plan=plan,
        points=tuple(points),
        offset=offset,
        limit=limit,
        admission_issues=tuple(issues),
    )


def materialize_survey_points(
    project: ProjectConfig,
    survey_dir: Path,
    *,
    expected_plan_hash: str,
    point_refs: Sequence[str] = (),
    all_points: bool = False,
) -> SurveyMaterializationResult:
    """Create only selected points after rechecking every bounded gate.

    Existing ``survey + point_id`` manifests are returned as reused.  This
    makes a retry safe after a process dies between individual Run commits.
    """
    if not expected_plan_hash.strip():
        raise SurveyMaterializationError(
            "materialization requires --expect-plan with the previewed hash"
        )
    clean_refs = tuple(dict.fromkeys(ref.strip() for ref in point_refs if ref.strip()))
    if all_points == bool(clean_refs):
        raise SurveyMaterializationError(
            "select exactly one of explicit --point values or --all"
        )

    root = project.root_dir.resolve()
    project_file = root / "runops.toml"
    project_is_persisted = project_file.exists() or project_file.is_symlink()
    if survey_dir.is_symlink():
        raise SurveyMaterializationError(
            f"Survey target must not be a symlink: {survey_dir}"
        )
    target = survey_dir.resolve()
    _require_managed_survey_target(root, target)
    with (
        experiment_lock(root),
        _survey_materialization_lock(root, target),
        run_namespace_guard(root),
    ):
        plan = plan_survey_runs(project, target)
        if plan.plan_hash != expected_plan_hash:
            raise SurveyMaterializationError(
                "Survey plan is stale: expected "
                f"{expected_plan_hash}, current {plan.plan_hash}; preview again"
            )
        experiment = _require_materialization_admission(project, plan)
        _reject_obviously_unbounded_selection(
            project,
            plan,
            experiment,
            ref_count=len(clean_refs),
            all_points=all_points,
        )
        selected = _select_points(plan, clean_refs, all_points=all_points)
        existing = _collect_existing_records(root)
        reusable, new_points = _partition_reusable(plan, selected, existing)
        _enforce_materialization_budget(
            project,
            plan,
            experiment,
            selected_count=len(selected),
            new_count=len(new_points),
            new_points=new_points,
            existing=existing,
        )

        adapter = load_adapter_for_simulator(
            project,
            plan.effective_case.simulator,
        )
        launcher = load_launcher_for_name(
            project,
            plan.effective_case.launcher,
        )
        site = load_site_profile(root)
        known_ids = collect_existing_run_ids(root / "runs")
        outcomes: dict[str, MaterializedPoint] = dict(reusable)
        for point in new_points:
            display_name = _point_display_name(plan, point)
            run_id = reserve_run_id(root, known_ids)

            def commit_guard(
                point: SurveyPoint = point,
                run_id: str = run_id,
            ) -> None:
                _assert_materialization_current(
                    project,
                    target,
                    expected_plan_hash,
                    point=point,
                    reserved_run_id=run_id,
                    expected_experiment=experiment,
                    project_is_persisted=project_is_persisted,
                )

            created = create_prepared_run(
                parent_dir=target,
                case_data=plan.effective_case,
                project=project,
                adapter=adapter,
                launcher=launcher,
                site=site,
                existing_ids=known_ids,
                params=point.params,
                display_name=display_name,
                naming=plan.survey_data.naming,
                survey_id=plan.survey_data.id,
                variation_keys=list(plan.variation_keys),
                reserved_run_id=run_id,
                manifest_metadata=_manifest_metadata(plan, point, root, experiment),
                commit_guard=commit_guard,
            )
            if created.reused:
                release_unused_run_id(root, run_id)
            else:
                known_ids.add(run_id)
            outcomes[point.point_id] = MaterializedPoint(
                ref=_point_ref(point),
                point_id=point.point_id,
                ordinal=point.ordinal,
                run_id=created.run_info.run_id,
                run_dir=created.run_info.run_dir,
                reused=created.reused,
                warnings=created.warnings,
            )

        if experiment is not None and new_points:
            try:
                for outcome in outcomes.values():
                    if not outcome.reused:
                        persist_manifest_budget_usage(
                            root,
                            outcome.run_dir,
                            read_manifest(outcome.run_dir),
                        )
            except SimctlError as exc:
                warning = (
                    "Runs committed; Experiment usage ledger will be rebuilt "
                    f"from their manifests ({exc})"
                )
                outcomes = {
                    point_id: MaterializedPoint(
                        ref=outcome.ref,
                        point_id=outcome.point_id,
                        ordinal=outcome.ordinal,
                        run_id=outcome.run_id,
                        run_dir=outcome.run_dir,
                        reused=outcome.reused,
                        warnings=(
                            outcome.warnings
                            if outcome.reused
                            else (*outcome.warnings, warning)
                        ),
                    )
                    for point_id, outcome in outcomes.items()
                }

        return SurveyMaterializationResult(
            survey_id=plan.survey_data.id,
            plan_hash=plan.plan_hash,
            candidate_count=plan.candidate_count,
            points=tuple(outcomes[point.point_id] for point in selected),
        )


def _plan_admission_issues(
    project: ProjectConfig,
    plan: SurveyExpansionPlan,
) -> list[str]:
    issues: list[str] = []
    survey = plan.survey_data
    raw_survey = survey.raw.get("survey", {})
    if not isinstance(raw_survey, dict) or not str(raw_survey.get("id", "")).strip():
        issues.append("materialization requires an explicit survey.id")
    if project.experiment_policy.require_experiment and not survey.experiment_id:
        issues.append("project policy requires survey.experiment_id")
    if not survey.phase:
        issues.append("materialization requires survey.phase")
    if not survey.intent.purpose:
        issues.append("materialization requires intent.purpose")
    if survey.budget.max_materialized_runs is None:
        issues.append(
            "survey budget.max_materialized_runs is unset; project default applies"
        )

    if survey.experiment_id:
        try:
            experiments = discover_experiments(project.root_dir)
        except SimctlError as exc:
            issues.append(str(exc))
            experiments = ()
        active_count = sum(item.lifecycle == "active" for item in experiments)
        if active_count > project.experiment_policy.max_active_experiments:
            issues.append(
                "active Experiment WIP limit is exceeded: "
                f"{active_count}/{project.experiment_policy.max_active_experiments}"
            )
        try:
            experiment = load_experiment(
                resolve_experiment(project.root_dir, survey.experiment_id)
            )
        except SimctlError as exc:
            issues.append(str(exc))
        else:
            if experiment.lifecycle != "active":
                issues.append(
                    f"Experiment {experiment.id} is {experiment.lifecycle}, not active"
                )
            if experiment_is_expired(experiment):
                issues.append(
                    f"Experiment {experiment.id} expired at "
                    f"{experiment.budget.expires_at}"
                )
            cumulative_points = _experiment_planned_points(
                project.root_dir,
                experiment.id,
            )
            if cumulative_points > experiment.budget.max_planned_points:
                issues.append(
                    f"cumulative candidate_count {cumulative_points} exceeds "
                    "Experiment "
                    f"max_planned_points {experiment.budget.max_planned_points}"
                )
            if survey.intent.purpose and survey.intent.purpose != experiment.intent:
                issues.append(
                    f"Survey purpose {survey.intent.purpose!r} does not match "
                    f"Experiment intent {experiment.intent!r}"
                )
            if survey.phase in {"main", "followup"} and experiment.decision != "expand":
                issues.append(
                    f"{survey.phase} materialization requires "
                    "Experiment decision=expand"
                )
            if experiment.decision in {"revise", "stop", "accept"}:
                issues.append(
                    f"Experiment decision={experiment.decision} blocks further "
                    "materialization"
                )
    return issues


def _experiment_planned_points(project_root: Path, experiment_id: str) -> int:
    """Count candidates across all durable Survey definitions for an Experiment."""
    total = 0
    for path in _iter_managed_survey_files(project_root):
        try:
            survey = load_survey(path.parent)
        except SimctlError as exc:
            raise SurveyMaterializationError(
                "cannot safely account Survey budget because a managed Survey "
                f"is invalid at {path.parent}: {exc}"
            ) from exc
        if survey.experiment_id != experiment_id:
            continue
        total += count_survey_points(survey.axes, survey.linked)
    return total


def _require_materialization_admission(
    project: ProjectConfig,
    plan: SurveyExpansionPlan,
) -> ExperimentData | None:
    blocking = [
        issue
        for issue in _plan_admission_issues(project, plan)
        if "project default applies" not in issue
    ]
    if blocking:
        raise SurveyMaterializationError("; ".join(blocking))
    if not plan.survey_data.experiment_id:
        return None
    build_standalone_manifest_metadata(
        project,
        experiment_id=plan.survey_data.experiment_id,
        purpose=plan.survey_data.intent.purpose or "",
        created_by=plan.survey_data.intent.created_by,
    )
    return load_experiment(
        resolve_experiment(project.root_dir, plan.survey_data.experiment_id)
    )


def _require_managed_survey_target(project_root: Path, survey_dir: Path) -> None:
    try:
        require_formal_run_target(project_root, survey_dir)
    except SimctlError as exc:
        raise SurveyMaterializationError(
            f"formal Survey must be in the active project runs/ tree: {survey_dir}"
        ) from exc
    if not survey_dir.is_dir():
        raise SurveyMaterializationError(
            f"Survey target must be a real directory: {survey_dir}"
        )

    current = load_survey(survey_dir)
    duplicates: list[Path] = []
    for candidate in _iter_managed_survey_files(project_root):
        parent = candidate.parent.resolve()
        if parent == survey_dir:
            continue
        try:
            other = load_survey(parent)
        except SimctlError as exc:
            raise SurveyMaterializationError(
                "cannot verify survey.id uniqueness because a managed Survey is "
                f"invalid at {parent}: {exc}"
            ) from exc
        if other.id == current.id:
            duplicates.append(parent)
    if duplicates:
        raise SurveyMaterializationError(
            f"duplicate survey.id {current.id!r} also found at "
            + ", ".join(str(path) for path in duplicates)
        )


def _iter_managed_survey_files(project_root: Path) -> Iterator[Path]:
    """Yield Survey definitions while treating formal Runs as terminal nodes."""
    runs_root = project_root / "runs"
    if not runs_root.exists() and not runs_root.is_symlink():
        return
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise SurveyMaterializationError(
            f"cannot safely inspect managed Surveys because runs/ is unsafe: "
            f"{runs_root}"
        )

    walk_error: OSError | None = None

    def remember_error(error: OSError) -> None:
        nonlocal walk_error
        walk_error = error

    for dirpath, dirnames, filenames in os.walk(
        runs_root,
        topdown=True,
        followlinks=False,
        onerror=remember_error,
    ):
        if walk_error is not None:
            raise SurveyMaterializationError(
                f"cannot safely inspect managed Surveys: {walk_error}"
            ) from walk_error
        current = Path(dirpath)
        if current.name.startswith((".tmp-", ".delete-")):
            dirnames[:] = []
            continue

        # A formal Run owns everything below its manifest boundary.  Simulator
        # inputs/artifacts named survey.toml are payload, never Survey entities.
        if "manifest.toml" in filenames:
            dirnames[:] = []
            continue

        retained: list[str] = []
        for dirname in dirnames:
            if dirname.startswith((".tmp-", ".delete-")):
                continue
            child = current / dirname
            if child.is_symlink():
                raise SurveyMaterializationError(
                    "cannot safely inspect managed Surveys because a directory "
                    f"is a symlink: {child}"
                )
            retained.append(dirname)
        dirnames[:] = retained

        if "survey.toml" not in filenames:
            continue
        survey_file = current / "survey.toml"
        try:
            survey_stat = os.stat(survey_file, follow_symlinks=False)
        except OSError as exc:
            raise SurveyMaterializationError(
                f"cannot safely inspect managed Survey {survey_file}: {exc}"
            ) from exc
        if not stat.S_ISREG(survey_stat.st_mode) or survey_stat.st_nlink != 1:
            raise SurveyMaterializationError(
                f"managed survey.toml must be a single-link regular file: {survey_file}"
            )
        yield survey_file

    if walk_error is not None:
        raise SurveyMaterializationError(
            f"cannot safely inspect managed Surveys: {walk_error}"
        ) from walk_error


def _reject_obviously_unbounded_selection(
    project: ProjectConfig,
    plan: SurveyExpansionPlan,
    experiment: ExperimentData | None,
    *,
    ref_count: int,
    all_points: bool,
) -> None:
    cap = (
        plan.survey_data.budget.max_materialized_runs
        or project.experiment_policy.default_max_materialized_runs
    )
    if experiment is not None:
        cap = min(cap, experiment.budget.max_materialized_runs)
    requested = plan.candidate_count if all_points else ref_count
    if requested > cap:
        raise SurveyMaterializationError(
            "Survey materialization cap exceeded: "
            f"selection requests {requested} points but the hard cap is {cap}"
        )


def _select_points(
    plan: SurveyExpansionPlan,
    refs: Sequence[str],
    *,
    all_points: bool,
) -> tuple[SurveyPoint, ...]:
    wanted = set(refs)
    selected: list[SurveyPoint] = []
    matched: set[str] = set()
    selected_ids: set[str] = set()
    alias_ordinals = {
        int(match.group("ordinal"))
        for ref in wanted
        if (match := _POINT_ALIAS.fullmatch(ref)) is not None
    }
    needs_hash_scan = any(_POINT_ALIAS.fullmatch(ref) is None for ref in wanted)

    for point in plan.iter_points():
        ref = _point_ref(point)
        is_selected = all_points or ref in wanted or point.point_id in wanted
        if is_selected:
            if point.point_id in selected_ids:
                raise SurveyMaterializationError(
                    "selected Survey points contain duplicate effective parameters: "
                    f"{point.point_id}"
                )
            selected_ids.add(point.point_id)
            selected.append(point)
            if ref in wanted:
                matched.add(ref)
            if point.point_id in wanted:
                matched.add(point.point_id)

        if (
            not all_points
            and not needs_hash_scan
            and alias_ordinals
            and point.ordinal >= max(alias_ordinals)
        ):
            break

    missing = wanted - matched
    if missing:
        raise SurveyMaterializationError(
            "unknown Survey point reference(s): " + ", ".join(sorted(missing))
        )
    if not selected:
        raise SurveyMaterializationError("no Survey points were selected")
    return tuple(selected)


@dataclass(frozen=True)
class _ExistingRun:
    run_dir: Path
    manifest: ManifestData


def _collect_existing_records(project_root: Path) -> tuple[_ExistingRun, ...]:
    try:
        records = collect_run_manifests_strict(project_root / "runs")
    except (SimctlError, OSError, TypeError, ValueError) as exc:
        raise SurveyMaterializationError(
            "cannot safely account existing formal Runs because strict namespace "
            f"validation failed: {exc}"
        ) from exc
    return tuple(_ExistingRun(run_dir, manifest) for run_dir, manifest in records)


def _partition_reusable(
    plan: SurveyExpansionPlan,
    selected: Sequence[SurveyPoint],
    existing: Sequence[_ExistingRun],
) -> tuple[dict[str, MaterializedPoint], list[SurveyPoint]]:
    by_point: dict[str, list[_ExistingRun]] = {}
    for record in existing:
        origin = record.manifest.origin
        intent = record.manifest.intent
        origin_survey = str(origin.get("survey", "")).strip()
        intent_survey = str(intent.get("survey_id", "")).strip()
        expected_survey = plan.survey_data.id
        associated = expected_survey in {origin_survey, intent_survey}
        if not associated:
            continue
        intent_experiment = str(intent.get("experiment_id", "")).strip()
        expected_experiment = plan.survey_data.experiment_id
        if (
            origin_survey != expected_survey
            or intent_survey != expected_survey
            or intent_experiment != expected_experiment
        ):
            raise SurveyMaterializationError(
                "existing Run has an inconsistent Survey owner edge at "
                f"{record.run_dir}: expected survey={expected_survey!r} and "
                f"experiment={expected_experiment!r}, got "
                f"origin.survey={origin_survey!r}, "
                f"intent.survey_id={intent_survey!r}, and "
                f"intent.experiment_id={intent_experiment!r}"
            )
        point_id = str(
            record.manifest.identity.get("point_id", "") or origin.get("point_id", "")
        )
        if point_id:
            by_point.setdefault(point_id, []).append(record)

    reusable: dict[str, MaterializedPoint] = {}
    new_points: list[SurveyPoint] = []
    for point in selected:
        matches = by_point.get(point.point_id, [])
        if len(matches) > 1:
            paths = ", ".join(str(item.run_dir) for item in matches)
            raise SurveyMaterializationError(
                f"duplicate materializations for {point.point_id}: {paths}"
            )
        if not matches:
            new_points.append(point)
            continue
        record = matches[0]
        recorded_plan = str(record.manifest.identity.get("plan_hash", ""))
        if recorded_plan != plan.plan_hash:
            raise SurveyMaterializationError(
                f"existing point {point.point_id} belongs to plan "
                f"{recorded_plan or '(missing)'}, not {plan.plan_hash}; "
                "use a new immutable survey.id for a revised plan"
            )
        if record.manifest.params_snapshot != point.params:
            raise SurveyMaterializationError(
                f"existing point {point.point_id} has a mismatched parameter snapshot"
            )
        if not materialized_point_identity_is_valid(
            record.run_dir,
            record.manifest,
        ):
            raise SurveyMaterializationError(
                f"existing point {point.point_id} scientific identity no longer "
                "matches its materialized input and provenance"
            )
        reusable[point.point_id] = MaterializedPoint(
            ref=_point_ref(point),
            point_id=point.point_id,
            ordinal=point.ordinal,
            run_id=str(record.manifest.run.get("id", "")),
            run_dir=record.run_dir,
            reused=True,
        )
    return reusable, new_points


def _enforce_materialization_budget(
    project: ProjectConfig,
    plan: SurveyExpansionPlan,
    experiment: ExperimentData | None,
    *,
    selected_count: int,
    new_count: int,
    new_points: Sequence[SurveyPoint],
    existing: Sequence[_ExistingRun],
) -> None:
    del selected_count  # Selection is reported; only newly created Runs consume budget.
    survey = plan.survey_data
    survey_records = [
        record
        for record in existing
        if record.manifest.origin.get("survey") == survey.id
    ]
    survey_cap = (
        survey.budget.max_materialized_runs
        or project.experiment_policy.default_max_materialized_runs
    )
    if len(survey_records) + new_count > survey_cap:
        raise SurveyMaterializationError(
            "Survey materialization cap exceeded: "
            f"{len(survey_records)} existing + {new_count} new > {survey_cap}"
        )

    per_run_hours = _planned_core_hours_per_run(plan)
    survey_existing_hours = sum(
        _manifest_core_hours(record.manifest) for record in survey_records
    )
    if (
        survey.budget.max_core_hours is not None
        and survey_existing_hours + per_run_hours * new_count
        > survey.budget.max_core_hours
    ):
        raise SurveyMaterializationError(
            "Survey core-hour budget exceeded by selected points"
        )

    try:
        if experiment is None:
            if new_count:
                enforce_project_unreviewed_completed_budget(project)
            return
        enforce_experiment_run_budget(
            project,
            experiment,
            new_count=new_count,
            new_core_hours=per_run_hours * new_count,
            reservation_tokens=tuple(
                f"survey:{survey.id}:{point.point_id}" for point in new_points
            ),
            persist=False,
        )
    except SimctlError as exc:
        raise SurveyMaterializationError(str(exc)) from exc


def _manifest_metadata(
    plan: SurveyExpansionPlan,
    point: SurveyPoint,
    project_root: Path,
    experiment: ExperimentData | None,
) -> dict[str, dict[str, Any]]:
    survey = plan.survey_data
    try:
        survey_path = survey.survey_dir.relative_to(project_root).as_posix()
    except ValueError:
        survey_path = str(survey.survey_dir)
    baseline_runs = list(experiment.baseline.run_ids) if experiment else []
    baseline_reason = experiment.baseline.reason if experiment else ""
    baseline_run = survey.intent.baseline_run or (
        baseline_runs[0] if baseline_runs else ""
    )
    return {
        "origin": {
            "survey_path": survey_path,
        },
        "intent": {
            "experiment_id": survey.experiment_id,
            "survey_id": survey.id,
            "purpose": survey.intent.purpose or "",
            "phase": survey.phase or "",
            "information_gap": survey.intent.information_gap,
            "baseline_run": baseline_run,
            "baseline_runs": baseline_runs,
            "baseline_reason": baseline_reason,
            "created_by": survey.intent.created_by,
            "goal_id": survey.intent.goal_id,
        },
        "identity": {
            "point_id": point.point_id,
            "plan_hash": plan.plan_hash,
            "budget_reservation": f"survey:{survey.id}:{point.point_id}",
        },
        "curation": {
            "review_status": "unreviewed",
            "reason": "",
            "reviewed_at": "",
            "reviewed_by": "",
        },
        "storage": {"tier": "hot", "form": "full"},
    }


def _point_preview(
    plan: SurveyExpansionPlan,
    point: SurveyPoint,
) -> SurveyPlanPoint:
    display_name = _point_display_name(plan, point)
    return SurveyPlanPoint(
        ref=_point_ref(point),
        point_id=point.point_id,
        ordinal=point.ordinal,
        params=dict(point.params),
        display_name=display_name,
        directory_preview=preview_run_directory_name(
            display_name,
            plan.survey_data.naming,
        ),
    )


def _point_display_name(plan: SurveyExpansionPlan, point: SurveyPoint) -> str:
    if plan.survey_data.naming_template:
        return generate_display_name(
            plan.survey_data.naming_template,
            point.params,
        )
    return generate_semantic_label(
        plan.base_case.params,
        point.params,
        list(plan.variation_keys),
        plan.survey_data.naming,
    )


def _point_ref(point: SurveyPoint) -> str:
    return f"p{point.ordinal:04d}"


def _assert_materialization_current(
    project: ProjectConfig,
    survey_dir: Path,
    expected_plan_hash: str,
    *,
    point: SurveyPoint,
    reserved_run_id: str,
    expected_experiment: ExperimentData | None,
    project_is_persisted: bool,
) -> None:
    """Recheck the full Survey and budget boundary around Run publication."""
    # Includes the formal target check at both sides of the staged-directory
    # publication CAS through create_prepared_run's commit guard.
    current_project = (
        load_project(project.root_dir) if project_is_persisted else project
    )
    project_root = current_project.root_dir.resolve()
    _require_managed_survey_target(project_root, survey_dir)
    current_plan = plan_survey_runs(current_project, survey_dir)
    if current_plan.plan_hash != expected_plan_hash:
        raise SurveyMaterializationError(
            "Survey inputs changed while a Run was staged: expected plan "
            f"{expected_plan_hash}, current {current_plan.plan_hash}; preview again"
        )
    current_experiment = _require_materialization_admission(
        current_project,
        current_plan,
    )
    if current_experiment != expected_experiment:
        experiment_id = current_plan.survey_data.experiment_id or "(ownerless)"
        raise SurveyMaterializationError(
            f"Experiment {experiment_id} changed while a Survey Run was staged; "
            "retry materialization from the current definition"
        )

    records = _collect_existing_records(project_root)
    reusable, new_points = _partition_reusable(current_plan, (point,), records)
    published = reusable.get(point.point_id)
    if published is not None and published.run_id != reserved_run_id:
        raise SurveyMaterializationError(
            f"Survey point {point.point_id} was materialized concurrently as "
            f"{published.run_id}; retry to reuse that exact Run"
        )

    is_published = published is not None
    _enforce_materialization_budget(
        current_project,
        current_plan,
        current_experiment,
        selected_count=1,
        new_count=0 if is_published else 1,
        new_points=() if is_published else new_points,
        existing=records,
    )
    if is_published:
        # The Experiment budget API deliberately treats a zero increment as
        # idempotent and therefore skips its admission-only review gate.  This
        # call is the post-publication half of a new Run commit, so a concurrent
        # sync must still be allowed to close the gate and trigger rollback.
        _enforce_current_review_backlog(
            current_project,
            current_experiment,
            records,
        )


def _enforce_current_review_backlog(
    project: ProjectConfig,
    experiment: ExperimentData | None,
    records: Sequence[_ExistingRun],
) -> None:
    unreviewed = tuple(
        record
        for record in records
        if record.manifest.run.get("status") in _COMPLETED_EQUIVALENT_STATES
        and not has_valid_run_review(record.manifest.curation)
    )
    project_count = len(unreviewed)
    project_cap = project.experiment_policy.max_unreviewed_completed_runs
    if project_count >= project_cap and project_count > 0:
        raise SurveyMaterializationError(
            "project-wide unreviewed completed Run backlog reached its limit: "
            f"{project_count}/{project_cap}"
        )
    if experiment is None:
        return
    experiment_count = sum(
        record.manifest.intent.get("experiment_id") == experiment.id
        for record in unreviewed
    )
    experiment_cap = experiment.budget.max_unreviewed_runs
    if experiment_count >= experiment_cap and experiment_count > 0:
        raise SurveyMaterializationError(
            "Experiment unreviewed completed Run backlog reached its limit: "
            f"{experiment_count}/{experiment_cap}"
        )


def _planned_core_hours_per_run(plan: SurveyExpansionPlan) -> float:
    if plan.candidate_count < 1:
        return 0.0
    if plan.estimated_core_hours is None:
        raise SurveyMaterializationError(
            "cannot enforce core-hour budget because job.walltime is invalid"
        )
    return plan.estimated_core_hours / plan.candidate_count


def _manifest_core_hours(manifest: ManifestData) -> float:
    job = manifest.job
    walltime = parse_walltime_hours(str(job.get("walltime", "")))
    if walltime is None:
        run_id = str(manifest.run.get("id", "unknown"))
        raise SurveyMaterializationError(
            f"cannot enforce Survey core-hour budget: Run {run_id} has invalid "
            "job.walltime"
        )
    processes = _positive_int(job.get("processes"))
    cores = _positive_int(job.get("cores"))
    if processes:
        width = processes * max(cores, 1)
    else:
        width = _positive_int(job.get("ntasks")) or 1
    return walltime * width


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return 0
    return value


@contextmanager
def _survey_materialization_lock(
    project_root: Path,
    survey_dir: Path,
) -> Iterator[None]:
    state_dir = require_project_state_root(project_root)
    digest = hashlib.sha256(str(survey_dir).encode("utf-8")).hexdigest()[:16]
    path = state_dir / f"survey-{digest}.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise SurveyMaterializationError(
            f"failed to open Survey materialization lock {path}: {exc}"
        ) from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)


__all__ = [
    "MaterializedPoint",
    "SurveyMaterializationError",
    "SurveyMaterializationResult",
    "SurveyPlanPoint",
    "SurveyPlanPreview",
    "materialize_survey_points",
    "preview_survey_plan",
]
