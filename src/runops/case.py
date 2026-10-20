"""Case loading (SPEC §5) and run labelling."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runops.errors import UsageError
from runops.util import hash_file, load_toml, tomllib

CASE_FILE = "case.toml"
LABEL_MAX = 48
JOB_KEYS = {
    "partition",
    "qos",
    "walltime",
    "nodes",
    "ntasks",
    "cpus_per_task",
    "processes",
    "threads",
    "cores",
    "memory",
    "gpus",
    "job_name",
    "extra_sbatch",
    "pre_commands",
    "post_commands",
    "modules",
}


@dataclass
class Case:
    name: str
    dir: Path
    simulator: str
    launcher: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    job: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def input_sources(self) -> list[tuple[Path, str]]:
        """Files copied into a run's ``input/``: (source, relative target)."""
        items: list[tuple[Path, str]] = []
        for path in sorted(self.dir.iterdir()):
            if path.is_file() and path.name != CASE_FILE and not path.name.startswith("."):
                items.append((path, path.name))
        extra = self.dir / "input"
        if extra.is_dir():
            for path in sorted(extra.rglob("*")):
                if path.is_file():
                    items.append((path, path.relative_to(extra).as_posix()))
        return items

    def input_hash(self) -> str:
        """Content hash of :meth:`input_sources` (the base files a run is rendered from)."""
        digest = hashlib.sha256()
        for src, rel in self.input_sources():
            digest.update(f"{rel}\0{hash_file(src)}\0".encode())
        return f"sha256:{digest.hexdigest()}"


def load_case(cases_dir: Path, name: str) -> Case:
    case_dir = cases_dir / name
    path = case_dir / CASE_FILE
    if not path.is_file():
        known = ", ".join(list_case_names(cases_dir)) or "(none)"
        raise UsageError(f"case {name!r} not found ({path}); known cases: {known}")
    try:
        data = load_toml(path)
    except tomllib.TOMLDecodeError as exc:
        raise UsageError(f"{path}: invalid TOML: {exc}") from None
    section = data.get("case", {})
    if not isinstance(section, dict):
        raise UsageError(f"{path}: [case] must be a table")
    simulator = str(section.get("simulator", ""))
    if not simulator:
        raise UsageError(f"{path}: [case].simulator is required")
    warnings: list[str] = []
    job = dict(data.get("job", {}))
    for key in job:
        if key not in JOB_KEYS:
            warnings.append(f"{path}: [job].{key} is unknown and ignored")
    tags = [str(t) for t in section.get("tags", [])]
    naming = data.get("naming", {})
    aliases = naming.get("aliases", {}) if isinstance(naming, dict) else {}
    return Case(
        name=name,
        dir=case_dir,
        simulator=simulator,
        launcher=str(section.get("launcher", "")),
        description=str(section.get("description", "")),
        tags=tags,
        job={k: v for k, v in job.items() if k in JOB_KEYS},
        params=dict(data.get("params", {})),
        aliases={str(k): str(v) for k, v in aliases.items()},
        warnings=warnings,
    )


def list_case_names(cases_dir: Path) -> list[str]:
    if not cases_dir.is_dir():
        return []
    return sorted(p.parent.name for p in cases_dir.glob(f"*/{CASE_FILE}"))


def changed_keys(base: dict[str, Any], params: dict[str, Any]) -> list[str]:
    return [k for k, v in params.items() if k not in base or base[k] != v]


def make_label(
    keys: list[str],
    params: dict[str, Any],
    aliases: dict[str, str],
    max_length: int = LABEL_MAX,
    names: dict[str, str] | None = None,
) -> str:
    """Auto label from changed keys, e.g. ``wc0.147_phiz45``.

    *names* maps a key to the short name given for its value (``sweep --names``);
    it replaces alias + value for that key.
    """
    parts = []
    for key in keys:
        if names and key in names:
            parts.append(names[key])
            continue
        alias = aliases.get(key) or key.rsplit(".", 1)[-1]
        parts.append(f"{alias}{_format_value(params[key])}")
    return slugify("_".join(parts), max_length)


def slugify(value: str, max_length: int = LABEL_MAX) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    cleaned = re.sub(r"[^A-Za-z0-9._+-]+", "-", normalized).strip("-._")
    return cleaned[:max_length].rstrip("-._")


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if math.isfinite(value) and value == round(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        return "-".join(_format_value(v) for v in value)
    return str(value)


def walltime_hours(value: str) -> float | None:
    """Parse ``[D-]H:MM:SS`` into hours."""
    match = re.fullmatch(r"(?:(\d+)-)?(\d+):([0-5]\d):([0-5]\d)", str(value).strip())
    if not match:
        return None
    days, hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    total = days * 24 + hours + minutes / 60 + seconds / 3600
    return total if total > 0 else None


def core_count(job: dict[str, Any], resource_style: str) -> int:
    if resource_style == "rsc":
        processes = int(job.get("processes", job.get("ntasks", 1)) or 1)
        cores = int(job.get("cores", job.get("threads", 1)) or 1)
        return max(processes * cores, 1)
    ntasks = int(job.get("ntasks", job.get("processes", 1)) or 1)
    per_task = int(job.get("cpus_per_task", job.get("cores", 1)) or 1)
    return max(ntasks * per_task, 1)


def core_hours(job: dict[str, Any], resource_style: str) -> float:
    hours = walltime_hours(str(job.get("walltime", ""))) or 0.0
    return core_count(job, resource_style) * hours
