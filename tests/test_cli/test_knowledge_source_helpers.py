"""Direct tests for knowledge source helper modules."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import typer

from runops.cli.knowledge import Path as KnowledgePath
from runops.cli.knowledge.common import _find_root
from runops.cli.knowledge.sources import (
    _list_sources,
    _print_external_status,
    _validate_requested_profiles,
)
from runops.core.knowledge_source import (
    ExternalKnowledgeMount,
    KnowledgeSource,
    save_knowledge_source,
)

if TYPE_CHECKING:
    from pytest import CaptureFixture, MonkeyPatch


def _create_project(root: Path) -> None:
    (root / "runops.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")


def test_find_root_uses_package_path_alias(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _create_project(tmp_path)
    monkeypatch.setattr(KnowledgePath, "cwd", lambda: tmp_path)

    assert _find_root() == tmp_path


def test_find_root_exits_when_project_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(KnowledgePath, "cwd", lambda: tmp_path)

    with pytest.raises(typer.Exit):
        _find_root()


def test_print_external_status_renders_simple_and_detailed(
    capsys: CaptureFixture[str],
) -> None:
    entries = [
        ExternalKnowledgeMount(
            name="kb",
            source_type="path",
            kind="profiles",
            path=Path("/tmp/kb"),
            display_path="refs/knowledge/kb",
            exists=True,
            profiles_enabled=["common"],
            profiles_available=["common", "advanced"],
        ),
        ExternalKnowledgeMount(
            name="project-kb",
            source_type="path",
            kind="project",
            path=Path("/tmp/project-kb"),
            display_path="../project-kb",
            exists=False,
        ),
    ]

    _print_external_status(entries, detailed=False)
    simple_output = capsys.readouterr().out
    _print_external_status(entries, detailed=True)
    detailed_output = capsys.readouterr().out

    assert "kb [profiles/path] (OK)" in simple_output
    assert "enabled profiles:   common" in simple_output
    assert "[project/path] project-kb (not ready)" in detailed_output


def test_list_sources_reports_empty_configuration(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "runops.cli.knowledge.sources.collect_external_knowledge",
        lambda _root: [],
    )

    _list_sources(tmp_path)

    assert "No knowledge sources configured." in capsys.readouterr().out


def test_validate_requested_profiles_rejects_unknown_profile(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _create_project(tmp_path)
    save_knowledge_source(
        tmp_path,
        KnowledgeSource(
            name="kb",
            source_type="path",
            kind="profiles",
            url=".",
            mount="refs/knowledge/kb",
        ),
    )
    (tmp_path / "refs" / "knowledge" / "kb").mkdir(parents=True)
    monkeypatch.setattr(
        "runops.cli.knowledge.sources.collect_external_knowledge",
        lambda _root: [
            ExternalKnowledgeMount(
                name="kb",
                source_type="path",
                kind="profiles",
                path=tmp_path / "refs" / "knowledge" / "kb",
                display_path="refs/knowledge/kb",
                exists=True,
                profiles_available=["common"],
            )
        ],
    )

    with pytest.raises(typer.Exit):
        _validate_requested_profiles(tmp_path, "kb", ["advanced"])
