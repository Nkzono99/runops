"""Harness file generation shared by ``runops init`` and ``runops update-harness``.

The builder renders every harness-managed file (``CLAUDE.md``, ``AGENTS.md``,
``.claude/skills/*``, ``.claude/rules/*``, ``.claude/settings.json``,
``.vscode/settings.json``, ``.codex/*``, ``.agents/skills/*``,
``cases/CLAUDE.md``, ``cases/AGENTS.md``, ``runs/CLAUDE.md``,
``runs/AGENTS.md``) into an in-memory mapping of
``relative_path -> rendered_content``. The scaffolded ``.gitignore`` is also
harness-managed, but through a dedicated block-based workflow so user-owned
ignore rules can live outside the managed section.

``runops init`` iterates the mapping and writes each file (``_write_if_missing``),
then persists template hashes to ``.runops/harness.lock``.  ``runops update-harness``
re-renders the same mapping, compares the current on-disk hash against the lock
to detect user edits, and then overwrites / emits ``.new`` files accordingly.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

HARNESS_LOCK_PATH = ".runops/harness.lock"

# File paths that `build_harness_bundle` may emit, as project-relative strings.
CLAUDE_MD = "CLAUDE.md"
AGENTS_MD = "AGENTS.md"
CLAUDE_SETTINGS = ".claude/settings.json"
VSCODE_SETTINGS = ".vscode/settings.json"
CASES_CLAUDE_MD = "cases/CLAUDE.md"
RUNS_CLAUDE_MD = "runs/CLAUDE.md"
CASES_AGENTS_MD = "cases/AGENTS.md"
RUNS_AGENTS_MD = "runs/AGENTS.md"
RULE_WORKFLOW = ".claude/rules/runops-workflow.md"
RULE_PLAN_BEFORE_ACT = ".claude/rules/plan-before-act.md"
RULE_COOKBOOK = ".claude/rules/cookbook.md"
RULE_UPSTREAM_FEEDBACK = ".claude/rules/upstream-feedback.md"
GITIGNORE_PATH = ".gitignore"

# Codex-side outputs (see runops.harness.codex for rationale).
CODEX_CONFIG = ".codex/config.toml"
CODEX_README = ".codex/README.md"
CODEX_RULES = ".codex/rules/runops.rules"
AGENTS_SKILLS_PREFIX = ".agents/skills/"
GITIGNORE_MANAGED_START = "# >>> runops managed (auto-updated by runo update-harness)"
GITIGNORE_MANAGED_END = "# <<< runops managed"

_CLAUDE_MD_TEMPLATE = "harness/claude/CLAUDE.md.j2"
_AGENTS_MD_TEMPLATE = "harness/codex/AGENTS.md.j2"
_CASES_DOC_TEMPLATE = "harness/shared/cases.md"
_RUNS_DOC_TEMPLATE = "harness/shared/runs.md"
_RULE_WORKFLOW_TEMPLATE = "harness/claude/rules/runops-workflow.md"
_RULE_PLAN_BEFORE_ACT_TEMPLATE = "harness/claude/rules/plan-before-act.md"
_RULE_COOKBOOK_TEMPLATE = "harness/claude/rules/cookbook.md.j2"
_RULE_UPSTREAM_FEEDBACK_TEMPLATE = "harness/claude/rules/upstream-feedback.md.j2"
_VSCODE_SETTINGS_TEMPLATE = "scaffold/vscode_settings.json"
_GITIGNORE_TEMPLATE = "scaffold/gitignore.txt"

# Files that update-harness is allowed to touch.  Any other file under the
# project root (campaign.toml, cases/**, runs/**, etc.) is user-owned and
# must never be rewritten by update-harness.
_ALL_HARNESS_PREFIXES: tuple[str, ...] = (
    CLAUDE_MD,
    AGENTS_MD,
    CLAUDE_SETTINGS,
    VSCODE_SETTINGS,
    GITIGNORE_PATH,
    CASES_CLAUDE_MD,
    RUNS_CLAUDE_MD,
    CASES_AGENTS_MD,
    RUNS_AGENTS_MD,
    ".claude/skills/",
    ".claude/rules/",
    ".codex/",
    AGENTS_SKILLS_PREFIX,
)


def is_harness_path(rel_path: str) -> bool:
    """Return True if ``rel_path`` is owned by the harness builder."""
    normalized = rel_path.replace("\\", "/")
    return any(
        normalized == prefix or normalized.startswith(prefix)
        for prefix in _ALL_HARNESS_PREFIXES
    )


@dataclass(frozen=True)
class HarnessBundle:
    """Rendered harness file contents keyed by project-relative path."""

    files: dict[str, str] = field(default_factory=dict)
    upstream_feedback: bool = True

    def hashes(self) -> dict[str, str]:
        """Return ``{relative_path: sha256}`` for every file in the bundle."""
        return {rel: hash_text(content) for rel, content in self.files.items()}


def hash_text(text: str) -> str:
    """Return hex sha256 of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str | None:
    """Return hex sha256 of the file at ``path``, or ``None`` if unreadable."""
    try:
        return hash_text(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return None


def build_managed_gitignore_block() -> str:
    """Return the runops-managed ``.gitignore`` block."""
    from runops.templates import load_static

    block = load_static(_GITIGNORE_TEMPLATE).rstrip("\n")
    return f"{GITIGNORE_MANAGED_START}\n{block}\n{GITIGNORE_MANAGED_END}\n"


def build_gitignore_file(existing_text: str = "") -> str:
    """Return a ``.gitignore`` that appends the managed block to existing text."""
    managed_block = build_managed_gitignore_block()
    prefix = existing_text.rstrip("\n")
    if not prefix:
        return managed_block
    return f"{prefix}\n\n{managed_block}"


def extract_managed_gitignore_block(text: str) -> str | None:
    """Return the managed ``.gitignore`` block when exactly one valid block exists."""
    lines = text.splitlines(keepends=True)
    start_indexes = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\n") == GITIGNORE_MANAGED_START
    ]
    end_indexes = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\n") == GITIGNORE_MANAGED_END
    ]
    if len(start_indexes) != 1 or len(end_indexes) != 1:
        return None

    start = start_indexes[0]
    end = end_indexes[0]
    if start >= end:
        return None
    return "".join(lines[start : end + 1])


