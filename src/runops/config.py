"""``runops.toml`` loading and validation (SPEC §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runops.errors import UsageError
from runops.util import load_toml, tomllib

CONFIG_FILE = "runops.toml"
SCHEMA_VERSION = 2
RESOLVER_MODES = ("package", "local_executable", "local_source")
LAUNCHER_KINDS = ("srun", "mpirun", "mpiexec", "none")

_SITE_KEYS = {
    "name",
    "resource_style",
    "modules",
    "stdout",
    "stderr",
    "extra_sbatch",
    "setup_commands",
    "env",
}
_SIM_KEYS = {
    "adapter",
    "package",
    "executable",
    "resolver_mode",
    "modules",
    "source_repo",
    "build_command",
    "command",
    "success_marker",
    "env",
}
_LAUNCHER_KEYS = {
    "kind",
    "command",
    "use_slurm_ntasks",
    "args",
    "extra_options",
    "modules",
}
_DEFAULT_KEYS = {
    "launcher",
    "scratch_ttl_days",
    "list_since_days",
    "tidy_failed_days",
    "tidy_archive_days",
    "label_max_length",
}
_TOP_KEYS = {"schema", "project", "site", "simulators", "launchers", "defaults"}


@dataclass
class SiteConfig:
    name: str = ""
    resource_style: str = "standard"
    modules: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    extra_sbatch: list[str] = field(default_factory=list)
    setup_commands: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class SimulatorConfig:
    name: str
    adapter: str
    package: str = ""
    executable: str = ""
    resolver_mode: str = "package"
    modules: list[str] = field(default_factory=list)
    source_repo: str = ""
    build_command: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class LauncherConfig:
    name: str
    kind: str = "srun"
    command: str = ""
    use_slurm_ntasks: bool = False
    args: str = ""
    extra_options: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)


@dataclass
class Defaults:
    launcher: str = ""
    scratch_ttl_days: float = 7
    list_since_days: float = 30
    tidy_failed_days: float = 30
    tidy_archive_days: float = 90
    label_max_length: int = 48


@dataclass
class ProjectConfig:
    root: Path
    name: str
    site: SiteConfig
    simulators: dict[str, SimulatorConfig]
    launchers: dict[str, LauncherConfig]
    defaults: Defaults
    warnings: list[str] = field(default_factory=list)

    def simulator(self, name: str) -> SimulatorConfig:
        try:
            return self.simulators[name]
        except KeyError:
            known = ", ".join(sorted(self.simulators)) or "(none)"
            raise UsageError(
                f"simulator {name!r} is not defined in runops.toml (known: {known})"
            ) from None

    def launcher(self, name: str) -> LauncherConfig:
        name = name or self.defaults.launcher
        if not name:
            if len(self.launchers) == 1:
                return next(iter(self.launchers.values()))
            return LauncherConfig(name="srun", kind="srun", command="srun")
        try:
            return self.launchers[name]
        except KeyError:
            known = ", ".join(sorted(self.launchers)) or "(none)"
            raise UsageError(
                f"launcher {name!r} is not defined in runops.toml (known: {known})"
            ) from None


def find_project_root(start: Path | None = None) -> Path:
    """Search upward from *start* for ``runops.toml`` with ``schema = 2``."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_FILE).is_file():
            return candidate
        if (candidate / "simulators.toml").is_file():
            raise UsageError(
                f"{candidate} looks like a runops v1 project; "
                "run `runo migrate-v1 --dry-run` there first"
            )
    raise UsageError(f"no {CONFIG_FILE} found in {current} or its parents; run `runo init`")


def load_config(root: Path) -> ProjectConfig:
    """Load and validate ``<root>/runops.toml``."""
    path = root / CONFIG_FILE
    try:
        data = load_toml(path)
    except FileNotFoundError:
        raise UsageError(f"{path} not found") from None
    except tomllib.TOMLDecodeError as exc:
        raise UsageError(f"{path}: invalid TOML: {exc}") from None
    return parse_config(root, data)


