"""Tests for runops.core.knowledge_source module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from runops.core.knowledge import load_candidate_facts
from runops.core.knowledge_source import (
    KnowledgeConfig,
    KnowledgeSource,
    collect_external_knowledge,
    discover_profiles,
    discover_repo_imports,
    import_external_facts,
    import_external_insights,
    load_knowledge_config,
    remove_knowledge_source,
    render_imports,
    save_knowledge_source,
    set_knowledge_source_profiles,
    sync_source,
    validate_source_structure,
)


def _create_project(tmp_path: Path, extra_toml: str = "") -> Path:
    content = f'[project]\nname = "test-project"\n{extra_toml}'
    (tmp_path / "runops.toml").write_text(content)
    return tmp_path


def _create_knowledge_source(tmp_path: Path, name: str = "test-kb") -> Path:
    """Create a minimal knowledge source directory."""
    kb_dir = tmp_path / name
    kb_dir.mkdir()
    (kb_dir / "README.md").write_text("# Test Knowledge\n")
    profiles_dir = kb_dir / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "common.md").write_text("# Common Profile\nCommon knowledge.\n")
    (profiles_dir / "advanced.md").write_text("# Advanced Profile\nAdvanced.\n")
    return kb_dir


# ---------- load_knowledge_config ----------


def test_load_knowledge_config_returns_none_when_no_section(tmp_path: Path) -> None:
    _create_project(tmp_path)
    assert load_knowledge_config(tmp_path) is None


def test_load_knowledge_config_parses_sources(tmp_path: Path) -> None:
    toml = """
[knowledge]
enabled = true
mount_dir = "refs/knowledge"

[[knowledge.sources]]
name = "shared-kb"
type = "git"
kind = "profiles"
url = "https://github.com/lab/kb.git"
ref = "main"
mount = "refs/knowledge/shared-kb"
profiles = ["common", "emses"]

