"""Project initialization workflow."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from runops import __version__
from runops.cli.init import command as _command_facade
from runops.cli.init.knowledge import _prepare_knowledge_imports
from runops.cli.init.prompting import _BundledSiteProfile
from runops.cli.init.scaffold import (
    _create_materials_skeleton,
    _create_notes_skeleton,
    _create_research_skeleton,
    _create_runops_skeleton,
    _mkdir_if_missing,
    _write_if_missing,
)
from runops.cli.init.serialization import (
    _build_campaign_toml,
    _build_launchers_toml,
    _build_simulators_toml,
    _build_simulators_toml_from_configs,
)
from runops.harness._plugins import (
    collect_plugin_recommendations,
    echo_plugin_recommendations,
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]

_SIMPROJECT_FILE = "runops.toml"
_SIMULATORS_FILE = "simulators.toml"
_LAUNCHERS_FILE = "launchers.toml"
_CAMPAIGN_FILE = "campaign.toml"
_CLAUDE_MD = "CLAUDE.md"
_AGENTS_MD = "AGENTS.md"
_SKILLS_DIR = ".claude/skills"
_RULES_DIR = ".claude/rules"
_CLAUDE_SETTINGS = ".claude/settings.json"
_SCHEMA_BASE_URL = "https://raw.githubusercontent.com/Nkzono99/runops/main/schemas"
_DEFAULT_RUNOPS_PACKAGE = f"runops=={__version__}"


def _safe_echo(message: str, *, err: bool = False) -> None:
    """Echo text even when the console encoding cannot represent it."""
    try:
        typer.echo(message, err=err)
    except UnicodeEncodeError:
        stream = sys.stderr if err else sys.stdout
        encoding = getattr(stream, "encoding", None) or "utf-8"
        safe_message = message.encode(encoding, errors="replace").decode(
            encoding,
            errors="replace",
        )
        typer.echo(safe_message, err=err)


def init(
    simulators: Annotated[
        Optional[list[str]],
        typer.Argument(help="Simulator names to configure (e.g. emses beach)."),
    ] = None,
    path: Annotated[
        Optional[Path],
        typer.Option("--path", "-p", help="Directory to initialize (defaults to cwd)."),
    ] = None,
    name: Annotated[
        Optional[str],
        typer.Option("--name", "-n", help="Project name (defaults to directory name)."),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip interactive prompts, use defaults."),
    ] = False,
    no_upstream_feedback: Annotated[
        bool,
        typer.Option(
            "--no-upstream-feedback",
            help="Do not include the upstream-feedback rule for the AI agent.",
        ),
    ] = False,
    no_harnessops: Annotated[
        bool,
        typer.Option(
            "--no-harnessops",
            help="Do not initialize the project-side HarnessOps overlay.",
        ),
    ] = False,
    gh_auth_login: Annotated[
        bool,
        typer.Option(
            "--gh-auth-login",
            help=(
                "Run `gh auth login` when simulator packages or --with-refs "
                "need GitHub authentication."
            ),
        ),
    ] = False,
    skip_github_auth_check: Annotated[
        bool,
        typer.Option(
            "--skip-github-auth-check",
            help=(
                "Skip GitHub authentication preflight for simulator packages "
                "and --with-refs."
            ),
        ),
    ] = False,
    with_refs: Annotated[
        bool,
        typer.Option(
            "--with-refs",
            help=(
                "Clone adapter-declared simulator doc repositories into refs/. "
                "By default, simulator knowledge is expected from plugins or "
                "explicit knowledge sources."
            ),
        ),
    ] = False,
    runops_package: Annotated[
        str,
        typer.Option(
            "--runops-package",
            help=(
                "Package spec used with --install-runops-into-venv for "
                "offline or pinned local CLI workflows."
            ),
        ),
    ] = _DEFAULT_RUNOPS_PACKAGE,
    install_runops_into_venv: Annotated[
        bool,
        typer.Option(
            "--install-runops-into-venv",
            help=(
                "Also install runops into the project .venv. By default, "
                "use `uvx --from runops runo ...` and keep .venv for runtime."
            ),
        ),
    ] = False,
) -> None:
    """Initialize a new runops project (runops.toml etc.).

    When the external ``hops`` CLI is available, ``runo init`` also delegates
    project-side HarnessOps overlay creation to ``hops init --profile
    runops-project``. Use ``--no-harnessops`` to skip that hook.

    By default, runs in interactive mode with guided prompts.
    Use --yes / -y to skip prompts and use defaults.

    Simulator names can also be passed directly:
      runo init emses beach

    Bootstrap usage (no prior install needed):
      uvx --from runops runo init
    """
    interactive = not yes
    project_dir = (path or Path.cwd()).resolve()

    # Interactive project name
    if interactive and not name:
        project_name = typer.prompt("Project name", default=project_dir.name)
    else:
        project_name = name or project_dir.name

    upstream_feedback = not no_upstream_feedback

    # Resolve interactive choices before writing files so failed preflights do
    # not leave a half-created project behind.
    sim_configs: dict[str, dict[str, Any]] = {}
    sim_names: list[str] = []

    if simulators:
        sim_names = simulators
        sim_content = _build_simulators_toml(simulators)
    elif interactive:
        import runops.cli.init as init_facade

        sim_names, sim_configs = init_facade._prompt_simulators()
        if sim_configs:
            sim_content = _build_simulators_toml_from_configs(sim_configs)
        else:
            sim_content = "[simulators]\n"
    else:
        sim_content = "[simulators]\n"

    site_profile: _BundledSiteProfile | None = None
    if interactive:
        import runops.cli.init as init_facade

        launcher_configs, site_profile = init_facade._prompt_launchers()
        launcher_content = _build_launchers_toml(launcher_configs)
    else:
        launcher_configs = {
            "srun": {"type": "srun", "use_slurm_ntasks": True},
        }
        launcher_content = _build_launchers_toml(launcher_configs)

    _command_facade.ensure_github_auth_for_simulators(
        sim_names,
        interactive=interactive,
        login=gh_auth_login,
        skip=skip_github_auth_check,
        include_refs=with_refs,
    )
    codex_plugin_recommendations = collect_plugin_recommendations(
        sim_names,
        simulator_configs=sim_configs or None,
        extra_plugins=site_profile.codex_plugins if site_profile else None,
    )

    if not project_dir.exists():
        project_dir.mkdir(parents=True)

    created: list[str] = []
    skipped: list[str] = []

    # runops.toml
    harness_line = (
        f"\n[harness]\nupstream_feedback = {'true' if upstream_feedback else 'false'}\n"
    )
    simproject_content = (
        f"#:schema {_SCHEMA_BASE_URL}/runops.json\n"
        f'[project]\nname = "{project_name}"\ndescription = ""\n' + harness_line
    )
    if _write_if_missing(project_dir / _SIMPROJECT_FILE, simproject_content):
        created.append(_SIMPROJECT_FILE)
    else:
        skipped.append(_SIMPROJECT_FILE)

    # simulators.toml
    sim_schema = f"#:schema {_SCHEMA_BASE_URL}/simulators.json\n"
    sim_content = sim_schema + sim_content
    if _write_if_missing(project_dir / _SIMULATORS_FILE, sim_content):
        created.append(_SIMULATORS_FILE)
    else:
        skipped.append(_SIMULATORS_FILE)

    # launchers.toml

    launcher_schema = f"#:schema {_SCHEMA_BASE_URL}/launchers.json\n"
    launcher_content = launcher_schema + launcher_content
    if _write_if_missing(project_dir / _LAUNCHERS_FILE, launcher_content):
        created.append(_LAUNCHERS_FILE)
    else:
        skipped.append(_LAUNCHERS_FILE)

    # site.toml — copy from bundled site profile
    if site_profile:
        from runops.core.site.profile import _load_site_toml

        site_file = project_dir / "site.toml"
        if not site_file.exists():
            # Read bundled file, write only the [site] sections (strip [launcher])
            with open(site_profile.source_path, "rb") as f:
                bundled_data = tomllib.load(f)
            site_only: dict[str, Any] = {}
            if "site" in bundled_data:
                site_only["site"] = bundled_data["site"]
            if site_only and tomli_w is not None:
                with open(site_file, "wb") as f:
                    f.write(f"#:schema {_SCHEMA_BASE_URL}/site.json\n".encode())
                    tomli_w.dump(site_only, f)
                created.append("site.toml")
            elif site_only:
                skipped.append("site.toml (tomli_w not available)")
        else:
            skipped.append("site.toml")

        # Apply per-simulator modules from site profile to simulators.toml
        site_data_loaded = _load_site_toml(site_profile.source_path)
        if site_data_loaded.simulator_modules:
            sim_file = project_dir / _SIMULATORS_FILE
            if sim_file.exists():
                with open(sim_file, "rb") as f:
                    existing = tomllib.load(f)
                sims = existing.get("simulators", {})
                updated = False
                for (
                    sim_name,
                    site_modules,
                ) in site_data_loaded.simulator_modules.items():
                    if sim_name in sims and site_modules:
                        sims[sim_name]["modules"] = site_modules
                        updated = True
                if updated and tomli_w is not None:
                    existing["simulators"] = sims
                    with open(sim_file, "wb") as f:
                        tomli_w.dump(existing, f)

    # SITE.md — copy companion docs from bundled site profile
    if site_profile and site_profile.docs_path:
        site_md = project_dir / "SITE.md"
        if site_md.exists():
            skipped.append("SITE.md")
        else:
            shutil.copy2(site_profile.docs_path, site_md)
            created.append("SITE.md")

    # campaign.toml
    campaign_content = _build_campaign_toml(
        project_name,
        sim_names,
        schema_base_url=_SCHEMA_BASE_URL,
    )
    if _write_if_missing(project_dir / _CAMPAIGN_FILE, campaign_content):
        created.append(_CAMPAIGN_FILE)
    else:
        skipped.append(_CAMPAIGN_FILE)

    # cases/ directory (with per-simulator subdirectories)
    if _mkdir_if_missing(project_dir / "cases"):
        created.append("cases/")
    else:
        skipped.append("cases/")
    for sim in sim_names:
        sim_cases_dir = project_dir / "cases" / sim
        if _mkdir_if_missing(sim_cases_dir):
            created.append(f"cases/{sim}/")

    # runs/ directory
    if _mkdir_if_missing(project_dir / "runs"):
        created.append("runs/")
    else:
        skipped.append("runs/")

    # .runops/ skeleton (insights, facts, generated knowledge)
    _create_runops_skeleton(project_dir, created)

    # notes/ skeleton (chronological lab notebook + reports)
    _create_notes_skeleton(project_dir, created)

    # materials/ skeleton (human-provided source material for agents)
    _create_materials_skeleton(project_dir, created)

    # research/ skeleton (mutable decision ledger + optional snapshots)
    _create_research_skeleton(project_dir, created)

    # refs/ — optional legacy/local mirror of simulator doc repos.  The normal
    # path is simulator/environment Codex plugins plus explicit knowledge
    # sources, so refs are only created when requested.
    if with_refs and sim_names:
        refs_created, refs_skipped = _command_facade._clone_doc_repos(
            project_dir, sim_names
        )
        created.extend(refs_created)
        skipped.extend(refs_skipped)

    # .gitignore
    from runops.harness.builder import build_gitignore_file

    if _write_if_missing(project_dir / ".gitignore", build_gitignore_file()):
        created.append(".gitignore")
    else:
        skipped.append(".gitignore")

    # Interactive knowledge source selection
    if interactive:
        import runops.cli.init as init_facade

        knowledge_sources = init_facade._prompt_knowledge_sources(project_dir)
        if knowledge_sources:
            from runops.core.knowledge_source import save_knowledge_source

            for ks in knowledge_sources:
                save_knowledge_source(project_dir, ks)

    # Bootstrap: .venv for simulator/runtime packages.  The default runops CLI
    # entrypoint is `uvx --from runops runo ...`; installing runops into the
    # project venv is an explicit offline/pinned workflow.
    import runops.cli.init as init_facade

    init_facade._bootstrap_environment(
        project_dir,
        sim_names,
        runops_package,
        created,
        skipped,
        install_runops=install_runops_into_venv,
    )

    # Materialize package-provided agent docs and external knowledge imports.
    knowledge_imports_path = _prepare_knowledge_imports(
        project_dir,
        sim_names,
        sync_sources=True,
    )

    # Build all harness-managed files (CLAUDE.md, AGENTS.md, skills, rules,
    # settings.json, editor settings, subdirectory CLAUDE.md) via the shared
    # builder so that `runo update-harness` can re-render the same set later.
    from runops.harness.builder import (
        GITIGNORE_PATH,
        build_harness_bundle,
        build_managed_gitignore_block,
        hash_text,
        save_harness_lock,
    )

    harness = build_harness_bundle(
        project_name,
        sim_names,
        upstream_feedback=upstream_feedback,
        knowledge_imports_path=knowledge_imports_path,
        include_reference_repos=with_refs,
        codex_plugin_recommendations=codex_plugin_recommendations,
    )
    for rel_path, content in sorted(harness.files.items()):
        full_path = project_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        if _write_if_missing(full_path, content):
            created.append(rel_path)
        else:
            skipped.append(rel_path)

    # Persist template hashes so update-harness can detect user edits.
    lock_hashes = harness.hashes()
    lock_hashes[GITIGNORE_PATH] = hash_text(build_managed_gitignore_block())
    save_harness_lock(project_dir, lock_hashes)

    # HarnessOps project overlay.  runops delegates all state changes to the
    # external hops CLI and keeps init usable when HarnessOps is unavailable.
    if no_harnessops:
        skipped.append("HarnessOps (disabled)")
    else:
        from runops.harness.harnessops import initialize_project_harnessops

        harnessops_result = initialize_project_harnessops(project_dir)
        if harnessops_result.status == "created":
            created.append(harnessops_result.message)
        else:
            skipped.append(harnessops_result.message)
            if harnessops_result.status == "failed":
                typer.echo(f"  Warning: {harnessops_result.message}", err=True)

    # git init
    fresh_git = False
    if (project_dir / ".git").exists():
        skipped.append("git init")
    else:
        result = subprocess.run(
            ["git", "init"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode == 0:
            created.append("git init")
            fresh_git = True
        else:
            typer.echo(f"  Warning: git init failed: {(result.stderr or '').strip()}")

    # Initial commit (only for freshly created repos)
    if fresh_git:
        subprocess.run(
            ["git", "add", "."],
            cwd=project_dir,
            capture_output=True,
            check=False,
        )
        result = subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode == 0:
            created.append("git commit (Initial commit)")
        else:
            typer.echo(
                f"  Warning: initial commit failed: {(result.stderr or '').strip()}"
            )

    # Print results
    typer.echo(f"Initialized project '{project_name}' in {project_dir}")
    if created:
        typer.echo("  Created:")
        for item in created:
            typer.echo(f"    {item}")
    if skipped:
        typer.echo("  Skipped (already exist):")
        for item in skipped:
            typer.echo(f"    {item}")
    echo_plugin_recommendations(codex_plugin_recommendations)
