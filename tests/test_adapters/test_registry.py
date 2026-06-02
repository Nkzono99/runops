"""Tests for adapter registry."""

from __future__ import annotations

import importlib.machinery
from pathlib import Path
from typing import Any

import pytest

from runops.adapters.base import SimulatorAdapter
from runops.adapters.registry import (
    ADAPTER_ENTRY_POINT_GROUP,
    AdapterImportError,
    AdapterRegistry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubAdapter(SimulatorAdapter):
    """Minimal concrete adapter for registry tests."""

    adapter_name = "stub"

    @property
    def name(self) -> str:
        return self.adapter_name

    def render_inputs(self, case_data: dict[str, Any], run_dir: Path) -> list[str]:
        return []

    def resolve_runtime(
        self, simulator_config: dict[str, Any], resolver_mode: str
    ) -> dict[str, Any]:
        return {}

    def build_program_command(
        self, runtime_info: dict[str, Any], run_dir: Path
    ) -> list[str]:
        return []

    def detect_outputs(self, run_dir: Path) -> dict[str, Any]:
        return {}

    def detect_status(self, run_dir: Path) -> str:
        return "unknown"

    def summarize(self, run_dir: Path) -> dict[str, Any]:
        return {}

    def collect_provenance(self, runtime_info: dict[str, Any]) -> dict[str, Any]:
        return {}


class _NoNameAdapter(_StubAdapter):
    """Adapter without adapter_name for error-path testing."""

    adapter_name = ""


class _FakeEntryPoint:
    """Small test double for importlib.metadata.EntryPoint."""

    def __init__(self, name: str, loaded: object) -> None:
        self.name = name
        self._loaded = loaded

    def load(self) -> object:
        if isinstance(self._loaded, Exception):
            raise self._loaded
        return self._loaded


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry() -> AdapterRegistry:
    """Fresh registry for each test."""
    return AdapterRegistry()


def test_register_and_get(registry: AdapterRegistry) -> None:
    """Register an adapter and retrieve it by name."""
    registry.register(_StubAdapter)
    assert registry.get("stub") is _StubAdapter


def test_register_with_explicit_name(registry: AdapterRegistry) -> None:
    """Explicit name overrides adapter_name."""
    registry.register(_StubAdapter, name="custom")
    assert registry.get("custom") is _StubAdapter


def test_duplicate_registration_raises(registry: AdapterRegistry) -> None:
    """Registering the same name twice should raise ValueError."""
    registry.register(_StubAdapter)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_StubAdapter)


def test_get_unknown_raises(registry: AdapterRegistry) -> None:
    """Looking up an unregistered name should raise KeyError."""
    with pytest.raises(KeyError, match="Unknown adapter"):
        registry.get("nonexistent")


def test_no_name_raises(registry: AdapterRegistry) -> None:
    """Adapter without adapter_name and no explicit name should raise."""
    with pytest.raises(AttributeError, match="must define"):
        registry.register(_NoNameAdapter)


def test_list_adapters(registry: AdapterRegistry) -> None:
    """list_adapters returns sorted names."""
    registry.register(_StubAdapter, name="b_adapter")
    registry.register(_StubAdapter, name="a_adapter")
    assert registry.list_adapters() == ["a_adapter", "b_adapter"]


def test_list_adapters_empty(registry: AdapterRegistry) -> None:
    """Empty registry returns empty list."""
    assert registry.list_adapters() == []


def test_default_version_capture_commands_quote_paths(tmp_path: Path) -> None:
    """Default version capture writes to work/ and quotes spaced executables."""
    adapter = _StubAdapter()
    commands = adapter.build_version_capture_commands(
        {"executable": "/opt/my solver/bin/solver"},
        [],
        tmp_path,
    )

    assert len(commands) == 1
    command = commands[0]
    assert "SIMULATOR_VERSION.txt" in command
    assert str(tmp_path / "work" / "SIMULATOR_VERSION.txt") in command
    assert "'/opt/my solver/bin/solver' --version" in command
    assert "printf '%s\\n'" in command


def test_load_from_config_unknown_module(registry: AdapterRegistry) -> None:
    """load_from_config logs a warning for missing adapter modules."""
    config = {
        "simulators": {
            "nonexistent_sim": {
                "adapter": "totally_fake_adapter",
                "resolver_mode": "package",
            }
        }
    }
    # Should not raise, just warn
    registry.load_from_config(config)
    assert "totally_fake_adapter" not in registry.list_adapters()


