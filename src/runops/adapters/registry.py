"""Adapter resolution (SPEC §8.1).

Order: ``runops.adapters`` entry point (current interpreter, then the
project's ``.venv``) -> project ``adapters/<name>.py`` -> built-in generic.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runops.adapters.base import SimulatorAdapterProtocol
from runops.adapters.generic import GenericAdapter
from runops.errors import UsageError

ENTRY_POINT_GROUP = "runops.adapters"


@dataclass
class ResolvedAdapter:
    adapter: Any
    source: str  # "entry-point" | "project-local" | "builtin"
    location: str = ""
    distribution: str = ""
    version: str = ""


def venv_site_packages(venv: Path) -> list[Path]:
    lib = venv / "lib"
    if not lib.is_dir():
        return []
    return sorted(p for p in lib.glob("python*/site-packages") if p.is_dir())


def _entry_point(
    name: str, project_root: Path | None
) -> tuple[Any, md.Distribution | None, str] | None:
    for ep in md.entry_points(group=ENTRY_POINT_GROUP):
        if ep.name == name:
            return ep, getattr(ep, "dist", None), ""
    if project_root is None:
        return None
    # Metadata directory listings are cached by mtime; on filesystems with
    # one-second mtime (Lustre) a package installed moments ago would be missed.
    importlib.invalidate_caches()
    # Python 3.10's importlib.invalidate_caches() does not reach the metadata
    # finder's FastPath cache; clear it explicitly.
    finder: Any = md.MetadataPathFinder
    try:
        finder.invalidate_caches()
    except TypeError:  # 3.10 defines it without @classmethod
        finder.invalidate_caches(finder)
    for site in venv_site_packages(project_root / ".venv"):
        for dist in md.distributions(path=[str(site)]):
            for ep in dist.entry_points:
                if ep.group == ENTRY_POINT_GROUP and ep.name == name:
                    return ep, dist, str(site)
    return None


def resolve_adapter(
    name: str,
    project_root: Path | None,
    sim_config: dict[str, Any] | None = None,
) -> ResolvedAdapter:
    resolved = _try_resolve(name, project_root)
    if resolved is None:
        raise UsageError(
            f"adapter {name!r} not found. Install the simulator package that "
            f"provides it (`pip install <package>` into .venv, or `runo update`), "
            f"or create adapters/{name}.py with an `Adapter` class."
        )
    configure = getattr(resolved.adapter, "configure", None)
    if callable(configure):
        configure(dict(sim_config or {}))
    _check_contract(resolved)
    return resolved


def _try_resolve(name: str, project_root: Path | None) -> ResolvedAdapter | None:
    found = _entry_point(name, project_root)
    if found is not None:
        ep, dist, site = found
        if site and site not in sys.path:
            # addsitedir also processes .pth files, so editable installs work.
            import site as site_module

            site_module.addsitedir(site)
        try:
            cls = ep.load()
        except Exception as exc:
            raise UsageError(f"adapter {name!r}: failed to import {ep.value}: {exc}") from exc
        return ResolvedAdapter(
            adapter=cls() if isinstance(cls, type) else cls,
            source="entry-point",
            location=ep.value,
            distribution=dist.metadata["Name"] if dist is not None else "",
            version=dist.version if dist is not None else "",
        )
    if project_root is not None:
        path = project_root / "adapters" / f"{name}.py"
        if path.is_file():
            module_name = f"runops_project_adapters.{name}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise UsageError(f"cannot import {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                raise UsageError(f"{path}: import failed: {exc}") from exc
            cls = getattr(module, "Adapter", None)
            if cls is None:
                raise UsageError(f"{path} must define a class named `Adapter`")
            return ResolvedAdapter(adapter=cls(), source="project-local", location=str(path))
    if name == "generic":
        return ResolvedAdapter(adapter=GenericAdapter(), source="builtin")
    return None


def _check_contract(resolved: ResolvedAdapter) -> None:
    adapter = resolved.adapter
    if not isinstance(adapter, SimulatorAdapterProtocol):
        missing = [
            attr
            for attr in ("name", "render_inputs", "build_command", "detect_status")
            if not hasattr(adapter, attr)
        ]
        raise UsageError(
            f"adapter from {resolved.location or resolved.source} does not "
            f"satisfy the contract; missing: {', '.join(missing)}"
        )


def optional(adapter: Any, method: str, default: Any, *args: Any) -> Any:
    """Call an optional adapter hook, returning *default* when absent."""
    func = getattr(adapter, method, None)
    if not callable(func):
        return default
    try:
        return func(*args)
    except NotImplementedError:
        return default
