"""Direct tests for init helper modules."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import typer

from runops.cli.init import prompting as prompting_mod
from runops.cli.init import serialization as serialization_mod

if TYPE_CHECKING:
    from pytest import MonkeyPatch


class _FakeRegistry:
    def __init__(self) -> None:
        self._adapters = {
            "emses": _FakeAdapter("emses"),
            "beach": _FakeAdapter("beach"),
        }

    def list_adapters(self) -> list[str]:
        return list(self._adapters)

    def get(self, name: str) -> _FakeAdapter:
        return self._adapters[name]


class _FakeAdapter:
    def __init__(self, name: str) -> None:
        self._name = name

    def default_config(self) -> dict[str, str]:
        return {"adapter": self._name, "executable": f"{self._name}-bin"}

    def interactive_config(self) -> dict[str, str]:
        return {"adapter": self._name, "executable": f"{self._name}-custom"}


def test_search_knowledge_repos_filters_supported_names(
    monkeypatch: MonkeyPatch,
) -> None:
    result = MagicMock(
        returncode=0,
        stdout=(
            '[{"nameWithOwner":"lab/shared_knowledge","sshUrl":"git@a:b.git"},'
            '{"nameWithOwner":"lab/shared-knowledge","sshUrl":"git@a:c.git"},'
            '{"nameWithOwner":"lab/plain","sshUrl":"git@a:d.git"}]'
        ),
    )
    monkeypatch.setattr(
        "runops.cli.init.prompting.subprocess.run",
        lambda *args, **kwargs: result,
    )

    repos = prompting_mod._search_knowledge_repos()

    assert repos == [
        ("lab/shared_knowledge", "git@a:b.git"),
        ("lab/shared-knowledge", "git@a:c.git"),
    ]


def test_search_knowledge_repos_handles_missing_gh(monkeypatch: MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError

    monkeypatch.setattr("runops.cli.init.prompting.subprocess.run", fail)
    assert prompting_mod._search_knowledge_repos() == []


def test_prompt_knowledge_sources_supports_candidate_and_manual_entries(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        prompting_mod,
        "_search_knowledge_repos",
        lambda: [("lab/shared_knowledge", "git@github.com:lab/shared_knowledge.git")],
    )

    answers = iter(
        [
            "1,9",
            "https://github.com/lab/manual-kb.git",
            "manual-kb",
            "../local-kb",
            "local-kb",
            "",
        ]
    )
    monkeypatch.setattr(
        "runops.cli.init.prompting.typer.prompt",
        lambda *args, **kwargs: next(answers),
    )

    sources = prompting_mod._prompt_knowledge_sources(tmp_path)

    assert [source.name for source in sources] == [
        "shared_knowledge",
        "manual-kb",
        "local-kb",
    ]
    assert [source.source_type for source in sources] == ["git", "git", "path"]


def test_prompt_simulators_uses_default_and_interactive_configs(
    monkeypatch: MonkeyPatch,
) -> None:
    registry = _FakeRegistry()
    monkeypatch.setattr(
        "runops.adapters.registry.get_global_registry",
        lambda: registry,
    )

    answers = iter(["1,beach,9,unknown", "emses"])
    confirms = iter([False, True])
    monkeypatch.setattr(
        "runops.cli.init.prompting.typer.prompt",
        lambda *args, **kwargs: next(answers),
    )
    monkeypatch.setattr(
        "runops.cli.init.prompting.typer.confirm",
        lambda *args, **kwargs: next(confirms),
    )

    selected, configs = prompting_mod._prompt_simulators()
    interactive_selected, interactive_configs = prompting_mod._prompt_simulators()

    assert selected == ["emses", "beach"]
    assert configs["emses"]["executable"] == "emses-bin"
    assert configs["beach"]["executable"] == "beach-bin"
    assert interactive_selected == ["emses"]
    assert interactive_configs["emses"]["executable"] == "emses-custom"


def test_load_site_profiles_reads_bundled_site_files() -> None:
    profiles = prompting_mod._load_site_profiles()

    assert "camphor" in profiles
    assert profiles["camphor"].source_path.name == "camphor.toml"
    assert profiles["camphor"].codex_plugins
    assert profiles["camphor"].codex_plugins[0].name == "kudpc-hpc-codex-plugin"


def test_prompt_launchers_supports_site_and_manual_launchers(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    profile = prompting_mod._BundledSiteProfile(
        name="camphor",
        launcher={"type": "srun", "args": "--mpi=pmix"},
        source_path=tmp_path / "camphor.toml",
    )
    monkeypatch.setattr(
        prompting_mod,
        "_load_site_profiles",
        lambda: {"camphor": profile},
    )

    answers = iter(["1", "srun", "cluster-srun", "--mpi=pmix", "intel mpi", "mystery"])
    confirms = iter([True])
    monkeypatch.setattr(
        "runops.cli.init.prompting.typer.prompt",
        lambda *args, **kwargs: next(answers),
    )
    monkeypatch.setattr(
        "runops.cli.init.prompting.typer.confirm",
        lambda *args, **kwargs: next(confirms),
    )

    launchers, selected_profile = prompting_mod._prompt_launchers()
    manual_launchers, manual_profile = prompting_mod._prompt_launchers()
    invalid_launchers, invalid_profile = prompting_mod._prompt_launchers()

    assert launchers == {"camphor": {"type": "srun", "args": "--mpi=pmix"}}
    assert selected_profile == profile
    assert manual_launchers == {
        "cluster-srun": {
            "type": "srun",
            "use_slurm_ntasks": True,
            "args": "--mpi=pmix",
            "modules": ["intel", "mpi"],
        }
    }
    assert manual_profile is None
    assert invalid_launchers == {}
    assert invalid_profile is None


def test_build_simulators_toml_and_campaign(
    monkeypatch: MonkeyPatch,
) -> None:
    registry = _FakeRegistry()
    monkeypatch.setattr(
        "runops.adapters.registry.get_global_registry",
        lambda: registry,
    )

    simulators = serialization_mod._build_simulators_toml(["emses"])
    campaign = serialization_mod._build_campaign_toml(
        "demo",
        ["emses"],
        schema_base_url="https://example.test/schemas",
    )

    assert "[simulators.emses]" in simulators
    assert 'adapter = "emses"' in simulators
    assert 'project_name = "demo"' not in campaign
    assert "demo" in campaign
    assert "emses" in campaign

    with pytest.raises(typer.BadParameter):
        serialization_mod._build_simulators_toml(["missing"])


def test_build_serialized_toml_manual_fallback(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(serialization_mod, "tomli_w", None)

    simulators = serialization_mod._build_simulators_toml_from_configs(
        {
            "emses": {
                "adapter": "emses",
                "packages": ["emout", "h5py"],
            }
        }
    )
    launchers = serialization_mod._build_launchers_toml(
        {
            "srun": {
                "type": "srun",
                "use_slurm_ntasks": True,
                "modules": ["intel", "mpi"],
            }
        }
    )

    assert 'packages = ["emout", "h5py"]' in simulators
    assert "use_slurm_ntasks = true" in launchers
    assert 'modules = ["intel", "mpi"]' in launchers