def hash_managed_gitignore_block(text: str) -> str | None:
    """Return the managed-block hash from ``.gitignore``, if present."""
    block = extract_managed_gitignore_block(text)
    if block is None:
        return None
    return hash_text(block)


def replace_managed_gitignore_block(text: str) -> str | None:
    """Replace the existing managed ``.gitignore`` block in ``text``."""
    lines = text.splitlines(keepends=True)
    start_indexes = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\n") == GITIGNORE_MANAGED_START
    ]
    end_indexes = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\n") == GITIGNORE_MANAGED_END
    ]
    if len(start_indexes) != 1 or len(end_indexes) != 1:
        return None

    start = start_indexes[0]
    end = end_indexes[0]
    if start >= end:
        return None

    updated = "".join(
        [
            *lines[:start],
            build_managed_gitignore_block(),
            *lines[end + 1 :],
        ]
    )
    if updated and not updated.endswith("\n"):
        updated += "\n"
    return updated


# ---------------------------------------------------------------------------
# Adapter lookups (private to harness builder; duplicated here to avoid a
# circular import with runops.cli.init which also depends on this module).
# ---------------------------------------------------------------------------


def _collect_doc_repos(simulator_names: list[str]) -> list[tuple[str, str]]:
    """Return unique ``(url, dest)`` pairs from the given adapters."""
    import runops.adapters  # noqa: F401
    from runops.adapters.registry import get_global_registry

    registry = get_global_registry()
    seen: set[str] = set()
    repos: list[tuple[str, str]] = []
    for sim_name in simulator_names:
        try:
            adapter_cls = registry.get(sim_name)
        except KeyError:
            continue
        for url, dest in adapter_cls.doc_repos():
            if dest in seen:
                continue
            seen.add(dest)
            repos.append((url, dest))
    return repos


def _collect_pip_packages(simulator_names: list[str]) -> list[str]:
    """Return unique pip packages declared by the given adapters."""
    import runops.adapters  # noqa: F401
    from runops.adapters.registry import get_global_registry

    registry = get_global_registry()
    seen: set[str] = set()
    packages: list[str] = []
    for sim_name in simulator_names:
        try:
            adapter_cls = registry.get(sim_name)
        except KeyError:
            continue
        for pkg in adapter_cls.pip_packages():
            if pkg in seen:
                continue
            seen.add(pkg)
            packages.append(pkg)
    return packages


# ---------------------------------------------------------------------------
# Individual file renderers
# ---------------------------------------------------------------------------