[[knowledge.sources]]
name = "local-kb"
type = "path"
kind = "project"
path = "../my-kb"
"""
    _create_project(tmp_path, toml)
    config = load_knowledge_config(tmp_path)

    assert config is not None
    assert config.enabled is True
    assert len(config.sources) == 2

    git_src = config.sources[0]
    assert git_src.name == "shared-kb"
    assert git_src.source_type == "git"
    assert git_src.kind == "profiles"
    assert git_src.url == "https://github.com/lab/kb.git"
    assert git_src.ref == "main"
    assert git_src.profiles == ["common", "emses"]

    path_src = config.sources[1]
    assert path_src.name == "local-kb"
    assert path_src.source_type == "path"
    assert path_src.kind == "project"
    assert path_src.url == "../my-kb"
    assert path_src.mount == ""


def test_load_knowledge_config_defaults(tmp_path: Path) -> None:
    _create_project(tmp_path, "\n[knowledge]\n")
    config = load_knowledge_config(tmp_path)

    assert config is not None
    assert config.enabled is True
    assert config.mount_dir == "refs/knowledge"
    assert config.derived_dir == ".runops/knowledge"
    assert config.auto_sync_on_setup is True
    assert config.generate_claude_imports is True
    assert config.sources == []


# ---------- save_knowledge_source ----------


def test_save_knowledge_source_creates_section(tmp_path: Path) -> None:
    _create_project(tmp_path)
    source = KnowledgeSource(
        name="test-kb",
        source_type="git",
        url="https://github.com/lab/kb.git",
        kind="profiles",
        mount="refs/knowledge/test-kb",
        profiles=["common"],
    )
    save_knowledge_source(tmp_path, source)

    config = load_knowledge_config(tmp_path)
    assert config is not None
    assert len(config.sources) == 1
    assert config.sources[0].name == "test-kb"
    assert config.sources[0].profiles == ["common"]


def test_save_knowledge_source_replaces_existing(tmp_path: Path) -> None:
    _create_project(tmp_path)
    source1 = KnowledgeSource(
        name="kb",
        source_type="git",
        url="https://old.git",
        kind="profiles",
        mount="refs/knowledge/kb",
    )
    save_knowledge_source(tmp_path, source1)

    source2 = KnowledgeSource(
        name="kb",
        source_type="git",
        url="https://new.git",
        kind="profiles",
        mount="refs/knowledge/kb",
        profiles=["updated"],
    )
    save_knowledge_source(tmp_path, source2)

    config = load_knowledge_config(tmp_path)
    assert config is not None
    assert len(config.sources) == 1
    assert config.sources[0].url == "https://new.git"
    assert config.sources[0].profiles == ["updated"]


def test_save_knowledge_source_path_type(tmp_path: Path) -> None:
    _create_project(tmp_path)
    source = KnowledgeSource(
        name="local-kb",
        source_type="path",
        url="../my-kb",
        kind="project",
    )
    save_knowledge_source(tmp_path, source)

    config = load_knowledge_config(tmp_path)
    assert config is not None
    assert config.sources[0].source_type == "path"
    assert config.sources[0].kind == "project"
    assert config.sources[0].url == "../my-kb"


def test_save_knowledge_source_preserves_schema_comment(tmp_path: Path) -> None:
    project_root = _create_project(
        tmp_path,
        "\n# human note\n[knowledge]\nenabled = true\n",
    )
    project_file = project_root / "runops.toml"
    project_file.write_text(
        "#:schema https://example.test/simproject.json\n"
        "[project]\n"
        'name = "test-project"\n'
        "# human note\n"
        "[knowledge]\n"
        "enabled = true\n",
        encoding="utf-8",
    )

    save_knowledge_source(
        project_root,
        KnowledgeSource(
            name="kb",
            source_type="path",
            url="../shared-kb",
            kind="profiles",
            mount="refs/knowledge/kb",
            profiles=["common"],
        ),
    )

    content = project_file.read_text(encoding="utf-8")
    assert "#:schema https://example.test/simproject.json" in content
    assert "# human note" in content
    assert 'name = "kb"' in content


# ---------- remove_knowledge_source ----------


def test_remove_knowledge_source_removes(tmp_path: Path) -> None:
    _create_project(tmp_path)
    source = KnowledgeSource(
        name="kb",
        source_type="git",
        url="https://x.git",
        kind="profiles",
        mount="refs/knowledge/kb",
    )
    save_knowledge_source(tmp_path, source)

    assert remove_knowledge_source(tmp_path, "kb") is True
    config = load_knowledge_config(tmp_path)
    assert config is not None
    assert len(config.sources) == 0


def test_remove_knowledge_source_not_found(tmp_path: Path) -> None:
    _create_project(tmp_path, "\n[knowledge]\nsources = []\n")
    assert remove_knowledge_source(tmp_path, "nonexistent") is False


def test_set_knowledge_source_profiles_updates_enabled_list(tmp_path: Path) -> None:
    project_root = _create_project(
        tmp_path,
        """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "kb"
