"""``runo migrate-v1``: one-shot conversion of a runops v1 project (SPEC §11).

``plan_migration`` only reads. ``apply_plan`` moves superseded v1 files into
``.runops/v1-backup/<stamp>/`` and keeps each run's original manifest as
``manifest.v1.toml``, so nothing is lost.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

import tomli_w
import tomlkit

from runops.config import CONFIG_FILE, SCHEMA_VERSION, parse_config
from runops.errors import UsageError
from runops.manifest import MANIFEST_FILE, RunState
from runops.util import load_toml, tomllib

V1_STATUS = {s.value for s in RunState} | {"purged"}
SIM_KEYS = ("adapter", "resolver_mode", "executable", "modules", "source_repo", "build_command")
LAUNCHER_KEYS = ("command", "use_slurm_ntasks", "args", "extra_options", "modules")
SITE_KEYS = (
    "name",
    "resource_style",
    "modules",
    "stdout",
    "stderr",
    "extra_sbatch",
    "setup_commands",
)
LEGACY_DIRS = (
    "experiments",
    "research",
    "analysis",
    "materials",
    "refs",
    "harness-feedback",
    ".harnessops",
    ".runops/insights",
    ".runops/knowledge",
    "campaign.toml",
)
LEGACY_ADAPTERS = ("emses", "beach")
V2_GITIGNORE = (
    ".venv/",
    ".runops/build/",
    ".runops/index.toml",
    ".runops/*.lock",
    ".runops/v1-backup/",
    "runs/**/work/",
)


@dataclass
class ManifestChange:
    path: Path
    data: dict[str, Any]


@dataclass
class MigrationPlan:
    root: Path
    config: dict[str, Any]
    build_moves: list[tuple[Path, Path]] = field(default_factory=list)
    case_moves: list[tuple[Path, Path]] = field(default_factory=list)
    case_rewrites: list[Path] = field(default_factory=list)
    manifests: list[ManifestChange] = field(default_factory=list)
    to_backup: list[Path] = field(default_factory=list)
    adapters: list[str] = field(default_factory=list)
    test_runs: list[Path] = field(default_factory=list)
    legacy: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def describe(self) -> list[str]:
        lines = [f"runops v1 -> v2 migration plan for {self.root}", ""]
        sims = ", ".join(self.config.get("simulators", {})) or "(none)"
        lines.append(f"runops.toml: write schema 2 (simulators: {sims})")
        lines.append("v1 configs, harness files and runops skills -> .runops/v1-backup/<stamp>/:")
        lines += [f"  {self.rel(p)}" for p in self.to_backup]
        if self.build_moves:
            lines.append("build caches .runops/work -> .runops/build:")
            lines += [f"  {self.rel(a)} -> {self.rel(b)}" for a, b in self.build_moves]
        if self.case_moves:
            lines.append(f"cases to flatten ({len(self.case_moves)}):")
            lines += [f"  {self.rel(a)} -> {self.rel(b)}" for a, b in self.case_moves]
        if self.case_rewrites:
            lines.append(f"case.toml [classification] -> [case].tags: {len(self.case_rewrites)}")
        statuses: dict[str, int] = {}
        for change in self.manifests:
            status = str(change.data["run"]["status"])
            statuses[status] = statuses.get(status, 0) + 1
        summary = ", ".join(f"{k}={v}" for k, v in sorted(statuses.items()))
        lines.append(
            f"manifests to convert: {len(self.manifests)} ({summary}); "
            "originals kept as manifest.v1.toml"
        )
        if self.adapters:
            lines.append(
                "project-local adapters to add: "
                + ", ".join(f"adapters/{a}.py" for a in self.adapters)
            )
        if self.test_runs:
            lines.append(
                f".runops/test-runs: {len(self.test_runs)} attempts "
                "(deleted only with --apply-delete-test-runs)"
            )
        if self.legacy:
            lines.append(
                "left untouched (listed in notes/README.md and LOG.md): " + ", ".join(self.legacy)
            )
        lines += [f"warning: {w}" for w in self.warnings]
        return lines


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return load_toml(path)
    except tomllib.TOMLDecodeError as exc:
        raise UsageError(f"{path}: invalid TOML: {exc}") from None


def plan_migration(root: Path) -> MigrationPlan:
    root = root.resolve()
    current = _load(root / CONFIG_FILE)
    if current.get("schema") == SCHEMA_VERSION:
        raise UsageError(f"{root} is already a runops v2 project")
    if not (root / "simulators.toml").is_file():
        raise UsageError(f"{root} has no simulators.toml; not a runops v1 project")
    plan = MigrationPlan(root=root, config={})
    plan.config = _plan_config(root, current, plan)
    parse_config(root, plan.config)  # validate early

    case_renames = _plan_cases(root, plan)
    sweeps = _survey_labels(root)
    runs_dir = root / "runs"
    for path in _iter_manifests(runs_dir):
        try:
            data = load_toml(path)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            plan.warnings.append(f"{plan.rel(path)}: unreadable, skipped ({exc})")
            continue
        if data.get("schema") == SCHEMA_VERSION:
            continue
        try:
            converted = convert_manifest(
                data, path.parent, root, sweeps, case_renames, plan.build_moves
            )
        except ValueError as exc:
            plan.warnings.append(f"{plan.rel(path)}: {exc}; skipped")
            continue
        plan.manifests.append(ManifestChange(path, converted))

    for name in (
        "simulators.toml",
        "launchers.toml",
        "site.toml",
        CONFIG_FILE,
        "AGENTS.md",
        "CLAUDE.md",
        ".codex",
    ):
        if (root / name).exists():
            plan.to_backup.append(root / name)
    for base in (".claude/skills", ".agents/skills"):
        if (root / base).is_dir():
            plan.to_backup += sorted(
                p for p in (root / base).iterdir() if p.name.startswith("runops")
            )
    plan.to_backup += _nested_harness_files(root)

    adapters = {sim.get("adapter") for sim in plan.config.get("simulators", {}).values()}
    plan.adapters = [
        a for a in LEGACY_ADAPTERS if a in adapters and not (root / "adapters" / f"{a}.py").exists()
    ]
    test_runs = root / ".runops" / "test-runs"
    if test_runs.is_dir():
        plan.test_runs = sorted(p for p in test_runs.iterdir() if p.is_dir())
    plan.legacy = [name for name in LEGACY_DIRS if (root / name).exists()]
    return plan


def _plan_config(root: Path, v1_runops: dict[str, Any], plan: MigrationPlan) -> dict[str, Any]:
    sims_v1 = _load(root / "simulators.toml").get("simulators", {})
    launchers_v1 = _load(root / "launchers.toml").get("launchers", {})
    site_file = _load(root / "site.toml")
    site_v1 = site_file.get("site", {})
    site: dict[str, Any] = {k: site_v1[k] for k in SITE_KEYS if k in site_v1}
    if isinstance(site_v1.get("env"), dict) and site_v1["env"]:
        site["env"] = dict(site_v1["env"])
    site_sim_modules = {
        name: list(entry.get("modules", []))
        for name, entry in (site_v1.get("simulators") or {}).items()
        if isinstance(entry, dict)
    }

    simulators: dict[str, Any] = {}
    work_dir = (root / ".runops" / "work").resolve()
    for name, raw in sims_v1.items():
        entry = {k: raw[k] for k in SIM_KEYS if k in raw and raw[k] not in ("", [])}
        entry.setdefault("adapter", name)
        site_mods = site_sim_modules.get(name) or site_sim_modules.get(str(entry["adapter"]), [])
        modules = list(dict.fromkeys([*site_mods, *entry.get("modules", [])]))
        if modules:
            entry["modules"] = modules
        exe = str(entry.get("executable", ""))
        moved = _build_target(Path(exe), work_dir, root) if exe.startswith("/") else None
        if moved is not None:
            src_dir, dst_dir, rest = moved
            if (src_dir, dst_dir) not in plan.build_moves:
                plan.build_moves.append((src_dir, dst_dir))
            entry["executable"] = (dst_dir / rest).relative_to(root).as_posix()
            entry["resolver_mode"] = "local_executable"
        dropped = sorted(set(raw) - set(SIM_KEYS))
        if dropped:
            plan.warnings.append(f"[simulators.{name}]: dropped {', '.join(dropped)}")
        simulators[name] = entry

    launchers: dict[str, Any] = {}
    for name, raw in launchers_v1.items():
        entry = {"kind": str(raw.get("kind") or raw.get("type") or "srun")}
        entry.update({k: raw[k] for k in LAUNCHER_KEYS if k in raw})
        launchers[name] = entry
    config: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "project": {"name": str(v1_runops.get("project", {}).get("name") or root.name)},
        "site": site,
        "simulators": simulators,
        "launchers": launchers,
        "defaults": {
            "scratch_ttl_days": 7,
            "list_since_days": 30,
            "tidy_failed_days": 30,
            "tidy_archive_days": 90,
            "label_max_length": 48,
        },
    }
    if len(launchers) == 1:
        config["defaults"]["launcher"] = next(iter(launchers))
    return config


def _build_target(exe: Path, work_dir: Path, root: Path) -> tuple[Path, Path, Path] | None:
    """``.runops/work/<d>/rest`` -> (src dir, .runops/build/<d>, rest)."""
    try:
        rel = exe.resolve().relative_to(work_dir)
    except (ValueError, OSError):
        return None
    if len(rel.parts) < 2:
        return None
    name = rel.parts[0]
    return work_dir / name, root / ".runops" / "build" / name, Path(*rel.parts[1:])


def _plan_cases(root: Path, plan: MigrationPlan) -> dict[str, str]:
    """Plan ``cases/<sim>/<name>`` -> ``cases/<name>``; return renamed names."""
    cases = root / "cases"
    renames: dict[str, str] = {}
    if not cases.is_dir():
        return renames
    taken = {p.parent.name for p in cases.glob("*/case.toml")}
    for path in sorted(cases.glob("*/*/case.toml")):
        case_dir = path.parent
        sim = case_dir.parent.name
        name = case_dir.name
        target = name
        if target in taken:
            target = f"{sim}-{name}"
            renames[name] = target
            plan.warnings.append(f"case {sim}/{name} renamed to {target} (name clash)")
        taken.add(target)
        plan.case_moves.append((case_dir, cases / target))
    for path in sorted(cases.glob("*/case.toml")) + sorted(cases.glob("*/*/case.toml")):
        try:
            if "classification" in load_toml(path):
                plan.case_rewrites.append(path)
        except tomllib.TOMLDecodeError as exc:
            plan.warnings.append(f"{plan.rel(path)}: invalid TOML ({exc})")
    return renames


def _iter_manifests(runs_dir: Path) -> list[Path]:
    found: list[Path] = []
    if not runs_dir.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(runs_dir):
        if MANIFEST_FILE in filenames:
            found.append(Path(dirpath) / MANIFEST_FILE)
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
    return found


def _survey_labels(root: Path) -> dict[Path, str]:
    labels: dict[Path, str] = {}
    runs = root / "runs"
    if not runs.is_dir():
        return labels
    for dirpath, dirnames, filenames in os.walk(runs):
        if MANIFEST_FILE in filenames:
            dirnames[:] = []
            continue
        if "survey.toml" in filenames:
            path = Path(dirpath) / "survey.toml"
            try:
                survey = load_toml(path).get("survey", {})
            except tomllib.TOMLDecodeError:
                survey = {}
            labels[path.parent.resolve()] = str(survey.get("id") or path.parent.name)
    return labels


def _nested_harness_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for base in (root / "runs", root / "cases"):
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            if MANIFEST_FILE in filenames:
                dirnames[:] = []
            for name in ("AGENTS.md", "CLAUDE.md"):
                if name in filenames:
                    found.append(Path(dirpath) / name)
    return sorted(found)


def _rel_path(value: str, root: Path) -> str:
    if not value:
        return ""
    path = Path(value)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return str(path)


def convert_manifest(
    data: dict[str, Any],
    run_dir: Path,
    root: Path,
    sweeps: dict[Path, str],
    case_renames: dict[str, str],
    build_moves: list[tuple[Path, Path]],
) -> dict[str, Any]:
    run = dict(data.get("run", {}))
    status = str(run.get("status", "created"))
    if status not in V1_STATUS:
        raise ValueError(f"unknown status {status!r}")
    path_v1 = data.get("path", {})
    origin = data.get("origin", {})
    classification = data.get("classification", {})
    intent = data.get("intent", {})
    storage_v1 = data.get("storage", {})
    sim_v1 = {**data.get("simulator_source", {}), **data.get("simulator", {})}
    job = {k: v for k, v in data.get("job", {}).items() if k != "queue"}

    rel_dir = run_dir.resolve().relative_to(root).as_posix()
    archive_prefix = "runs/_archive/"
    archived = status in ("archived", "purged") or rel_dir.startswith(archive_prefix)
    tags = [
        str(t)
        for t in [
            classification.get("model"),
            classification.get("submodel"),
            *classification.get("tags", []),
        ]
        if t
    ]
    sweep = str(origin.get("survey") or "")
    if not sweep:
        for parent in run_dir.resolve().parents:
            if parent in sweeps:
                sweep = sweeps[parent]
                break
    case = str(origin.get("case", ""))
    executable = str(sim_v1.get("executable", ""))
    for src, dst in build_moves:
        if executable.startswith(str(src) + "/"):
            executable = str(dst) + executable[len(str(src)) :]
    new_run: dict[str, Any] = {
        "id": str(run.get("id", "")),
        "label": str(run.get("display_name") or run.get("label") or ""),
        "status": "archived" if archived else status,
        "created_at": str(run.get("created_at", "")),
        "why": str(intent.get("purpose") or run.get("why") or ""),
        "scratch": False,
        "expires_at": "",
        "pinned": bool(storage_v1.get("pinned", False)),
        "tags": list(dict.fromkeys(tags)),
    }
    if not new_run["id"]:
        raise ValueError("missing [run].id")
    if archived:
        new_run["status_before_archive"] = (
            "completed" if status in ("archived", "purged") else status
        )
    archived_from = ""
    if archived:
        archived_from = (
            "runs/" + rel_dir[len(archive_prefix) :]
            if rel_dir.startswith(archive_prefix)
            else _rel_path(str(path_v1.get("archived_from", "")), root)
        )
    return {
        "schema": SCHEMA_VERSION,
        "run": new_run,
        "path": {
            "run_dir": rel_dir,
            "archived_from": archived_from,
            "archived_at": str(
                path_v1.get("archived_at") or path_v1.get("bundle_archived_at") or ""
            ),
        },
        "origin": {
            "case": case_renames.get(case, case),
            "sweep": sweep,
            "parent_run": str(origin.get("parent_run", "")),
            "created_by": str(intent.get("created_by") or ""),
        },
        "simulator": {
            "name": str(sim_v1.get("name", "")),
            "adapter": str(sim_v1.get("adapter", "")),
            "executable": executable,
            "resolver_mode": str(sim_v1.get("resolver_mode", "")),
            "package_version": str(sim_v1.get("package_version", "")),
            "exe_hash": str(sim_v1.get("exe_hash", "")),
            "git_commit": str(sim_v1.get("git_commit", "")),
            "git_dirty": bool(sim_v1.get("git_dirty", False)),
        },
        "launcher": dict(data.get("launcher", {})),
        "job": job,
        "params": dict(data.get("params_snapshot") or data.get("params") or {}),
        "variation": {"changed_keys": list(data.get("variation", {}).get("changed_keys", []))},
        "identity": {"input_hash": str(data.get("identity", {}).get("input_hash", ""))},
        "storage": {
            "work_purged_at": str(path_v1.get("archived_at") or "") if status == "purged" else "",
        },
    }


# ---------------------------------------------------------------------------
# applying
# ---------------------------------------------------------------------------


def apply_plan(plan: MigrationPlan, *, delete_test_runs: bool = False) -> list[str]:
    root = plan.root
    log: list[str] = []
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    backup = root / ".runops" / "v1-backup" / stamp
    backup.mkdir(parents=True, exist_ok=False)

    for path in plan.to_backup:
        if not path.exists():
            continue
        target = backup / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
    log.append(f"moved {len(plan.to_backup)} v1 files to {plan.rel(backup)}")
    (root / CONFIG_FILE).write_text(tomli_w.dumps(plan.config), encoding="utf-8")
    log.append("wrote runops.toml (schema 2)")

    for src, dst in plan.build_moves:
        if src.is_dir() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            log.append(f"moved {plan.rel(src)} -> {plan.rel(dst)}")
            log += _repair_worktrees(dst)

    for case_toml in plan.case_rewrites:
        _rewrite_case(case_toml)
    for src, dst in plan.case_moves:
        shutil.move(str(src), str(dst))
        _set_case_name(dst / "case.toml", dst.name)
        _prune(src.parent, root / "cases")
    if plan.case_moves or plan.case_rewrites:
        log.append(f"cases: {len(plan.case_moves)} moved, {len(plan.case_rewrites)} rewritten")

    for change in plan.manifests:
        backup_manifest = change.path.with_name("manifest.v1.toml")
        if not backup_manifest.exists():
            shutil.copy2(change.path, backup_manifest)
        tmp = change.path.with_name(".manifest.toml.migrating")
        tmp.write_text(tomli_w.dumps(change.data), encoding="utf-8")
        os.replace(tmp, change.path)
    log.append(f"converted {len(plan.manifests)} manifests")

    for name in plan.adapters:
        install_legacy_adapter(root, name)
        log.append(f"added adapters/{name}.py")

    if delete_test_runs and plan.test_runs:
        for path in plan.test_runs:
            shutil.rmtree(path)
        log.append(f"deleted {len(plan.test_runs)} test runs")

    _write_notes(plan)
    _update_gitignore(root)

    from runops.ops.setup import refresh_agent_files
    from runops.project import Project

    project = Project.open(root)
    for warning in refresh_agent_files(project):
        log.append(f"warning: {warning}")
    project.rebuild_index()
    log.append("deployed skills, wrote AGENTS.md / CLAUDE.md, rebuilt run index")
    log.append("next: `runo doctor`, then `runo list --all`")
    return log


def _repair_worktrees(directory: Path) -> list[str]:
    """Re-register git worktrees (``.git`` files) moved along with a build dir."""
    log: list[str] = []
    candidates = [directory / ".git", *directory.glob("*/.git")]
    for git_file in candidates:
        if not git_file.is_file():
            continue
        result = subprocess.run(
            ["git", "-C", str(git_file.parent), "worktree", "repair"],
            capture_output=True,
            text=True,
            check=False,
        )
        where = git_file.parent
        if result.returncode == 0:
            log.append(f"repaired git worktree link for {where}")
        else:
            log.append(f"warning: git worktree repair failed for {where}: {result.stderr.strip()}")
    return log


def install_legacy_adapter(root: Path, name: str) -> Path:
    """Copy the bundled v1 port of *name* to ``<root>/adapters/<name>.py``."""
    target = root / "adapters" / f"{name}.py"
    target.parent.mkdir(exist_ok=True)
    source = resources.files("runops.legacy_adapters") / f"{name}.py"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _rewrite_case(path: Path) -> None:
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    classification = doc.get("classification")
    if classification is None:
        return
    case = doc.get("case")
    if case is None:
        case = tomlkit.table()
        doc["case"] = case
    tags = [str(t) for t in case.get("tags", [])]
    tags += [str(t) for t in [classification.get("model"), classification.get("submodel")] if t]
    tags += [str(t) for t in classification.get("tags", [])]
    case["tags"] = list(dict.fromkeys(tags))
    del doc["classification"]
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def _set_case_name(path: Path, name: str) -> None:
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    case = doc.get("case")
    if case is not None and case.get("name") != name:
        case["name"] = name
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def _prune(directory: Path, stop: Path) -> None:
    if directory != stop and directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()


def _write_notes(plan: MigrationPlan) -> None:
    root = plan.root
    notes = root / "notes"
    notes.mkdir(exist_ok=True)
    readme = notes / "README.md"
    lines = []
    if not readme.exists():
        lines.append("# notes\n\nReusable knowledge: one topic per file.\n")
    if plan.legacy:
        lines.append("\n## runops v1 material (left in place)\n")
        lines += [f"- `{name}`" for name in plan.legacy]
        lines.append("")
    if lines:
        with readme.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    log = root / "LOG.md"
    entry = [
        "" if log.exists() else "# Log\n",
        f"## {datetime.now().astimezone():%Y-%m-%d} migrated to runops v2",
        "",
        "v1 configs and harness files are in `.runops/v1-backup/`; each run keeps",
        "`manifest.v1.toml`.",
    ]
    if plan.legacy:
        entry.append("v1 material left in place: " + ", ".join(f"`{n}`" for n in plan.legacy) + ".")
    with log.open("a", encoding="utf-8") as f:
        f.write("\n".join(entry) + "\n")


def _update_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    missing = [line for line in V2_GITIGNORE if line not in existing]
    if missing:
        with path.open("a", encoding="utf-8") as f:
            f.write("\n# runops v2\n" + "\n".join(missing) + "\n")