def _render_agent_md(
    template_path: str,
    doc_name: str,
    project_name: str,
    doc_repos: list[tuple[str, str]],
    *,
    knowledge_imports_path: str,
    supports_import: bool,
    skills_dir: str,
    include_cookbook_rule: bool,
    include_upstream_feedback: bool,
) -> str:
    """Render a CLAUDE.md / AGENTS.md Jinja template.

    ``supports_import`` controls whether the rendered file may use the
    ``@file`` import syntax.  Claude Code supports it; the Codex CLI
    does not, so AGENTS.md falls back to plain path references.

    ``skills_dir`` is the directory (``.claude/skills`` or
    ``.agents/skills``) mentioned in the "information priority" section.
    """
    from runops.templates import get_jinja_env

    env = get_jinja_env()
    template = env.get_template(template_path)
    return template.render(
        doc_name=doc_name,
        project_name=project_name,
        doc_repos=doc_repos,
        include_cookbook_rule=include_cookbook_rule,
        include_upstream_feedback=include_upstream_feedback,
        knowledge_imports_path=knowledge_imports_path,
        supports_import=supports_import,
        skills_dir=skills_dir,
        agent_name="Claude Code" if supports_import else "Codex",
        skill_prefix="/" if supports_import else "$",
    )


def _render_skill_files(
    project_name: str,
    simulator_names: list[str],
    *,
    skill_prefix: str,
    agent_name: str,
) -> dict[str, str]:
    """Return ``{"<skill-name>/SKILL.md": content}`` for bundled skills.

    Claude Code invokes project skills as slash commands (``/note``), while
    Codex mentions them with ``$`` (``$note``).  The shared SKILL.md templates
    may use ``skill_prefix`` so each harness gets native instructions.
    """
    pip_pkgs = _collect_pip_packages(simulator_names) if simulator_names else []
    if pip_pkgs:
        pip_install_line = f"uv pip install {' '.join(pip_pkgs)}"
    else:
        pip_install_line = "# uv pip install <必要なパッケージ>"

    skills_dir = Path(__file__).resolve().parent.parent / "templates" / "skills"
    results: dict[str, str] = {}
    for skill_path in sorted(skills_dir.iterdir()):
        if not skill_path.is_dir():
            continue
        skill_md = skill_path / "SKILL.md"
        if not skill_md.exists():
            continue
        content = skill_md.read_text(encoding="utf-8")
        if "{{" in content:
            from runops.templates import get_jinja_env

            env = get_jinja_env()
            template = env.from_string(content)
            content = template.render(
                agent_name=agent_name,
                project_name=project_name,
                pip_install_line=pip_install_line,
                skill_prefix=skill_prefix,
            )
        results[f"{skill_path.name}/SKILL.md"] = content
    return results


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def build_harness_bundle(
    project_name: str,
    simulator_names: list[str],
    *,
    upstream_feedback: bool = True,
    knowledge_imports_path: str = "",
) -> HarnessBundle:
    """Render every harness file into an in-memory bundle.

    Args:
        project_name: Project name used in CLAUDE.md / AGENTS.md headers.
        simulator_names: Simulator adapter names (e.g. ``["emses", "beach"]``).
        upstream_feedback: Include the ``.claude/rules/upstream-feedback.md``
            rule.  ``runops init --no-upstream-feedback`` sets this to False.
        knowledge_imports_path: Relative path to the rendered imports file,
            or empty string if knowledge imports are not configured.

    Returns:
        Bundle keyed by project-relative path; consumers iterate it to write
        files or to compute template hashes for ``.runops/harness.lock``.
    """
    from runops.harness import build_claude_settings
    from runops.harness.codex import (
        build_codex_config,
        build_codex_readme,
        build_codex_rules,
    )
    from runops.templates import load_static, render

    files: dict[str, str] = {}
    doc_repos = _collect_doc_repos(simulator_names) if simulator_names else []
    include_cookbook_rule = bool(simulator_names and doc_repos)

    files[CLAUDE_MD] = _render_agent_md(
        _CLAUDE_MD_TEMPLATE,
        CLAUDE_MD,
        project_name,
        doc_repos,
        knowledge_imports_path=knowledge_imports_path,
        supports_import=True,
        skills_dir=".claude/skills/",
        include_cookbook_rule=include_cookbook_rule,
        include_upstream_feedback=upstream_feedback,
    )
    files[AGENTS_MD] = _render_agent_md(
        _AGENTS_MD_TEMPLATE,
        AGENTS_MD,
        project_name,
        doc_repos,
        knowledge_imports_path=knowledge_imports_path,
        supports_import=False,
        skills_dir=AGENTS_SKILLS_PREFIX,
        include_cookbook_rule=include_cookbook_rule,
        include_upstream_feedback=upstream_feedback,
    )

    files[CLAUDE_SETTINGS] = build_claude_settings()
    files[VSCODE_SETTINGS] = load_static(_VSCODE_SETTINGS_TEMPLATE)

    rendered_claude_skills = _render_skill_files(
        project_name,
        simulator_names,
        skill_prefix="/",
        agent_name="Claude Code",
    )
    for rel_path, content in rendered_claude_skills.items():
        files[f".claude/skills/{rel_path}"] = content

    files[RULE_WORKFLOW] = load_static(_RULE_WORKFLOW_TEMPLATE)
    files[RULE_PLAN_BEFORE_ACT] = load_static(_RULE_PLAN_BEFORE_ACT_TEMPLATE)
    if include_cookbook_rule:
        files[RULE_COOKBOOK] = render(_RULE_COOKBOOK_TEMPLATE)
    if upstream_feedback:
        files[RULE_UPSTREAM_FEEDBACK] = render(_RULE_UPSTREAM_FEEDBACK_TEMPLATE)

    files[CASES_CLAUDE_MD] = load_static(_CASES_DOC_TEMPLATE)
    files[RUNS_CLAUDE_MD] = load_static(_RUNS_DOC_TEMPLATE)
    files[CASES_AGENTS_MD] = load_static(_CASES_DOC_TEMPLATE)
    files[RUNS_AGENTS_MD] = load_static(_RUNS_DOC_TEMPLATE)

    # Codex harness.  Codex auto-loads .codex/config.toml (with trust),
    # .codex/rules/*.rules, .agents/skills/<name>/SKILL.md, and AGENTS.md
    # files from the project root down to the current working directory.
    # Project-local slash-command prompts have no Codex equivalent, so we
    # do not emit them.
    files[CODEX_CONFIG] = build_codex_config(project_name)
    files[CODEX_README] = build_codex_readme(project_name)
    files[CODEX_RULES] = build_codex_rules()
    # SKILL.md frontmatter is shared, but invocation syntax differs:
    # Claude uses `/skill`; Codex uses `$skill`.
    rendered_codex_skills = _render_skill_files(
        project_name,
        simulator_names,
        skill_prefix="$",
        agent_name="Codex",
    )
    for rel_path, content in rendered_codex_skills.items():
        files[f"{AGENTS_SKILLS_PREFIX}{rel_path}"] = content

    return HarnessBundle(files=files, upstream_feedback=upstream_feedback)


