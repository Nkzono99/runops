"""``init``, ``doctor``, ``update`` (SPEC §7.3, §8.2, §10)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

from runops.adapters.base import exe_str
from runops.config import CONFIG_FILE, SCHEMA_VERSION, load_config
from runops.errors import RunError, RunopsError, UsageError
from runops.harness import write_harness
from runops.ops.common import sim_context
from runops.ops.skills import (
    adapter_sources,
    deploy,
    deployed_skill_names,
    read_lock,
    runops_source,
)
from runops.project import Project
from runops.runtime import package_specs, resolve_runtime

# Package specs for simulators whose adapter lives in their own package.
KNOWN_PACKAGES = {
    "emses": "MPIEMSES3D @ git+https://github.com/CS12-Laboratory/MPIEMSES3D.git",
    "beach": "beach-bem",
}
KNOWN_EXECUTABLES = {"emses": "mpiemses3D", "beach": "beach"}

SITE_PRESETS: dict[str, dict[str, Any]] = {
    "camphor": {
        "site": {
            "name": "camphor",
            "resource_style": "rsc",
            "modules": ["intel/2023.2", "intelmpi/2023.2"],
            "stdout": "stdout.%J.log",
            "stderr": "stderr.%J.log",
        },
        "launcher": {"kind": "srun", "use_slurm_ntasks": True},
        "simulator_modules": {
            "emses": ["hdf5/1.12.2_intel-2023.2-impi", "fftw/3.3.10_intel-2022.3-impi"],
        },
    },
    "standard": {
        "site": {"name": "", "resource_style": "standard"},
        "launcher": {"kind": "srun", "use_slurm_ntasks": True},
    },
}

GITIGNORE = """\
.venv/
.runops/build/
.runops/index.toml
.runops/*.lock
runs/**/work/
CLAUDE.local.md
.claude/settings.local.json
"""

LOG_TEMPLATE = """\
# Log

Append dated entries: what was concluded across runs and what to do next.
Run-specific observations go to `runo note RUN "..."`.
"""

NOTES_README = """\
# notes