def parse_config(root: Path, data: dict[str, Any]) -> ProjectConfig:
    warnings: list[str] = []
    schema = data.get("schema")
    if schema != SCHEMA_VERSION:
        raise UsageError(
            f"runops.toml schema is {schema!r}, expected {SCHEMA_VERSION}. "
            "If this is a v1 project, run `runo migrate-v1`."
        )
    _warn_unknown(data, _TOP_KEYS, "runops.toml", warnings)

    project = _table(data, "project")
    name = str(project.get("name") or root.name)

    site_raw = _table(data, "site")
    _warn_unknown(site_raw, _SITE_KEYS, "[site]", warnings)
    site = SiteConfig(
        name=str(site_raw.get("name", "")),
        resource_style=str(site_raw.get("resource_style", "standard")),
        modules=_str_list(site_raw.get("modules"), "[site].modules"),
        stdout=str(site_raw.get("stdout", "")),
        stderr=str(site_raw.get("stderr", "")),
        extra_sbatch=_str_list(site_raw.get("extra_sbatch"), "[site].extra_sbatch"),
        setup_commands=_str_list(site_raw.get("setup_commands"), "[site].setup_commands"),
        env={str(k): str(v) for k, v in _table(site_raw, "env").items()},
    )
    if site.resource_style not in ("standard", "rsc"):
        raise UsageError(
            f"[site].resource_style must be 'standard' or 'rsc', got {site.resource_style!r}"
        )

    simulators: dict[str, SimulatorConfig] = {}
    for sim_name, raw in _table(data, "simulators").items():
        if not isinstance(raw, dict):
            raise UsageError(f"[simulators.{sim_name}] must be a table")
        _warn_unknown(raw, _SIM_KEYS, f"[simulators.{sim_name}]", warnings)
        mode = str(raw.get("resolver_mode", "package"))
        if mode not in RESOLVER_MODES:
            raise UsageError(
                f"[simulators.{sim_name}].resolver_mode must be one of {', '.join(RESOLVER_MODES)}"
            )
        simulators[sim_name] = SimulatorConfig(
            name=sim_name,
            adapter=str(raw.get("adapter") or sim_name),
            package=str(raw.get("package", "")),
            executable=str(raw.get("executable", "")),
            resolver_mode=mode,
            modules=_str_list(raw.get("modules"), f"[simulators.{sim_name}].modules"),
            source_repo=str(raw.get("source_repo", "")),
            build_command=str(raw.get("build_command", "")),
            raw=dict(raw),
        )

    launchers: dict[str, LauncherConfig] = {}
    for launcher_name, raw in _table(data, "launchers").items():
        if not isinstance(raw, dict):
            raise UsageError(f"[launchers.{launcher_name}] must be a table")
        _warn_unknown(raw, _LAUNCHER_KEYS, f"[launchers.{launcher_name}]", warnings)
        kind = str(raw.get("kind", "srun"))
        if kind not in LAUNCHER_KINDS:
            raise UsageError(
                f"[launchers.{launcher_name}].kind must be one of {', '.join(LAUNCHER_KINDS)}"
            )
        launchers[launcher_name] = LauncherConfig(
            name=launcher_name,
            kind=kind,
            command=str(raw.get("command") or ("" if kind == "none" else kind)),
            use_slurm_ntasks=bool(raw.get("use_slurm_ntasks", False)),
            args=str(raw.get("args", "")),
            extra_options=_str_list(
                raw.get("extra_options"), f"[launchers.{launcher_name}].extra_options"
            ),
            modules=_str_list(raw.get("modules"), f"[launchers.{launcher_name}].modules"),
        )

    defaults_raw = _table(data, "defaults")
    _warn_unknown(defaults_raw, _DEFAULT_KEYS, "[defaults]", warnings)
    defaults = Defaults(
        launcher=str(defaults_raw.get("launcher", "")),
        scratch_ttl_days=_positive(defaults_raw, "scratch_ttl_days", 7),
        list_since_days=_positive(defaults_raw, "list_since_days", 30),
        tidy_failed_days=_positive(defaults_raw, "tidy_failed_days", 30),
        tidy_archive_days=_positive(defaults_raw, "tidy_archive_days", 90),
        label_max_length=int(_positive(defaults_raw, "label_max_length", 48)),
    )
    if defaults.label_max_length < 8:
        raise UsageError("[defaults].label_max_length must be at least 8")
    if defaults.launcher and defaults.launcher not in launchers:
        raise UsageError(f"[defaults].launcher {defaults.launcher!r} is not a defined launcher")
    return ProjectConfig(
        root=root,
        name=name,
        site=site,
        simulators=simulators,
        launchers=launchers,
        defaults=defaults,
        warnings=warnings,
    )


def _positive(table: dict[str, Any], key: str, default: float) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise UsageError(f"[defaults].{key} must be a positive number, got {value!r}")
    return float(value)


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise UsageError(f"[{key}] must be a table")
    return value


def _str_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise UsageError(f"{where} must be a list of strings")
    return [str(v) for v in value]


def _warn_unknown(data: dict[str, Any], known: set[str], where: str, warnings: list[str]) -> None:
    for key in data:
        if key not in known:
            warnings.append(f"{where}: unknown key {key!r} ignored")