# ---------------------------------------------------------------------------
# harness.lock persistence
# ---------------------------------------------------------------------------


def load_harness_lock(project_dir: Path) -> dict[str, str]:
    """Load the ``harness.lock`` mapping ``relative_path -> template sha256``.

    Returns an empty dict when the lock file is missing, malformed, or when
    the project predates this feature.
    """
    lock_path = project_dir / HARNESS_LOCK_PATH
    if not lock_path.is_file():
        return {}
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    hashes = raw.get("hashes")
    if not isinstance(hashes, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in hashes.items()
        if isinstance(k, str) and isinstance(v, str)
    }


def save_harness_lock(project_dir: Path, hashes: dict[str, str]) -> None:
    """Write the harness lock with sorted entries for stable diffs."""
    lock_path = project_dir / HARNESS_LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": 1,
        "hashes": dict(sorted(hashes.items())),
    }
    lock_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# runops.toml [harness] helpers
# ---------------------------------------------------------------------------


def read_upstream_feedback_setting(project_dir: Path) -> bool:
    """Return ``[harness].upstream_feedback`` from runops.toml.

    Defaults to True when the key, table, or file is absent so that projects
    predating this feature get upstream-feedback guidance by default once they
    run ``runops update-harness``.
    """
    project_file = project_dir / "runops.toml"
    if not project_file.is_file():
        return True
    try:
        with open(project_file, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return True
    harness = data.get("harness")
    if not isinstance(harness, dict):
        return True
    value = harness.get("upstream_feedback", True)
    return bool(value)
