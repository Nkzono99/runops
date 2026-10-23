"""Acceptance 9b and adapter helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from runops.adapters.base import set_dotted, toml_override
from runops.adapters.registry import resolve_adapter
from runops.errors import UsageError

LOCAL_ADAPTER = """
from pathlib import Path

class Adapter:
    name = "{name}"
    def render_inputs(self, params, run_dir):
        (run_dir / "input" / "local.txt").write_text(repr(sorted(params.items())))
        return ["input/local.txt"]
    def build_command(self, runtime, run_dir):
        return ["{name}-exe", "input/local.txt"]
    def detect_status(self, run_dir):
        return "completed"
"""


def write_dist(site: Path, name: str, module_source: str, version: str = "1.0") -> None:
    """Create an installed distribution with a runops.adapters entry point."""
    site.mkdir(parents=True, exist_ok=True)
    module = f"{name}_runops"
    (site / f"{module}.py").write_text(module_source)
    info = site / f"{module}-{version}.dist-info"
    info.mkdir(exist_ok=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {module}\nVersion: {version}\n")
    (info / "entry_points.txt").write_text(f"[runops.adapters]\n{name} = {module}:Adapter\n")
    (info / "RECORD").write_text("")


def test_project_local_adapter(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (project_dir / "adapters").mkdir()
    (project_dir / "adapters/localsim.py").write_text(LOCAL_ADAPTER.format(name="localsim"))
    resolved = resolve_adapter("localsim", project_dir)
    assert resolved.source == "project-local"


def test_entry_point_wins_over_local(project_dir: Path) -> None:
    (project_dir / "adapters").mkdir()
    (project_dir / "adapters/dualsim.py").write_text(LOCAL_ADAPTER.format(name="dualsim"))
    site = project_dir / ".venv/lib/python3.99/site-packages"
    write_dist(site, "dualsim", LOCAL_ADAPTER.format(name="dualsim"), "2.5")
    resolved = resolve_adapter("dualsim", project_dir)
    assert resolved.source == "entry-point"
    assert resolved.version == "2.5"


def test_missing_adapter(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(UsageError, match=r"adapters/nosuch\.py"):
        resolve_adapter("nosuch", project_dir)
    cfg = project_dir / "runops.toml"
    cfg.write_text(cfg.read_text() + '\n[simulators.ghost]\nadapter = "nosuch"\nexecutable = "x"\n')
    case = project_dir / "cases/g"
    case.mkdir()
    (case / "case.toml").write_text('[case]\nsimulator = "ghost"\n[job]\nwalltime = "1:00:00"\n')
    res = cli("new", "g")
    assert res.code == 2 and "pip install" in res.err


def test_contract_violation(project_dir: Path) -> None:
    (project_dir / "adapters").mkdir()
    (project_dir / "adapters/bad.py").write_text("class Adapter:\n    name = 'bad'\n")
    with pytest.raises(UsageError, match="render_inputs"):
        resolve_adapter("bad", project_dir)


def test_set_dotted_and_toml_override(tmp_path: Path) -> None:
    config = {"species": [{"q": 1}, {"q": 2}]}
    set_dotted(config, "plasma.wc", 0.5)
    set_dotted(config, "species[1].q", -1)
    set_dotted(config, "species.0.q", 9)
    assert config == {"species": [{"q": 9}, {"q": -1}], "plasma": {"wc": 0.5}}
    with pytest.raises(ValueError):
        set_dotted(config, "species.5.q", 1)
    with pytest.raises(ValueError):
        set_dotted(config, "plasma[0].x", 1)
    path = tmp_path / "in.toml"
    path.write_text("[boundary]\nradius = 1.0\n")
    toml_override(path, {"boundary.radius": 7e-6, "output.dir": "latest"})
    assert path.read_text() == '[boundary]\nradius = 7e-06\n\n[output]\ndir = "latest"\n'


def test_param_warnings_name_the_adapter_and_a_newer_executable(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    source = LOCAL_ADAPTER.format(name="schemasim") + (
        "    def validate_params(self, params):\n"
        "        return ['step_growth is not a known key']\n"
    )
    (project_dir / "adapters").mkdir()
    (project_dir / "adapters/schemasim.py").write_text(source)
    exe = project_dir / "bin/schemasim"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    cfg = project_dir / "runops.toml"
    cfg.write_text(
        cfg.read_text()
        + '\n[simulators.schemasim]\nadapter = "schemasim"\n'
        + 'resolver_mode = "local_executable"\nexecutable = "bin/schemasim"\n'
    )
    case = project_dir / "cases/sch"
    case.mkdir()
    (case / "case.toml").write_text(
        '[case]\nname = "sch"\nsimulator = "schemasim"\n[job]\nwalltime = "1:00:00"\n'
    )
    res = cli("new", "sch", "--why", "w")
    assert res.code == 0, res.err
    assert "adapter schemasim: step_growth is not a known key" in res.err
    assert "local_executable executable" in res.err