type = "path"
kind = "profiles"
path = "../shared-kb"
mount = "refs/knowledge/kb"
profiles = ["common"]
""",
    )

    updated = set_knowledge_source_profiles(
        project_root,
        "kb",
        enable=["emses"],
        disable=["common"],
    )

    assert updated.profiles == ["emses"]
    config = load_knowledge_config(project_root)
    assert config is not None
    assert config.sources[0].profiles == ["emses"]


# ---------- sync_source ----------


def test_sync_source_path_exists(tmp_path: Path) -> None:
    kb_dir = _create_knowledge_source(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    source = KnowledgeSource(
        name="test-kb",
        source_type="path",
        url=str(kb_dir),
        kind="profiles",
        mount="refs/knowledge/test-kb",
    )
    status = sync_source(project, source)
    assert status in ("linked", "copied", "exists", "updated-copy")


def test_sync_source_path_copy_removes_deleted_files(tmp_path: Path) -> None:
    kb_dir = _create_knowledge_source(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    mount = project / "refs" / "knowledge" / "test-kb"
    mount.mkdir(parents=True)
    stale_file = mount / "stale.md"
    stale_file.write_text("old", encoding="utf-8")

    source = KnowledgeSource(
        name="test-kb",
        source_type="path",
        url=str(kb_dir),
        kind="profiles",
        mount="refs/knowledge/test-kb",
    )

    status = sync_source(project, source)

    assert status == "updated-copy"
    assert not stale_file.exists()
    assert (mount / "README.md").is_file()


def test_sync_source_path_not_found(tmp_path: Path) -> None:
    from runops.core.exceptions import KnowledgeSourceError

    project = tmp_path / "project"
    project.mkdir()

    source = KnowledgeSource(
        name="missing",
        source_type="path",
        url="/nonexistent/path",
        kind="project",
        mount="refs/knowledge/missing",
    )
    with pytest.raises(KnowledgeSourceError, match="not found"):
        sync_source(project, source)


def test_sync_source_rejects_mount_path_outside_project(tmp_path: Path) -> None:
    from runops.core.exceptions import KnowledgeSourceError

    kb_dir = _create_knowledge_source(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    source = KnowledgeSource(
        name="test-kb",
        source_type="path",
        url=str(kb_dir),
        kind="profiles",
        mount="../outside",
    )

    with pytest.raises(KnowledgeSourceError, match="escapes project root"):
        sync_source(project, source)


def test_sync_source_git_clone(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    source = KnowledgeSource(
        name="git-kb",
        source_type="git",
        url="https://github.com/lab/kb.git",
        kind="profiles",
        mount="refs/knowledge/git-kb",
    )

    with patch("runops.core.knowledge_source.sync.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        status = sync_source(project, source)

    assert status == "cloned"
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "git"
    assert call_args[1] == "clone"


def test_sync_source_git_pull(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    mount = project / "refs" / "knowledge" / "git-kb"
    mount.mkdir(parents=True)
    (mount / ".git").mkdir()  # fake git dir

    source = KnowledgeSource(
        name="git-kb",
        source_type="git",
        url="https://github.com/lab/kb.git",
        kind="profiles",
        mount="refs/knowledge/git-kb",
    )

    with patch("runops.core.knowledge_source.sync.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        status = sync_source(project, source)

    assert status == "updated"
    call_args = mock_run.call_args[0][0]
    assert "pull" in call_args


# ---------- validate_source_structure ----------


def test_validate_source_structure_valid(tmp_path: Path) -> None:
    kb_dir = _create_knowledge_source(tmp_path)
    issues = validate_source_structure(kb_dir)
    assert issues == []


def test_validate_source_structure_missing_profiles(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "README.md").write_text("# KB\n")

    issues = validate_source_structure(kb_dir)
    assert any("profiles/" in i for i in issues)


def test_validate_source_structure_missing_readme(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "profiles").mkdir()

    issues = validate_source_structure(kb_dir)
    assert any("README.md" in i for i in issues)


def test_validate_source_structure_checks_profile_imports(tmp_path: Path) -> None:
    kb_dir = _create_knowledge_source(tmp_path)
    (kb_dir / "profiles" / "common.md").write_text(
        "# Common\n@docs/missing.md\n",
        encoding="utf-8",
    )

    issues = validate_source_structure(kb_dir)
    assert any("missing import target" in issue for issue in issues)


def test_validate_source_structure_checks_entrypoints_manifest(tmp_path: Path) -> None:
    kb_dir = _create_knowledge_source(tmp_path)
    (kb_dir / "entrypoints.toml").write_text(
        'imports = ["docs/agent-guide.md"]\n'
        "[profiles.common]\n"
        'imports = ["analysis/recipes/common.toml"]\n',
        encoding="utf-8",
    )

    issues = validate_source_structure(kb_dir)
    assert any("missing import target" in issue for issue in issues)


def test_validate_source_structure_checks_analysis_schema_files(tmp_path: Path) -> None:
    kb_dir = _create_knowledge_source(tmp_path)
    observables_dir = kb_dir / "analysis" / "observables"
    recipes_dir = kb_dir / "analysis" / "recipes"
    observables_dir.mkdir(parents=True)
    recipes_dir.mkdir(parents=True)
    (observables_dir / "density.toml").write_text(
        '[observable]\nname = "density"\n',
        encoding="utf-8",
    )
    (recipes_dir / "summary.toml").write_text(
        '[recipe]\nname = "summary"\n',
        encoding="utf-8",
    )

    issues = validate_source_structure(kb_dir)
    assert any("observables schema" in issue for issue in issues)
    assert any("recipe schema" in issue for issue in issues)


def test_validate_source_structure_not_found(tmp_path: Path) -> None:
    issues = validate_source_structure(tmp_path / "nonexistent")
    assert len(issues) == 1
    assert "not found" in issues[0]


# ---------- discover_profiles ----------


def test_discover_profiles(tmp_path: Path) -> None:
    kb_dir = _create_knowledge_source(tmp_path)
    profiles = discover_profiles(kb_dir)
    assert profiles == ["advanced", "common"]


def test_discover_profiles_no_dir(tmp_path: Path) -> None:
    assert discover_profiles(tmp_path) == []


def test_sync_source_path_project_marks_source_available(tmp_path: Path) -> None:
    kb_dir = _create_knowledge_source(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    source = KnowledgeSource(
        name="upstream-project",
        source_type="path",
        kind="project",
        url=str(kb_dir),
    )

    status = sync_source(project, source)
    assert status == "available"


def test_collect_external_knowledge_includes_project_and_profile_sources(
    tmp_path: Path,
) -> None:
    kb_dir = _create_knowledge_source(tmp_path, "kb")
    other_project = tmp_path / "other-project"
    other_project.mkdir()
    (other_project / ".runops" / "insights").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(
        project,
        """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "kb"
