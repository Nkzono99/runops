"""Executable resolution and the ``local_source`` build cache (SPEC §4.1)."""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import shutil
import subprocess
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

from runops.adapters.base import RuntimeInfo, exe_str
from runops.adapters.registry import optional, venv_site_packages
from runops.config import SimulatorConfig
from runops.errors import RunError, UsageError
from runops.project import Project
from runops.util import hash_file


def package_specs(sim: SimulatorConfig, adapter: Any) -> list[str]:
    if sim.package:
        return [sim.package]
    return list(optional(adapter, "pip_packages", []) or [])


def installed_version(project: Project, spec: str) -> str:
    try:
        name = Requirement(spec).name
    except InvalidRequirement:
        name = spec
    for site in venv_site_packages(project.venv_dir):
        for dist in md.distributions(path=[str(site)], name=name):
            return dist.version
    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return ""


def resolve_runtime(
    project: Project,
    sim: SimulatorConfig,
    adapter: Any,
    *,
    build: bool = True,
) -> tuple[RuntimeInfo, list[str]]:
    """Resolve the executable; returns runtime info and warnings."""
    warnings: list[str] = []
    custom = getattr(adapter, "resolve_runtime", None)
    if callable(custom):
        info = custom(dict(sim.raw), project.venv_dir)
        info.resolver_mode = info.resolver_mode or sim.resolver_mode
    elif sim.resolver_mode == "local_source":
        info = _resolve_local_source(project, sim, build=build)
    else:
        info = RuntimeInfo(
            executable=_find_executable(project, sim, warnings),
            resolver_mode=sim.resolver_mode,
        )
        if sim.resolver_mode == "package":
            specs = package_specs(sim, adapter)
            if specs:
                info.package_version = installed_version(project, specs[0])
    if exe_str(info.executable) and info.executable.is_file():
        info.exe_hash = hash_file(info.executable)
    return info, warnings


def _find_executable(project: Project, sim: SimulatorConfig, warnings: list[str]) -> Path:
    exe = sim.executable
    if not exe:
        if sim.raw.get("command"):
            return Path("")
        raise UsageError(f"[simulators.{sim.name}].executable is not set")
    path = Path(exe).expanduser()
    if path.is_absolute():
        if not path.exists():
            warnings.append(f"executable {path} does not exist")
        return path
    if sim.resolver_mode == "package":
        candidate = project.venv_dir / "bin" / exe
        if candidate.exists():
            return candidate
    if "/" in exe:
        candidate = (project.root / exe).resolve()
        if candidate.exists():
            return candidate
    found = shutil.which(exe)
    if found:
        return Path(found)
    hint = " (try `runo update`)" if sim.resolver_mode == "package" else ""
    warnings.append(f"executable {exe!r} not found on this host{hint}")
    return Path(exe)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise UsageError(
            f"git {' '.join(args)} failed in {repo}: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout.decode(errors="replace")


def source_state(project: Project, sim: SimulatorConfig) -> tuple[Path, str, bool, str]:
    """Return (repo, full_commit, dirty, build_dir_name)."""
    if not sim.source_repo:
        raise UsageError(f"[simulators.{sim.name}].source_repo is required for local_source")
    repo = Path(sim.source_repo).expanduser()
    if not repo.is_absolute():
        repo = (project.root / repo).resolve()
    if not repo.is_dir():
        raise UsageError(f"source_repo {repo} does not exist")
    commit = _git(repo, "rev-parse", "HEAD").strip()
    status = _git(repo, "status", "--porcelain")
    dirty = bool(status.strip())
    name = f"{sim.name}-{commit[:12]}"
    if dirty:
        digest = hashlib.sha256(_git(repo, "diff", "HEAD").encode())
        digest.update(status.encode())
        name += f"-dirty-{digest.hexdigest()[:8]}"
    return repo, commit, dirty, name


def build_simulator(project: Project, sim: SimulatorConfig, *, force: bool = False) -> Path:
    """Build *sim* into ``.runops/build/<name>-<commit>``; return the build dir."""
    if sim.resolver_mode != "local_source":
        raise UsageError(f"simulator {sim.name!r} is not resolver_mode = local_source")
    if not sim.build_command:
        raise UsageError(f"[simulators.{sim.name}].build_command is required")
    if not sim.executable:
        raise UsageError(f"[simulators.{sim.name}].executable is required")
    repo, _commit, _dirty, name = source_state(project, sim)
    target = project.build_dir / name
    if (target / sim.executable).exists() and not force:
        return target
    partial = project.build_dir / f".{name}.partial"
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    files = _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for rel in filter(None, files.split("\0")):
        src = repo / rel
        dst = partial / rel
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
        elif src.exists() or src.is_symlink():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst, follow_symlinks=False)
    log_path = partial / "runops-build.log"
    with log_path.open("w") as log:
        result = subprocess.run(
            sim.build_command,
            shell=True,
            cwd=partial,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode != 0:
        tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-20:])
        raise RunError(
            f"build of {sim.name} failed (exit {result.returncode}); see {log_path}\n{tail}"
        )
    if not (partial / sim.executable).exists():
        raise RunError(
            f"build of {sim.name} finished but {sim.executable} was not produced in {partial}"
        )
    if target.exists():
        shutil.rmtree(target)
    partial.rename(target)
    return target


def _resolve_local_source(project: Project, sim: SimulatorConfig, *, build: bool) -> RuntimeInfo:
    _repo, commit, dirty, name = source_state(project, sim)
    target = project.build_dir / name
    exe = target / sim.executable
    if not exe.exists():
        if not build:
            raise UsageError(f"{sim.name} is not built yet; run `runo build {sim.name}`")
        target = build_simulator(project, sim)
        exe = target / sim.executable
    return RuntimeInfo(
        executable=exe,
        git_commit=commit,
        git_dirty=dirty,
        resolver_mode="local_source",
        build_dir=project.rel(target),
    )