def test_load_entry_points_registers_external_adapter(
    registry: AdapterRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installed entry points can register adapters outside runops.contrib."""

    def fake_entry_points() -> dict[str, list[_FakeEntryPoint]]:
        return {ADAPTER_ENTRY_POINT_GROUP: [_FakeEntryPoint("external", _StubAdapter)]}

    monkeypatch.setattr(
        "runops.adapters.registry.importlib_metadata.entry_points",
        fake_entry_points,
    )

    registry.load_entry_points()

    assert registry.get("external") is _StubAdapter


def test_load_from_config_prefers_matching_entry_point(
    registry: AdapterRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config loading checks entry points before bundled module conventions."""
    config = {
        "simulators": {
            "external_sim": {
                "adapter": "external",
                "resolver_mode": "package",
            }
        }
    }

    def fake_entry_points() -> dict[str, list[_FakeEntryPoint]]:
        return {ADAPTER_ENTRY_POINT_GROUP: [_FakeEntryPoint("external", _StubAdapter)]}

    monkeypatch.setattr(
        "runops.adapters.registry.importlib_metadata.entry_points",
        fake_entry_points,
    )

    registry.load_from_config(config)

    assert registry.get("external") is _StubAdapter


def test_load_from_config_raises_for_broken_entry_point(
    registry: AdapterRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured external entry point that fails to load is not swallowed."""
    config = {
        "simulators": {
            "broken_sim": {
                "adapter": "broken_external",
                "resolver_mode": "package",
            }
        }
    }

    def fake_entry_points() -> dict[str, list[_FakeEntryPoint]]:
        return {
            ADAPTER_ENTRY_POINT_GROUP: [
                _FakeEntryPoint("broken_external", ImportError("missing dependency"))
            ]
        }

    monkeypatch.setattr(
        "runops.adapters.registry.importlib_metadata.entry_points",
        fake_entry_points,
    )

    with pytest.raises(AdapterImportError, match="broken_external"):
        registry.load_from_config(config)


def test_load_entry_points_can_skip_broken_adapters(
    registry: AdapterRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global discovery can skip broken optional adapters during package import."""

    def fake_entry_points() -> dict[str, list[_FakeEntryPoint]]:
        return {
            ADAPTER_ENTRY_POINT_GROUP: [
                _FakeEntryPoint("broken_external", ImportError("missing dependency"))
            ]
        }

    monkeypatch.setattr(
        "runops.adapters.registry.importlib_metadata.entry_points",
        fake_entry_points,
    )

    registry.load_entry_points(fail_on_error=False)

    assert "broken_external" not in registry.list_adapters()


def test_load_from_config_raises_for_broken_adapter_module(
    registry: AdapterRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A discovered adapter module with broken imports should fail loudly."""
    config = {
        "simulators": {
            "broken_sim": {
                "adapter": "broken_adapter",
                "resolver_mode": "package",
            }
        }
    }

    def fake_find_spec(module_path: str):
        if module_path == "runops.adapters.contrib.broken_adapter":
            return importlib.machinery.ModuleSpec(module_path, loader=None)
        return None

    def fake_import_module(module_path: str):
        raise ImportError("missing optional dependency")

    monkeypatch.setattr(
        "runops.adapters.registry.importlib.util.find_spec",
        fake_find_spec,
    )
    monkeypatch.setattr(
        "runops.adapters.registry.importlib.import_module",
        fake_import_module,
    )

    with pytest.raises(AdapterImportError, match="missing optional dependency"):
        registry.load_from_config(config)


def test_load_from_config_skips_already_registered(
    registry: AdapterRegistry,
) -> None:
    """Already-registered adapters are not re-imported."""
    registry.register(_StubAdapter, name="my_adapter")
    config = {
        "simulators": {
            "some_sim": {"adapter": "my_adapter"},
        }
    }
    # Should not raise even though the module doesn't exist
    registry.load_from_config(config)


# ---------------------------------------------------------------------------
# Global convenience API
# ---------------------------------------------------------------------------


def test_global_registry_has_generic() -> None:
    """Importing the adapters package registers GenericAdapter globally."""
    from runops.adapters import list_adapters

    assert "generic" in list_adapters()


def test_global_get_generic() -> None:
    """Global get() returns GenericAdapter for 'generic'."""
    from runops.adapters import get
    from runops.adapters.generic import GenericAdapter

    assert get("generic") is GenericAdapter
