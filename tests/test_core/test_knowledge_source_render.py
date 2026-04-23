"""Direct tests for knowledge source render helpers."""

from __future__ import annotations

from pathlib import Path

from runops.core.knowledge_source import KnowledgeConfig, KnowledgeSource
from runops.core.knowledge_source_render import (
    _resolve_profile_imports,
    render_imports,
)


def _create_source(tmp_path: Path, name: str = "kb") -> Path:
    source = tmp_path / name
    source.mkdir()
    (source / "profiles").mkdir()
    (source / "profiles" / "common.md").write_text("# Common\n", encoding="utf-8")
    return source


def test_resolve_profile_imports_uses_manifest_and_dedupes(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    (source / "docs").mkdir()
    (source / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (source / "entrypoints.toml").write_text(
        'imports = ["docs/guide.md"]\n'
        "[profiles.common]\n"
        'imports = ["profiles/common.md", "docs/guide.md"]\n',
        encoding="utf-8",
    )

    resolved = _resolve_profile_imports(
        source,
        KnowledgeSource(
            name="kb",
            source_type="path",
            url=".",
            mount="refs/knowledge/kb",
            profiles=["common"],
        ),
    )

    assert resolved == ["docs/guide.md", "profiles/common.md"]


def test_resolve_profile_imports_falls_back_to_profile_paths_and_claude(
    tmp_path: Path,
) -> None:
    source = _create_source(tmp_path)
    (source / "CLAUDE.md").write_text("# Imported\n", encoding="utf-8")

    profile_resolved = _resolve_profile_imports(
        source,
        KnowledgeSource(
            name="kb",
            source_type="path",
            url=".",
            mount="refs/knowledge/kb",
            profiles=["common"],
        ),
    )
    claude_resolved = _resolve_profile_imports(
        source,
        KnowledgeSource(
            name="kb",
            source_type="path",
            url=".",
            mount="refs/knowledge/kb",
            profiles=[],
        ),
    )

    assert profile_resolved == ["profiles/common.md"]
    assert claude_resolved == ["CLAUDE.md"]


def test_render_imports_reports_source_state_comments(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    invalid_mount = project / "refs" / "knowledge" / "invalid"
    invalid_mount.mkdir(parents=True)
    (invalid_mount / "entrypoints.toml").write_text(
        "[profiles.common\n",
        encoding="utf-8",
    )

    empty_mount = project / "refs" / "knowledge" / "empty"
    empty_mount.mkdir(parents=True)

    config = KnowledgeConfig(
        sources=[
            KnowledgeSource(
                name="skip-me",
                source_type="path",
                kind="project",
                url=".",
            ),
            KnowledgeSource(
                name="no-mount",
                source_type="path",
                kind="profiles",
                url=".",
                mount="",
            ),
            KnowledgeSource(
                name="not-mounted",
                source_type="path",
                kind="profiles",
                url=".",
                mount="refs/knowledge/missing",
            ),
            KnowledgeSource(
                name="invalid",
                source_type="path",
                kind="profiles",
                url=".",
                mount="refs/knowledge/invalid",
            ),
            KnowledgeSource(
                name="empty",
                source_type="path",
                kind="profiles",
                url=".",
                mount="refs/knowledge/empty",
            ),
        ],
    )

    imports_path = render_imports(project, config)
    content = imports_path.read_text(encoding="utf-8")

    assert "<!-- source no-mount: mount not configured -->" in content
    assert "<!-- source not-mounted: not mounted -->" in content
    assert "<!-- source invalid: invalid entrypoints" in content
    assert "<!-- source empty: no entrypoints enabled -->" in content


def test_render_imports_reports_invalid_and_missing_targets(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    mount = project / "refs" / "knowledge" / "kb"
    mount.mkdir(parents=True)
    (mount / "docs").mkdir()
    (mount / "docs" / "present.md").write_text("# Present\n", encoding="utf-8")
    (mount / "entrypoints.toml").write_text(
        'imports = ["../escape.md", "docs/missing.md", "profiles/missing.md", '
        '"docs/present.md"]\n',
        encoding="utf-8",
    )

    config = KnowledgeConfig(
        sources=[
            KnowledgeSource(
                name="kb",
                source_type="path",
                kind="profiles",
                url=".",
                mount="refs/knowledge/kb",
            ),
        ],
    )

    imports_path = render_imports(project, config)
    content = imports_path.read_text(encoding="utf-8")

    assert (
        "<!-- source kb: Import path escapes source root: ../escape.md -->" in content
    )
    assert "<!-- source kb: missing import target docs/missing.md -->" in content
    assert "<!-- profile missing not found in kb -->" in content
    assert "@refs/knowledge/kb/docs/present.md" in content


def test_render_imports_dedupes_extra_imports(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    mount = project / "refs" / "knowledge" / "kb"
    mount.mkdir(parents=True)
    (mount / "docs").mkdir()
    (mount / "docs" / "present.md").write_text("# Present\n", encoding="utf-8")
    (mount / "entrypoints.toml").write_text(
        'imports = ["docs/present.md"]\n',
        encoding="utf-8",
    )

    config = KnowledgeConfig(
        sources=[
            KnowledgeSource(
                name="kb",
                source_type="path",
                kind="profiles",
                url=".",
                mount="refs/knowledge/kb",
            ),
        ],
    )

    imports_path = render_imports(
        project,
        config,
        extra_imports=[
            "refs\\knowledge\\kb\\docs\\present.md",
            "extras/one.md",
            "extras/one.md",
        ],
    )
    lines = imports_path.read_text(encoding="utf-8").splitlines()

    assert lines.count("@refs/knowledge/kb/docs/present.md") == 1
    assert lines.count("@extras/one.md") == 1