Reusable knowledge: one topic per file (formulas, methods, environment pitfalls).
Extend an existing file instead of creating a similar one.
"""


@dataclass
class InitReport:
    root: Path
    created: list[str] = field(default_factory=list)
    installed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_sim_arg(arg: str) -> tuple[str, str]:
    """``emses`` or ``name=package-spec``."""
    name, sep, spec = arg.partition("=")
    name = name.strip()
    if not name:
        raise UsageError(f"invalid simulator argument {arg!r}")
    return name, spec.strip() if sep else ""


def init_project(
    root: Path,
    sims: list[str],
    *,
    site: str = "",
    name: str = "",
    install: bool = True,
) -> InitReport:
    root = root.resolve()
    if (root / CONFIG_FILE).exists():
        raise UsageError(f"{root / CONFIG_FILE} already exists")
    if (root / "simulators.toml").exists():
        raise UsageError(f"{root} is a runops v1 project; use `runo migrate-v1`")
    preset = SITE_PRESETS.get(site or "standard")
    if preset is None:
        raise UsageError(f"unknown site preset {site!r}; known: {', '.join(SITE_PRESETS)}")
    report = InitReport(root)
    simulators: dict[str, Any] = {}
    for arg in sims:
        sim_name, spec = parse_sim_arg(arg)
        entry: dict[str, Any] = {"adapter": sim_name}
        if sim_name == "generic":
            entry.update({"resolver_mode": "local_executable", "command": "./run.sh"})
        else:
            entry["resolver_mode"] = "package"
            package = spec or KNOWN_PACKAGES.get(sim_name, "")
            if package:
                entry["package"] = package
            entry["executable"] = KNOWN_EXECUTABLES.get(sim_name, sim_name)
            modules = preset.get("simulator_modules", {}).get(sim_name)
            if modules:
                entry["modules"] = list(modules)
        simulators[sim_name] = entry
    config: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "project": {"name": name or root.name},
        "site": {k: v for k, v in preset["site"].items() if v != ""},
        "simulators": simulators,
        "launchers": {"srun": dict(preset["launcher"])},
        "defaults": {"launcher": "srun", "scratch_ttl_days": 7, "list_since_days": 30},
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / CONFIG_FILE).write_text(tomli_w.dumps(config), encoding="utf-8")
    report.created.append(CONFIG_FILE)
    for directory in ("cases", "runs", "notes", ".runops"):
        (root / directory).mkdir(exist_ok=True)
    for rel, text in (
        ("LOG.md", LOG_TEMPLATE),
        ("notes/README.md", NOTES_README),
    ):
        path = root / rel
        if not path.exists():
            path.write_text(text, encoding="utf-8")
            report.created.append(rel)
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE, encoding="utf-8")
        report.created.append(".gitignore")

    project = Project(load_config(root))
    if install:
        report.installed, warnings = install_packages(project, upgrade=False)
        report.warnings += warnings
    report.created += add_legacy_adapters(project)
    report.warnings += refresh_agent_files(project)
    report.created += ["AGENTS.md", "CLAUDE.md", ".agents/skills/", ".claude/skills/"]
    return report


def add_legacy_adapters(project: Project) -> list[str]:
    """Place the bundled emses/beach ports when no package provides the adapter yet."""
    from runops.ops.migrate import LEGACY_ADAPTERS, install_legacy_adapter

    added: list[str] = []
    for sim in project.config.simulators.values():
        if sim.adapter not in LEGACY_ADAPTERS or f"adapters/{sim.adapter}.py" in added:
            continue
        try:
            sim_context(project, sim.name)
        except RunopsError:
            install_legacy_adapter(project.root, sim.adapter)
            added.append(f"adapters/{sim.adapter}.py")
    return added


def _pending_specs(project: Project, warnings: list[str]) -> list[str]:
    specs: list[str] = []
    for sim in project.config.simulators.values():
        if sim.package:
            specs.append(sim.package)
            continue
        try:
            ctx = sim_context(project, sim.name)
        except RunopsError:
            if sim.adapter != "generic":
                warnings.append(
                    f"simulator {sim.name!r}: no package spec and adapter {sim.adapter!r} "
                    "not found; set [simulators.{0}].package or add adapters/{1}.py".format(
                        sim.name, sim.adapter
                    )
                )
            continue
        specs += package_specs(sim, ctx.adapter)
    return list(dict.fromkeys(specs))


def ensure_venv(project: Project) -> Path:
    python = project.venv_dir / "bin" / "python"
    if python.exists():
        return python
    uv = shutil.which("uv")
    cmd = (
        [uv, "venv", str(project.venv_dir)]
        if uv
        else [sys.executable, "-m", "venv", str(project.venv_dir)]
    )
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RunError(f"creating .venv failed: {result.stderr.strip()}")
    return python


def install_packages(project: Project, *, upgrade: bool) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    specs = _pending_specs(project, warnings)
    if not specs:
        return [], warnings
    python = ensure_venv(project)
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "pip", "install", "--python", str(python)]
    else:
        cmd = [str(python), "-m", "pip", "install"]
    if upgrade:
        cmd.append("--upgrade")
    result = subprocess.run([*cmd, *specs], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RunError(
            "package install failed:\n" + "\n".join(result.stderr.strip().splitlines()[-15:])
        )
    return specs, warnings


def refresh_agent_files(project: Project) -> list[str]:
    warnings: list[str] = []
    sources = [runops_source(), *adapter_sources(project, warnings)]
    report = deploy(project, sources)
    warnings += report.warnings
    write_harness(project, deployed_skill_names(project))
    return warnings


def update_project(project: Project, *, skills_only: bool = False) -> tuple[list[str], list[str]]:
    installed: list[str] = []
    warnings: list[str] = []
    if not skills_only:
        installed, warnings = install_packages(project, upgrade=True)
    warnings += refresh_agent_files(project)
    return installed, warnings


# ---- doctor -----------------------------------------------------------

V1_LEFTOVERS = (
    "simulators.toml",
    "launchers.toml",
    "site.toml",
    "campaign.toml",
    "SITE.md",
    ".harness",
    ".runops/facts.toml",
    ".runops/environment.toml",
    ".runops/harness.lock",
)


@dataclass
class Check:
    level: str  # ok | warn | error
    topic: str
    message: str


def doctor(project: Project) -> list[Check]:
    checks: list[Check] = [Check("ok", "config", f"{project.root / CONFIG_FILE} loaded")]
    checks += [Check("warn", "config", w) for w in project.config.warnings]
    for sim in project.config.simulators.values():
        try:
            ctx = sim_context(project, sim.name)
        except RunopsError as exc:
            checks.append(Check("error", f"simulator {sim.name}", str(exc)))
            continue
        where = ctx.resolved.location or "built-in"
        version = f" {ctx.resolved.distribution} {ctx.resolved.version}".rstrip()
        checks.append(
            Check(
                "ok",
                f"simulator {sim.name}",
                f"adapter {sim.adapter!r} resolved via {ctx.resolved.source} ({where}){version}",
            )
        )
        try:
            runtime, warns = resolve_runtime(project, sim, ctx.adapter, build=False)
            for w in warns:
                checks.append(Check("warn", f"simulator {sim.name}", w))
            if not warns and exe_str(runtime.executable):
                checks.append(
                    Check(
                        "ok",
                        f"simulator {sim.name}",
                        f"executable {runtime.executable}",
                    )
                )
        except RunopsError as exc:
            checks.append(Check("warn", f"simulator {sim.name}", str(exc)))
    if shutil.which("sbatch"):
        checks.append(Check("ok", "slurm", "sbatch found"))
    else:
        checks.append(
            Check("warn", "slurm", "sbatch not found on this host; submit/sync will fail")
        )
    lock = read_lock(project)
    if not lock:
        checks.append(
            Check("warn", "skills", "no skills deployed; run `runo update --skills-only`")
        )
    for source, version in sorted({(str(e.get("source")), str(e.get("version"))) for e in lock}):
        current = _current_skill_version(project, source)
        if current and current != version:
            checks.append(
                Check(
                    "warn",
                    "skills",
                    f"{source} skills are from {version}, installed is {current}; "
                    "run `runo update --skills-only`",
                )
            )
    leftovers = [name for name in V1_LEFTOVERS if (project.root / name).exists()]
    if leftovers:
        checks.append(
            Check(
                "warn",
                "v1",
                "v1 leftovers (safe to delete after review): " + ", ".join(leftovers),
            )
        )
    return checks


def _current_skill_version(project: Project, source: str) -> str:
    if source == "runops":
        from runops import __version__

        return __version__
    for sim in project.config.simulators.values():
        if sim.adapter != source:
            continue
        try:
            ctx = sim_context(project, sim.name)
        except RunopsError:
            return ""
        return ctx.resolved.version or "local"
    return ""
