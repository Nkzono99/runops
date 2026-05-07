"""Bundled skill rendering helpers for generated agent harnesses."""

from __future__ import annotations

from pathlib import Path

from runops.harness._adapters import collect_pip_packages

_SKILL_RESOURCE_SKIP_NAMES = {"README.md", "manifest.txt"}


def render_skill_files(
    project_name: str,
    simulator_names: list[str],
    *,
    skill_prefix: str,
    agent_name: str,
    skills_dir: str,
) -> dict[str, str]:
    """Return ``{"<skill-name>/<path>": content}`` for bundled skills.

    Claude Code invokes project skills as slash commands (``/note``), while
    Codex mentions them with ``$`` (``$note``).  The shared SKILL.md templates
    may use ``skill_prefix`` so each harness gets native instructions.

    Skill support resources (``scripts/``, ``references/``, ``examples/``) are
    copied alongside ``SKILL.md`` so generated projects can run helper tools
    from the same skill directory.
    """
    pip_pkgs = collect_pip_packages(simulator_names) if simulator_names else []
    if pip_pkgs:
        pip_install_line = f"uv pip install {' '.join(pip_pkgs)}"
    else:
        pip_install_line = "# uv pip install <必要なパッケージ>"

    skills_template_dir = (
        Path(__file__).resolve().parent.parent / "templates" / "skills"
    )
    results: dict[str, str] = {}
    for skill_path in sorted(skills_template_dir.iterdir()):
        if not skill_path.is_dir():
            continue
        skill_md = skill_path / "SKILL.md"
        if not skill_md.exists():
            continue
        for resource_path in sorted(skill_path.rglob("*")):
            if not resource_path.is_file():
                continue
            if resource_path.name in _SKILL_RESOURCE_SKIP_NAMES:
                continue

            rel_path = resource_path.relative_to(skill_path).as_posix()
            content = resource_path.read_text(encoding="utf-8")
            if rel_path == "SKILL.md" and "{{" in content:
                from runops.templates import get_jinja_env

                env = get_jinja_env()
                template = env.from_string(content)
                content = template.render(
                    agent_name=agent_name,
                    project_name=project_name,
                    pip_install_line=pip_install_line,
                    skill_prefix=skill_prefix,
                    skills_dir=skills_dir,
                )
            results[f"{skill_path.name}/{rel_path}"] = content
    return results
