"""``new``, ``new --from``, ``sweep``, ``case new`` (SPEC §5, §7.3, §7.6)."""

from __future__ import annotations

import itertools
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from runops.adapters.base import RuntimeInfo, exe_str
from runops.adapters.registry import optional
from runops.case import (
    CASE_FILE,
    JOB_KEYS,
    Case,
    changed_keys,
    core_hours,
    list_case_names,
    load_case,
    make_label,
    slugify,
)
from runops.errors import RunError, UsageError
from runops.manifest import MANIFEST_FILE, SCHEMA_VERSION, Manifest
from runops.ops.common import SimContext, resolve_dest, sim_context
from runops.ops.submit import write_job_for
from runops.project import SCRATCH_DIR, Project
from runops.runtime import resolve_runtime
from runops.util import hash_tree, move_noreplace, now_iso, parse_value


@dataclass
class RunSpec:
    params: dict[str, Any]
    changed: list[str]
    label: str
    parent: Path
    sweep: str = ""
    job: dict[str, Any] = field(default_factory=dict)
    job_changed: list[str] = field(default_factory=list)


@dataclass
class CreateRequest:
    case: str
    sets: dict[str, Any] = field(default_factory=dict)
    why: str = ""
    label: str = ""
    tags: list[str] = field(default_factory=list)
    scratch: bool = False
    dest: str = ""
    created_by: str = "human"
    from_run: str = ""
    continue_run: bool = False
    job: dict[str, Any] = field(default_factory=dict)  # --job overrides of [job]
    job_from_case: bool = False  # with --from: take [job] from the case, not the source run


@dataclass
class CreateResult:
    manifests: list[Manifest]
    warnings: list[str]
    changes: list[str] = field(default_factory=list)  # input and resource differences, shown


@dataclass
class SweepPoint:
    ref: str
    params: dict[str, Any]
    values: dict[str, Any]
    label: str


@dataclass
class SweepPlan:
    case: Case
    sweep_label: str
    parent: Path
    points: list[SweepPoint]
    core_hours: float
    job: dict[str, Any] = field(default_factory=dict)


