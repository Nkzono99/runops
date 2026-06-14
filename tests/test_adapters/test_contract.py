"""Cross-adapter contract tests for built-in simulator adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from runops.adapters import (
    BeachAdapter,
    EmseAdapter,
    GenericAdapter,
    get,
    list_adapters,
)
from runops.adapters.base import SimulatorAdapter
from runops.core.codex_plugin import CodexPluginRecommendation
from runops.core.plugins import (
    detect_codex_plugin_conflicts,
    validate_codex_plugin_recommendation,
)
from tests.factories import write_toml


@dataclass(frozen=True)
class AdapterContractSpec:
    """Inputs needed to exercise the common SimulatorAdapter contract."""

    adapter_cls: type[SimulatorAdapter]
    template_name: str | None
    template_data: dict[str, Any] | None
    params: dict[str, Any]
    expected_input: str

    @property
    def name(self) -> str:
        """Return the instantiated adapter name for pytest ids."""
        return self.adapter_cls().name


ADAPTER_CONTRACT_SPECS = (
    AdapterContractSpec(
        adapter_cls=GenericAdapter,
        template_name=None,
        template_data=None,
        params={"nx": 16},
        expected_input="input/params.json",
    ),
    AdapterContractSpec(
        adapter_cls=EmseAdapter,
        template_name="plasma.toml",
        template_data={
            "jobcon": {"nstep": 10},
            "tmgrid": {"dt": 0.01, "nx": 8, "ny": 1, "nz": 8},
            "system": {"nspec": 1},
            "species": [{"wp": 1.0, "qm": -1.0, "npin": 100}],
        },
        params={"jobcon.nstep": 20},
        expected_input="input/plasma.toml",
    ),
    AdapterContractSpec(
        adapter_cls=BeachAdapter,
        template_name="beach.toml",
        template_data={
            "sim": {"dt": 1.0e-8, "batch_count": 1, "max_step": 10},
            "mesh": {"mode": "template"},
            "output": {"write_files": True},
        },
        params={"sim.batch_count": 2},
        expected_input="input/beach.toml",
    ),
)


def _make_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "R20260424-0001"
    for subdir in ("input", "work", "analysis", "status", "submit"):
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)
    return run_dir


def _make_case_data(spec: AdapterContractSpec, tmp_path: Path) -> dict[str, Any]:
    case_dir = tmp_path / f"case_{spec.name}"
    case_dir.mkdir()
    if spec.template_name and spec.template_data is not None:
        write_toml(case_dir / spec.template_name, spec.template_data)
    return {
        "case": {
            "name": f"{spec.name}_case",
            "simulator": spec.name,
            "launcher": "srun",
            "case_dir": str(case_dir),
        },
        "params": dict(spec.params),
    }


@pytest.mark.parametrize(
    "spec",
    ADAPTER_CONTRACT_SPECS,
    ids=lambda spec: spec.name,
)
def test_builtin_adapter_is_registered(spec: AdapterContractSpec) -> None:
    """Every built-in adapter should be reachable through the global registry."""
    adapter = spec.adapter_cls()
    assert adapter.name in list_adapters()
    assert get(adapter.name) is spec.adapter_cls


@pytest.mark.parametrize(
    "spec",
    ADAPTER_CONTRACT_SPECS,
    ids=lambda spec: spec.name,
)
def test_contract_metadata_methods_return_expected_types(
    spec: AdapterContractSpec,
) -> None:
    """Static adapter metadata methods must return machine-readable values."""
    defaults = spec.adapter_cls.default_config()
    assert isinstance(defaults, dict)
    assert defaults.get("adapter") == spec.name
    assert isinstance(spec.adapter_cls.parameter_schema(), dict)
    assert isinstance(spec.adapter_cls.default_plot_recipes(), dict)
    assert isinstance(spec.adapter_cls.required_outputs(), dict)
    assert isinstance(spec.adapter_cls.knowledge_sources(), dict)
    assert isinstance(spec.adapter_cls.doc_repos(), list)
    assert isinstance(spec.adapter_cls.pip_packages(), list)
    assert isinstance(spec.adapter_cls.codex_plugins(), list)
    assert isinstance(spec.adapter_cls.case_template(), dict)
    assert isinstance(spec.adapter_cls.agent_guide(), str)


@pytest.mark.parametrize(
    ("adapter_cls", "expected_plugins", "forbidden_phrases"),
    [
        (
            BeachAdapter,
            ("BEACH Context", "beach-context"),
            (
                "パラメータサーベイでよく変えるパラメータ",
                "environment.electron_density",
            ),
        ),
        (
            EmseAdapter,
            ("MPIEMSES3D Context", "emout Context", "delegated_capabilities"),
            ("主要な namelist", "species[0].temperature"),
        ),
    ],
    ids=["beach", "emses"],
)
def test_builtin_agent_guides_are_plugin_first_fallbacks(
    adapter_cls: type[SimulatorAdapter],
    expected_plugins: tuple[str, ...],
    forbidden_phrases: tuple[str, ...],
) -> None:
    """Bundled agent guides should not become long simulator manuals again."""
    guide = adapter_cls.agent_guide()

    for expected in expected_plugins:
        assert expected in guide
    for phrase in forbidden_phrases:
        assert phrase not in guide


@pytest.mark.parametrize(
    "spec",
    ADAPTER_CONTRACT_SPECS,
    ids=lambda spec: spec.name,
)
def test_contract_codex_plugin_recommendations_are_complete(
    spec: AdapterContractSpec,
) -> None:
    """Adapter plugin recommendations must be usable without project context."""
    recommendations = spec.adapter_cls.codex_plugins()

    assert all(
        isinstance(recommendation, CodexPluginRecommendation)
        for recommendation in recommendations
    )
    issues = [
        issue
        for recommendation in recommendations
        for issue in validate_codex_plugin_recommendation(recommendation)
    ]
    issues.extend(detect_codex_plugin_conflicts(recommendations))
    assert [issue.to_dict() for issue in issues] == []


@pytest.mark.parametrize(
    "spec",
    ADAPTER_CONTRACT_SPECS,
    ids=lambda spec: spec.name,
)
def test_contract_render_inputs_returns_relative_paths(
    spec: AdapterContractSpec,
    tmp_path: Path,
) -> None:
    """render_inputs should write expected input files and return relative paths."""
    adapter = spec.adapter_cls()
    run_dir = _make_run_dir(tmp_path)
    case_data = _make_case_data(spec, tmp_path)

    created = adapter.render_inputs(case_data, run_dir)

    assert spec.expected_input in created
    assert (run_dir / spec.expected_input).is_file()
    assert all(isinstance(path, str) for path in created)
    assert all(not Path(path).is_absolute() for path in created)


@pytest.mark.parametrize(
    "spec",
    ADAPTER_CONTRACT_SPECS,
    ids=lambda spec: spec.name,
)
def test_contract_runtime_and_command_methods_return_expected_types(
    spec: AdapterContractSpec,
    tmp_path: Path,
) -> None:
    """Runtime resolution and command construction should be launcher-agnostic."""
    adapter = spec.adapter_cls()
    run_dir = _make_run_dir(tmp_path)
    runtime = adapter.resolve_runtime({"executable": "python"}, "package")

    assert isinstance(runtime, dict)
    assert runtime.get("resolver_mode") == "package"
    assert runtime.get("executable")

    command = adapter.build_program_command(runtime, run_dir)
    assert command
    assert all(isinstance(part, str) for part in command)

    version_commands = adapter.build_version_capture_commands(runtime, command, run_dir)
    assert isinstance(version_commands, list)
    assert all(isinstance(command_line, str) for command_line in version_commands)


@pytest.mark.parametrize(
    "spec",
    ADAPTER_CONTRACT_SPECS,
    ids=lambda spec: spec.name,
)
def test_contract_detection_and_summary_are_safe_on_empty_run(
    spec: AdapterContractSpec,
    tmp_path: Path,
) -> None:
    """Detection methods should return structured empty-run results, not crash."""
    adapter = spec.adapter_cls()
    run_dir = _make_run_dir(tmp_path)

    outputs = adapter.detect_outputs(run_dir)
    status = adapter.detect_status(run_dir)
    summary = adapter.summarize(run_dir)

    assert isinstance(outputs, dict)
    assert isinstance(status, str)
    assert status
    assert isinstance(summary, dict)


@pytest.mark.parametrize(
    "spec",
    ADAPTER_CONTRACT_SPECS,
    ids=lambda spec: spec.name,
)
def test_contract_validation_and_provenance_return_expected_types(
    spec: AdapterContractSpec,
) -> None:
    """validate_params and collect_provenance should expose stable shapes."""
    adapter = spec.adapter_cls()
    issues = adapter.validate_params({"case": {"name": "case"}, "params": {}})
    provenance = adapter.collect_provenance(
        {
            "resolver_mode": "package",
            "executable": "python",
        }
    )

    assert isinstance(issues, list)
    assert isinstance(provenance, dict)
    for key in (
        "resolver_mode",
        "executable",
        "exe_hash",
        "git_commit",
        "git_dirty",
        "source_repo",
        "build_command",
    ):
        assert key in provenance
