"""Direct tests for knowledge source validation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from runops.core.knowledge_source_validation import (
    _validate_analysis_file,
    _validate_import_paths,
    validate_source_structure,
)

if TYPE_CHECKING:
    import pytest


def _create_knowledge_source(tmp_path: Path, name: str = "kb") -> Path:
    source = tmp_path / name
    source.mkdir()
    (source / "README.md").write_text("# KB\n", encoding="utf-8")
    profiles_dir = source / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "common.md").write_text("# Common\n", encoding="utf-8")
    return source


def test_validate_import_paths_reports_escape_and_directory_targets(
    tmp_path: Path,
) -> None:
    source = _create_knowledge_source(tmp_path)
    (source / "docs").mkdir()

    issues = _validate_import_paths(
        source,
        ["../outside.md", "docs"],
        context="profiles/common.md",
    )

    assert any("escapes source root" in issue for issue in issues)
    assert any("import target is not a file" in issue for issue in issues)


def test_validate_analysis_file_reports_parse_and_read_errors(tmp_path: Path) -> None:
    source = _create_knowledge_source(tmp_path)
    observables_dir = source / "analysis" / "observables"
    observables_dir.mkdir(parents=True)

    invalid = observables_dir / "invalid.toml"
    invalid.write_text("[observable\n", encoding="utf-8")
    missing = observables_dir / "missing.toml"

    parse_issues = _validate_analysis_file(
        invalid,
        source_path=source,
        kind="observables",
    )
    read_issues = _validate_analysis_file(
        missing,
        source_path=source,
        kind="observables",
    )

    assert any("schema parse failed" in issue for issue in parse_issues)
    assert any("schema not readable" in issue for issue in read_issues)


def test_validate_analysis_file_checks_observables_tables(tmp_path: Path) -> None:
    source = _create_knowledge_source(tmp_path)
    observables_dir = source / "analysis" / "observables"
    observables_dir.mkdir(parents=True)

    observables = observables_dir / "density.toml"
    observables.write_text(
        "[observables.good]\n"
        'source = "work/density.dat"\n'
        "[observables.bad]\n"
        'label = "missing keys"\n'
        "[observables.scalar]\n"
        "value = 1\n",
        encoding="utf-8",
    )

    issues = _validate_analysis_file(
        observables,
        source_path=source,
        kind="observables",
    )

    assert any(
        "observables.bad missing source/path/metric" in issue for issue in issues
    )


def test_validate_analysis_file_checks_recipe_tables(tmp_path: Path) -> None:
    source = _create_knowledge_source(tmp_path)
    recipes_dir = source / "analysis" / "recipes"
    recipes_dir.mkdir(parents=True)

    recipes = recipes_dir / "plots.toml"
    recipes.write_text(
        '[recipes.good]\nplot = "line"\n[recipes.bad]\ntitle = "missing keys"\n',
        encoding="utf-8",
    )

    issues = _validate_analysis_file(
        recipes,
        source_path=source,
        kind="recipes",
    )

    assert any(
        "recipes.bad missing recipe definition keys" in issue for issue in issues
    )


def test_validate_source_structure_reports_empty_and_unreadable_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _create_knowledge_source(tmp_path)
    (source / "profiles" / "empty.md").write_text("", encoding="utf-8")
    (source / "profiles" / "broken.md").write_text("# Broken\n", encoding="utf-8")
    (source / "agent-empty.md").write_text("", encoding="utf-8")
    (source / "agent-broken.md").write_text("# Broken agent\n", encoding="utf-8")

    original_read_text = Path.read_text

    def fake_read_text(
        self: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if self.name in {"broken.md", "agent-broken.md"}:
            raise OSError("boom")
        return original_read_text(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    issues = validate_source_structure(source)

    assert any("Profile is empty" in issue for issue in issues)
    assert any("Profile not readable" in issue for issue in issues)
    assert any("Agent doc is empty" in issue for issue in issues)
    assert any("Agent doc not readable" in issue for issue in issues)


def test_validate_source_structure_reports_entrypoint_issues(tmp_path: Path) -> None:
    source = _create_knowledge_source(tmp_path)
    (source / "entrypoints.toml").write_text(
        '[profiles.missing]\nimports = ["profiles/common.md"]\n',
        encoding="utf-8",
    )

    issues = validate_source_structure(source)

    assert any("has no matching profiles/<name>.md" in issue for issue in issues)
