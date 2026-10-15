"""Adapter contract (SPEC §8.1).

A simulator package does not need to import runops: any class with a
``name`` attribute and the three required methods satisfies
:class:`SimulatorAdapterProtocol`.  :class:`SimulatorAdapter` only adds
default implementations of the optional hooks for convenience.

Required:
    render_inputs(params, run_dir) -> list[str]
    build_command(runtime, run_dir) -> list[str]   # cwd is run_dir
    detect_status(run_dir) -> "completed" | "failed" | "unknown"

Optional (looked up with ``getattr``):
    configure(sim_config: dict) -> None
    case_template() -> dict[str, str]
    pip_packages() -> list[str]
    resolve_runtime(sim_config: dict, venv: Path) -> RuntimeInfo
    collect_provenance(runtime) -> dict
    validate_params(params) -> list[str]
    summarize(run_dir) -> dict
    keep_patterns() -> list[str]
    extend_inputs(src_run, run_dir, params) -> list[str]
    job_prelude(run_dir) -> list[str]
    agent_context_dir() -> Path | None
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import tomli_w

from runops.util import load_toml

AdapterStatus = Literal["completed", "failed", "unknown"]


@dataclass
class RuntimeInfo:
    """Resolved executable and provenance passed to ``build_command``."""

    executable: Path
    package_version: str = ""
    exe_hash: str = ""
    git_commit: str = ""
    git_dirty: bool = False
    env: dict[str, str] = field(default_factory=dict)
    resolver_mode: str = ""
    build_dir: str = ""


def exe_str(path: Path | None) -> str:
    """String form of an executable path; ``""`` when unset."""
    text = str(path) if path is not None else ""
    return "" if text in ("", ".") else text


@runtime_checkable
class SimulatorAdapterProtocol(Protocol):
    name: str

    def render_inputs(self, params: dict[str, Any], run_dir: Path) -> list[str]: ...

    def build_command(self, runtime: RuntimeInfo, run_dir: Path) -> list[str]: ...

    def detect_status(self, run_dir: Path) -> str: ...


class SimulatorAdapter:
    """Optional convenience base class with default optional hooks."""

    name: str = ""

    def render_inputs(self, params: dict[str, Any], run_dir: Path) -> list[str]:
        raise NotImplementedError

    def build_command(self, runtime: RuntimeInfo, run_dir: Path) -> list[str]:
        raise NotImplementedError

    def detect_status(self, run_dir: Path) -> str:
        return "unknown"

    def case_template(self) -> dict[str, str]:
        return {}

    def pip_packages(self) -> list[str]:
        return []

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        return []

    def summarize(self, run_dir: Path) -> dict[str, Any]:
        return {}

    def keep_patterns(self) -> list[str]:
        return []

    def job_prelude(self, run_dir: Path) -> list[str]:
        return []

    def agent_context_dir(self) -> Path | None:
        return None


_SEGMENT_RE = re.compile(r"^(?P<name>[^\[\]]*)(?P<idx>(\[\d+\])*)$")


def _steps(key: str) -> list[str | int]:
    """``a.b[0].c`` / ``a.b.0.c`` -> ["a", "b", 0, "c"] (digits index arrays)."""
    steps: list[str | int] = []
    for part in key.split("."):
        match = _SEGMENT_RE.match(part)
        if not match or (not match.group("name") and not match.group("idx")):
            raise ValueError(f"invalid parameter key {key!r}")
        if match.group("name"):
            steps.append(match.group("name"))
        steps += [int(x) for x in re.findall(r"\[(\d+)\]", match.group("idx"))]
    return steps


def set_dotted(config: dict[str, Any], key: str, value: Any) -> None:
    """Set a dotted *key* in nested tables/arrays, creating missing tables.

    ``plasma.wc`` sets ``config["plasma"]["wc"]``; an array element is addressed
    as ``species.0.wp`` or ``species[0].wp``.
    """
    steps = _steps(key)
    node: Any = config
    for i, step in enumerate(steps):
        last = i == len(steps) - 1
        if isinstance(node, list):
            index = int(step) if isinstance(step, int) or str(step).isdigit() else None
            if index is None or index >= len(node):
                raise ValueError(f"{key!r}: invalid array index {step!r}")
            if last:
                node[index] = value
                return
            node = node[index]
            continue
        if not isinstance(node, dict) or isinstance(step, int):
            raise ValueError(f"{key!r}: {step!r} does not address an array")
        if last:
            node[step] = value
            return
        child = node.get(step)
        if not isinstance(child, (dict, list)):
            child = {}
            node[step] = child
        node = child


def toml_override(path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """Apply dotted-key *params* to the TOML file at *path* in place."""
    config = load_toml(path)
    for key, value in params.items():
        set_dotted(config, key, value)
    path.write_text(tomli_w.dumps(config), encoding="utf-8")
    return config