def parse_sets(items: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        key, sep, raw = item.partition("=")
        key = key.strip()
        if not sep or not key:
            raise UsageError(f"--set expects key=value, got {item!r}")
        if key in result:
            raise UsageError(f"--set {key} given more than once")
        result[key] = parse_value(raw.strip())
    return result


def parse_job(items: list[str]) -> dict[str, Any]:
    """``--job key=value``: a run's own ``[job]`` values (walltime, processes, ...)."""
    result: dict[str, Any] = {}
    for item in items:
        key, sep, raw = item.partition("=")
        key = key.strip()
        if not sep or not key:
            raise UsageError(f"--job expects key=value, got {item!r}")
        if key not in JOB_KEYS:
            raise UsageError(f"--job {key}: not a job key ({', '.join(sorted(JOB_KEYS))})")
        if key in result:
            raise UsageError(f"--job {key} given more than once")
        value = parse_value(raw.strip())
        # A walltime such as 72:00:00 is not a TOML literal; keep it as text.
        result[key] = raw.strip() if key == "walltime" else value
    return result


def _job_keys(job: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in job.items() if k in JOB_KEYS}


def _diff(label: str, before: dict[str, Any], after: dict[str, Any]) -> str:
    keys = [k for k in after if before.get(k) != after[k]]
    keys += [k for k in before if k not in after]
    if not keys:
        return ""
    parts = [f"{k} {before.get(k, '-')} -> {after.get(k, '-')}" for k in keys]
    return f"{label}: " + ", ".join(parts)


def parse_sweep_sets(items: list[str]) -> dict[str, list[Any]]:
    axes: dict[str, list[Any]] = {}
    for item in items:
        key, sep, raw = item.partition("=")
        key = key.strip()
        if not sep or not key:
            raise UsageError(f"--set expects key=v1,v2,..., got {item!r}")
        if key in axes:
            raise UsageError(f"--set {key} given more than once")
        values = [parse_value(v.strip()) for v in _split_values(raw)]
        if not values:
            raise UsageError(f"--set {key}: no values")
        axes[key] = values
    if not axes:
        raise UsageError("sweep needs at least one --set key=v1,v2,...")
    return axes


def parse_sweep_names(items: list[str], axes: dict[str, list[Any]]) -> dict[str, list[str]]:
    """``--names KEY=n1,n2,...``: a short label for each value of a swept KEY."""
    names: dict[str, list[str]] = {}
    for item in items:
        key, sep, raw = item.partition("=")
        key = key.strip()
        if not sep or not key:
            raise UsageError(f"--names expects KEY=n1,n2,..., got {item!r}")
        if key not in axes:
            raise UsageError(f"--names {key}: not a swept key ({', '.join(axes)})")
        if key in names:
            raise UsageError(f"--names {key} given more than once")
        values = [slugify(v.strip(), 80) for v in raw.split(",")]
        if len(values) != len(axes[key]):
            raise UsageError(f"--names {key}: {len(values)} names for {len(axes[key])} values")
        if not all(values) or len(set(values)) != len(values):
            raise UsageError(f"--names {key}: names must be non-empty and distinct")
        names[key] = values
    return names


def _split_values(raw: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for char in raw:
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [p for p in parts if p.strip()]


def _dest_parent(project: Project, case: Case, dest: str, scratch: bool) -> Path:
    if scratch and not dest:
        return project.runs_dir / SCRATCH_DIR
    if not dest:
        return project.runs_dir / case.name
    return resolve_dest(project, dest)


def create_run(project: Project, request: CreateRequest) -> CreateResult:
    """Create one run from a case, or derived from another run (``--from``)."""
    source: Manifest | None = None
    if request.from_run:
        source = project.resolve_run(request.from_run)
        case_name = source.case
    else:
        case_name = request.case
    if not case_name:
        raise UsageError("a CASE (or --from RUN) is required")
    case = load_case(project.cases_dir, case_name)
    if request.continue_run and source is None:
        raise UsageError("--continue requires --from RUN")

    base = dict(case.params)
    params = dict(source.params if source else case.params)
    params.update(request.sets)
    changed = changed_keys(base, params)
    if request.label:
        label = slugify(request.label, project.config.defaults.label_max_length)
    else:
        label = make_label(changed, params, case.aliases, project.config.defaults.label_max_length)
        if request.continue_run:
            label = slugify(
                f"{label or source.id if source else label}-cont",
                project.config.defaults.label_max_length,
            )
    # A derived run keeps the resources of its source, so a change of processes or
    # walltime does not need an edit of the case; --job overrides single values.
    if source is not None and not request.job_from_case:
        job = _job_keys(source.job)
    else:
        job = dict(case.job)
    job.update(request.job)
    parent = _dest_parent(project, case, request.dest, request.scratch)
    spec = RunSpec(
        params=params,
        changed=changed,
        label=label,
        parent=parent,
        job=job,
        job_changed=[k for k in job if case.job.get(k) != job[k]],
    )
    result = _materialize(project, case, [spec], request, source=source)
    if source is not None:
        against = f"vs {source.id}"
        result.changes += [
            line
            for line in (
                _diff(f"params {against}", source.params, params),
                _diff(f"job {against}", _job_keys(source.job), job),
            )
            if line
        ]
    else:
        line = _diff("job vs case", dict(case.job), job)
        if line:
            result.changes.append(line)
    if source is not None:
        recorded = str(source.section("origin").get("case_input_hash", ""))
        if recorded and recorded != case.input_hash():
            # Inputs come from the case as it is now, not as it was for the source.
            result.warnings.append(
                f"case {case.name!r} input files changed since {source.id} was created; "
                f"{result.manifests[0].id} differs from it by more than the inherited params"
            )
    return result


def plan_sweep(
    project: Project,
    case_name: str,
    axes: dict[str, list[Any]],
    *,
    sweep_label: str = "",
    limit: int | None = None,
    dest: str = "",
    names: dict[str, list[str]] | None = None,
    job: dict[str, Any] | None = None,
) -> SweepPlan:
    case = load_case(project.cases_dir, case_name)
    run_job = {**case.job, **(job or {})}
    keys = list(axes)
    names = names or {}
    combos = list(itertools.product(*(range(len(axes[k])) for k in keys)))
    if limit is not None:
        combos = combos[: max(limit, 0)]
    base_parent = _dest_parent(project, case, dest, False)
    if not sweep_label:
        day = datetime.now().astimezone().strftime("%Y%m%d")
        n = 1
        while (base_parent / f"sweep-{day}-{n:02d}").exists():
            n += 1
        sweep_label = f"sweep-{day}-{n:02d}"
    sweep_label = slugify(sweep_label, 80)
    parent = base_parent / sweep_label
    points: list[SweepPoint] = []
    for i, combo in enumerate(combos, start=1):
        params = dict(case.params)
        values = {k: axes[k][j] for k, j in zip(keys, combo, strict=True)}
        point_names = {k: names[k][j] for k, j in zip(keys, combo, strict=True) if k in names}
        params.update(values)
        points.append(
            SweepPoint(
                ref=f"p{i:04d}",
                params=params,
                values=values,
                label=make_label(
                    keys,
                    params,
                    case.aliases,
                    project.config.defaults.label_max_length,
                    point_names,
                ),
            )
        )
    hours = 0.0
    if points:
        hours = core_hours(run_job, project.config.site.resource_style) * len(points)
    return SweepPlan(case, sweep_label, parent, points, hours, run_job)


def apply_sweep(project: Project, plan: SweepPlan, request: CreateRequest) -> CreateResult:
    if not plan.points:
        raise UsageError("sweep has no points")
    specs = [
        RunSpec(
            params=p.params,
            changed=list(p.values),
            label=p.label,
            parent=plan.parent,
            sweep=plan.sweep_label,
            job=dict(plan.job),
            job_changed=[k for k in plan.job if plan.case.job.get(k) != plan.job[k]],
        )
        for p in plan.points
    ]
    result = _materialize(project, plan.case, specs, request, source=None)
    line = _diff("job vs case", dict(plan.case.job), plan.job)
    if line:
        result.changes.append(line)
    return result


def _materialize(
    project: Project,
    case: Case,
    specs: list[RunSpec],
    request: CreateRequest,
    *,
    source: Manifest | None,
) -> CreateResult:
    ctx = sim_context(project, case.simulator)
    warnings = list(case.warnings) + list(project.config.warnings)
    for spec in specs[:1]:
        warnings += [
            str(w) for w in optional(ctx.adapter, "validate_params", [], spec.params) or []
        ]
    runtime, runtime_warnings = resolve_runtime(project, ctx.sim, ctx.adapter)
    warnings += runtime_warnings
    launcher = project.config.launcher(case.launcher)
    created: list[Manifest] = []
    existing = _hash_index(project)
    with project.id_lock():
        ids = project.next_run_ids(len(specs))
        staged: list[tuple[Path, Path, Manifest]] = []
        try:
            for run_id, spec in zip(ids, specs, strict=True):
                name = f"{run_id}--{spec.label}" if spec.label else run_id
                final = spec.parent / name
                if final.exists():
                    raise UsageError(f"{final} already exists")
                # Stage beside the target so the final rename stays on one filesystem.
                stage = spec.parent / f".{name}.staging"
                manifest = _populate(
                    project,
                    case,
                    ctx,
                    runtime,
                    spec,
                    request,
                    run_id,
                    stage,
                    final,
                    source,
                )
                manifest.data["launcher"] = {"name": launcher.name}
                manifest.save()
                warnings += _duplicate_warnings(manifest, existing)
                staged.append((stage, final, manifest))
            for stage, final, _manifest in staged:
                move_noreplace(stage, final)
                moved = Manifest.load(final / MANIFEST_FILE)
                write_job_for(project, moved, ctx=ctx)
                project.update_index(moved.id, final)
                created.append(moved)
        except BaseException:
            for run_id, spec in zip(ids, specs, strict=True):
                for leftover in spec.parent.glob(f".{run_id}*.staging"):
                    shutil.rmtree(leftover, ignore_errors=True)
            raise
    return CreateResult(created, warnings)


def _hash_index(project: Project) -> dict[str, list[tuple[str, str]]]:
    """input_hash -> [(run id, exe_hash)] over every run, archived included."""
    index: dict[str, list[tuple[str, str]]] = {}
    for m in project.iter_runs():
        input_hash = str(m.section("identity").get("input_hash", ""))
        if input_hash:
            exe_hash = str(m.section("simulator").get("exe_hash", ""))
            index.setdefault(input_hash, []).append((m.id, exe_hash))
    return index


def _duplicate_warnings(manifest: Manifest, index: dict[str, list[tuple[str, str]]]) -> list[str]:
    """Inform (never refuse) when a run repeats the inputs of an existing one (SPEC §1.2 #2)."""
    input_hash = str(manifest.section("identity").get("input_hash", ""))
    exe_hash = str(manifest.section("simulator").get("exe_hash", ""))
    same_exe = [rid for rid, h in index.get(input_hash, []) if h == exe_hash]
    other_exe = [rid for rid, h in index.get(input_hash, []) if h != exe_hash]
    out: list[str] = []
    if same_exe:
        out.append(
            f"{manifest.id}: same inputs and executable as {', '.join(same_exe)}; "
            "the result should be identical"
        )
    elif other_exe:
        out.append(f"{manifest.id}: same inputs as {', '.join(other_exe)} (different executable)")
    return out


def _populate(
    project: Project,
    case: Case,
    ctx: SimContext,
    runtime: RuntimeInfo,
    spec: RunSpec,
    request: CreateRequest,
    run_id: str,
    stage: Path,
    final: Path,
    source: Manifest | None,
) -> Manifest:
    if stage.exists():
        shutil.rmtree(stage)
    stage.parent.mkdir(parents=True, exist_ok=True)
    input_dir = stage / "input"
    input_dir.mkdir(parents=True)
    for name in ("work", "submit", "analysis"):
        (stage / name).mkdir()
    # Inputs always come from the case; a derived run inherits only params.
    for src, rel in case.input_sources():
        dst = input_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    try:
        ctx.adapter.render_inputs(dict(spec.params), stage)
        if request.continue_run and source is not None:
            extend = getattr(ctx.adapter, "extend_inputs", None)
            if not callable(extend):
                raise UsageError(f"adapter {ctx.sim.adapter!r} does not support --continue")
            try:
                extend(source.run_dir, stage, dict(spec.params))
            except NotImplementedError:
                raise UsageError(
                    f"adapter {ctx.sim.adapter!r} does not support --continue"
                ) from None
    except (ValueError, KeyError, OSError) as exc:
        raise RunError(f"{run_id}: render_inputs failed: {exc}") from exc

    now = now_iso()
    run: dict[str, Any] = {
        "id": run_id,
        "label": spec.label,
        "status": "created",
        "created_at": now,
        "why": request.why,
        "scratch": request.scratch,
        "expires_at": "",
        "pinned": False,
        "tags": list(dict.fromkeys([*case.tags, *request.tags])),
    }
    if request.scratch:
        ttl = timedelta(days=project.config.defaults.scratch_ttl_days)
        run["expires_at"] = (datetime.now().astimezone() + ttl).isoformat(timespec="seconds")
    provenance = dict(optional(ctx.adapter, "collect_provenance", {}, runtime) or {})
    simulator = {
        "name": ctx.sim.name,
        "adapter": ctx.sim.adapter,
        "adapter_source": ctx.resolved.source,
        "adapter_version": ctx.resolved.version,
        "executable": exe_str(runtime.executable),
        "resolver_mode": runtime.resolver_mode or ctx.sim.resolver_mode,
        "package_version": runtime.package_version,
        "exe_hash": runtime.exe_hash,
        "git_commit": runtime.git_commit,
        "git_dirty": runtime.git_dirty,
        "build_dir": runtime.build_dir,
        **{k: v for k, v in provenance.items() if isinstance(v, (str, int, float, bool))},
    }
    data: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "run": run,
        "path": {"run_dir": project.rel(final), "archived_from": "", "archived_at": ""},
        "origin": {
            "case": case.name,
            "sweep": spec.sweep,
            "parent_run": source.id if source else "",
            "case_input_hash": case.input_hash(),
            "created_by": request.created_by,
        },
        "simulator": simulator,
        "job": {"scheduler": "slurm", "job_id": "", "attempt": 0, **spec.job},
        "params": dict(spec.params),
        "variation": {
            "changed_keys": list(spec.changed),
            "job_changed_keys": list(spec.job_changed),
        },
        "identity": {"input_hash": hash_tree(input_dir)},
        "storage": {"work_purged_at": ""},
    }
    manifest = Manifest(stage / MANIFEST_FILE, data)
    manifest.save()
    return manifest


# ---- cases ------------------------------------------------------------


def new_case(project: Project, name: str, simulator: str, from_case: str = "") -> Path:
    name = name.strip()
    if not name or slugify(name, 200) != name:
        raise UsageError(f"invalid case name {name!r}; use letters, digits, . _ + -")
    target = project.cases_dir / name
    if target.exists():
        raise UsageError(f"{target} already exists")
    if from_case:
        src = load_case(project.cases_dir, from_case)
        shutil.copytree(src.dir, target)
        _rewrite_case_name(target / CASE_FILE, name)
        return target
    if not simulator:
        if len(project.config.simulators) == 1:
            simulator = next(iter(project.config.simulators))
        else:
            raise UsageError("--simulator is required")
    ctx = sim_context(project, simulator)
    target.mkdir(parents=True)
    for filename, content in (optional(ctx.adapter, "case_template", {}) or {}).items():
        if filename == CASE_FILE:
            continue
        path = target / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    launcher = project.config.defaults.launcher
    (target / CASE_FILE).write_text(
        f"""[case]
name = "{name}"
simulator = "{simulator}"
{f'launcher = "{launcher}"' if launcher else '# launcher = "srun"'}
description = ""
tags = []

[job]
# partition = ""
walltime = "01:00:00"
# MPI style:      nodes = 1, ntasks = 4
# rsc / OpenMP:   processes = 1, threads = 8, cores = 8
# pre_commands = []

[params]
# "section.key" = value   # dotted keys override the base input file

# [naming.aliases]
# "section.key" = "short"
""",
        encoding="utf-8",
    )
    return target


def _rewrite_case_name(path: Path, name: str) -> None:
    import tomlkit

    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    case = doc.get("case")
    if case is None:
        case = tomlkit.table()
        doc["case"] = case
    case["name"] = name
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def list_cases(project: Project) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in list_case_names(project.cases_dir):
        try:
            case = load_case(project.cases_dir, name)
        except UsageError as exc:
            rows.append({"name": name, "simulator": "", "description": f"error: {exc}"})
            continue
        rows.append(
            {
                "name": name,
                "simulator": case.simulator,
                "description": case.description,
                "params": len(case.params),
            }
        )
    return rows