type = "path"
kind = "profiles"
path = "../kb"
mount = "refs/knowledge/kb"
profiles = ["common"]

[[knowledge.sources]]
name = "other-project"
type = "path"
kind = "project"
path = "../other-project"
""",
    )

    mount_dir = project / "refs" / "knowledge" / "kb"
    mount_dir.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(kb_dir, mount_dir)

    entries = collect_external_knowledge(project)

    assert [entry.name for entry in entries] == ["kb", "other-project"]
    assert entries[0].kind == "profiles"
    assert entries[0].profiles_available == ["advanced", "common"]
    assert entries[1].kind == "project"
    assert entries[1].exists is True


# ---------- render_imports ----------


def test_render_imports_with_profiles(tmp_path: Path) -> None:
    kb_dir = _create_knowledge_source(tmp_path, "kb")
    project = tmp_path / "project"
    project.mkdir()

    # Mount the kb at the expected location
    mount_dir = project / "refs" / "knowledge" / "kb"
    mount_dir.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(kb_dir, mount_dir)

    config = KnowledgeConfig(
        sources=[
            KnowledgeSource(
                name="kb",
                source_type="path",
                url=str(kb_dir),
                mount="refs/knowledge/kb",
                profiles=["common"],
            ),
        ],
    )

    imports_path = render_imports(project, config)
    assert imports_path.is_file()
    content = imports_path.read_text()
    assert "@refs/knowledge/kb/profiles/common.md" in content
    assert "advanced" not in content


def test_render_imports_uses_entrypoints_manifest(tmp_path: Path) -> None:
    kb_dir = _create_knowledge_source(tmp_path, "kb")
    (kb_dir / "docs").mkdir()
    (kb_dir / "docs" / "agent-guide.md").write_text("# Agent\n", encoding="utf-8")
    (kb_dir / "entrypoints.toml").write_text(
        '[profiles.common]\nimports = ["profiles/common.md", "docs/agent-guide.md"]\n',
        encoding="utf-8",
    )

    project = tmp_path / "project"
    project.mkdir()
    mount_dir = project / "refs" / "knowledge" / "kb"
    mount_dir.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(kb_dir, mount_dir)

    config = KnowledgeConfig(
        sources=[
            KnowledgeSource(
                name="kb",
                source_type="path",
                url=str(kb_dir),
                mount="refs/knowledge/kb",
                profiles=["common"],
            ),
        ],
    )

    imports_path = render_imports(project, config)
    content = imports_path.read_text(encoding="utf-8")
    assert "@refs/knowledge/kb/profiles/common.md" in content
    assert "@refs/knowledge/kb/docs/agent-guide.md" in content


def test_render_imports_no_profiles_uses_claude_md(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    mount_dir = project / "refs" / "knowledge" / "kb"
    mount_dir.mkdir(parents=True)
    (mount_dir / "CLAUDE.md").write_text("# Knowledge\n")

    config = KnowledgeConfig(
        sources=[
            KnowledgeSource(
                name="kb",
                source_type="path",
                url=".",
                mount="refs/knowledge/kb",
                profiles=[],
            ),
        ],
    )

    imports_path = render_imports(project, config)
    content = imports_path.read_text()
    assert "@refs/knowledge/kb/CLAUDE.md" in content


def test_render_imports_missing_profile_adds_comment(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    mount_dir = project / "refs" / "knowledge" / "kb"
    mount_dir.mkdir(parents=True)
    (mount_dir / "profiles").mkdir()

    config = KnowledgeConfig(
        sources=[
            KnowledgeSource(
                name="kb",
                source_type="path",
                url=".",
                mount="refs/knowledge/kb",
                profiles=["nonexistent"],
            ),
        ],
    )

    imports_path = render_imports(project, config)
    content = imports_path.read_text()
    assert "<!-- profile nonexistent not found" in content


def test_import_external_insights_namespaces_by_source(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project)

    source_a = tmp_path / "alpha-project"
    source_b = tmp_path / "beta-project"
    for source_root in (source_a, source_b):
        insights_dir = source_root / ".runops" / "insights"
        insights_dir.mkdir(parents=True, exist_ok=True)
        (insights_dir / "stability.md").write_text(
            "---\n"
            "type: result\n"
            "simulator: emses\n"
            "created: 2026-04-02\n"
            "---\n\n"
            "Stable run.\n",
            encoding="utf-8",
        )

    imported, skipped = import_external_insights(
        project,
        [
            KnowledgeSource(
                name="alpha",
                source_type="path",
                kind="project",
                url=str(source_a),
            ),
            KnowledgeSource(
                name="beta",
                source_type="path",
                kind="project",
                url=str(source_b),
            ),
        ],
    )

    assert imported == 2
    assert skipped == 0
    assert (project / ".runops" / "insights" / "alpha__stability.md").is_file()
    assert (project / ".runops" / "insights" / "beta__stability.md").is_file()


def test_import_external_insights_skips_existing_namespaced_file(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project)
    source_root = tmp_path / "alpha-project"
    insights_dir = source_root / ".runops" / "insights"
    insights_dir.mkdir(parents=True, exist_ok=True)
    (insights_dir / "stability.md").write_text(
        "---\n"
        "type: result\n"
        "simulator: emses\n"
        "created: 2026-04-02\n"
        "---\n\n"
        "Stable run.\n",
        encoding="utf-8",
    )

    source = KnowledgeSource(
        name="alpha",
        source_type="path",
        kind="project",
        url=str(source_root),
    )
    first = import_external_insights(project, [source])
    second = import_external_insights(project, [source])

    assert first == (1, 0)
    assert second == (0, 1)


def test_import_external_facts_syncs_candidates_by_source(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project)
    source_root = tmp_path / "alpha-project"
    facts_dir = source_root / ".runops"
    facts_dir.mkdir(parents=True, exist_ok=True)
    (facts_dir / "facts.toml").write_text(
        "[[facts]]\n"
        'id = "f001"\n'
        'claim = "dt must stay below 1.0"\n'
        'fact_type = "constraint"\n'
        'simulator = "emses"\n'
        'confidence = "high"\n',
        encoding="utf-8",
    )

    synced_sources, total_facts = import_external_facts(
        project,
        [
            KnowledgeSource(
                name="alpha",
                source_type="path",
                kind="project",
                url=str(source_root),
            ),
        ],
    )

    assert synced_sources == 1
    assert total_facts == 1
    facts = load_candidate_facts(project)
    assert len(facts) == 1
    assert facts[0].id == "alpha:f001"
    assert facts[0].storage == "candidate"
    assert facts[0].transport_source == "alpha"
    assert facts[0].upstream_id == "f001"


def test_discover_repo_imports_reads_entrypoints_manifest(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "entrypoints.toml").write_text(
        'imports = ["docs/agent-user-guide.md"]\n',
        encoding="utf-8",
    )

    assert discover_repo_imports(repo_root) == ["docs/agent-user-guide.md"]
