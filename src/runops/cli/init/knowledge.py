"""Knowledge bootstrap helpers for ``runo init`` and ``runo setup``."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import typer

from runops.harness._adapters import collect_doc_repos as _collect_doc_repos

logger = logging.getLogger(__name__)

_RUNOPS_AGENT_GUIDE_TEMPLATE = "knowledge/runops/agent-user-guide.md"
_RUNOPS_AGENT_GUIDE_PATH = ".runops/knowledge/runops/agent-user-guide.md"


def _clone_doc_repos(
    project_dir: Path,
    simulator_names: list[str],
) -> tuple[list[str], list[str]]:
    """Clone documentation repos into project_dir/refs/."""
    repos = _collect_doc_repos(simulator_names)
    if not repos:
        return [], []

    created: list[str] = []
    skipped: list[str] = []
    refs_dir = project_dir / "refs"
    refs_dir.mkdir(exist_ok=True)

    for url, dest in repos:
        dest_path = refs_dir / dest
        rel = f"refs/{dest}"
        if dest_path.exists():
            skipped.append(rel)
            continue
        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode == 0:
            created.append(rel)
        else:
            logger.warning(
                "git clone %s failed: %s", url, (result.stderr or "").strip()
            )

    return created, skipped


def _discover_agent_docs(
    project_dir: Path,
    doc_repos: list[tuple[str, str]],
) -> list[str]:
    """Discover manifest-declared agent doc imports from cloned doc repos."""
    from runops.core.knowledge_source import discover_repo_imports

    refs_dir = project_dir / "refs"
    paths: list[str] = []
    for _url, dest in doc_repos:
        repo_root = refs_dir / dest
        if not repo_root.is_dir():
            continue
        for rel_path in discover_repo_imports(repo_root):
            paths.append(f"refs/{dest}/{rel_path}".replace("\\", "/"))
    return paths


def _materialize_runops_agent_docs(project_dir: Path) -> list[str]:
    """Write package-provided runops agent docs into generated knowledge."""
    from runops.templates import load_static

    guide_path = project_dir / _RUNOPS_AGENT_GUIDE_PATH
    guide_path.parent.mkdir(parents=True, exist_ok=True)
    guide_path.write_text(
        load_static(_RUNOPS_AGENT_GUIDE_TEMPLATE),
        encoding="utf-8",
    )
    return [_RUNOPS_AGENT_GUIDE_PATH]


def _prepare_knowledge_imports(
    project_dir: Path,
    simulator_names: list[str],
    *,
    sync_sources: bool = False,
    validate_sources: bool = False,
) -> str:
    """Sync knowledge sources and render the unified imports.md bundle."""
    from runops.core.knowledge_source import (
        KnowledgeConfig,
        load_knowledge_config,
        render_imports,
        sync_all_sources,
        validate_source_structure,
    )

    knowledge_imports_path = ""
    config = load_knowledge_config(project_dir)

    if sync_sources and config is not None and config.sources:
        typer.echo("Syncing knowledge sources...")
        for name, status in sync_all_sources(project_dir, config):
            typer.echo(f"  {name}: {status}")

        if validate_sources:
            for source in config.sources:
                if not source.mount:
                    continue
                source_path = project_dir / source.mount
                if not source_path.is_dir():
                    continue
                issues = validate_source_structure(source_path)
                for issue in issues:
                    typer.echo(f"  Warning ({source.name}): {issue}")

    runops_doc_imports = _materialize_runops_agent_docs(project_dir)
    doc_repos = _collect_doc_repos(simulator_names) if simulator_names else []
    agent_doc_imports = [
        *runops_doc_imports,
        *_discover_agent_docs(project_dir, doc_repos),
    ]

    render_config = config if config is not None else KnowledgeConfig()
    should_render = bool(agent_doc_imports or (config is not None and config.sources))
    if should_render:
        render_imports(
            project_dir,
            render_config,
            extra_imports=agent_doc_imports or None,
        )
        typer.echo("  Rendered knowledge imports")

    if render_config.generate_claude_imports:
        imports_file = (
            project_dir / render_config.derived_dir / "enabled" / "imports.md"
        )
        if imports_file.is_file():
            knowledge_imports_path = f"{render_config.derived_dir}/enabled/imports.md"

    return knowledge_imports_path
