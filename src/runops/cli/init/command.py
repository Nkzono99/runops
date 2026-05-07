"""CLI commands for project initialization and environment checks."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from runops.cli.init.knowledge import _clone_doc_repos, _prepare_knowledge_imports
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
from runops.core.discovery import validate_uniqueness
from runops.core.exceptions import DuplicateRunIdError, ProjectConfigError
from runops.core.project import load_project

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
_DEFAULT_SIMCTL_REPO = "https://github.com/Nkzono99/runops.git"


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
    runops_repo: Annotated[
        str,
        typer.Option(
            "--runops-repo",
            help="Git URL for runops repository.",
        ),
    ] = _DEFAULT_SIMCTL_REPO,
) -> None:
    """Initialize a new runops project (runops.toml etc.).

    By default, runs in interactive mode with guided prompts.
    Use --yes / -y to skip prompts and use defaults.

    Simulator names can also be passed directly:
      runo init emses beach

    Bootstrap usage (no prior install needed):
      uvx --from runops runo init
    """
    interactive = not yes
    project_dir = (path or Path.cwd()).resolve()

    if not project_dir.exists():
        project_dir.mkdir(parents=True)

    # Interactive project name
    if interactive and not name:
        project_name = typer.prompt("Project name", default=project_dir.name)
    else:
        project_name = name or project_dir.name

    created: list[str] = []
    skipped: list[str] = []

    upstream_feedback = not no_upstream_feedback

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

    sim_schema = f"#:schema {_SCHEMA_BASE_URL}/simulators.json\n"
    sim_content = sim_schema + sim_content
    if _write_if_missing(project_dir / _SIMULATORS_FILE, sim_content):
        created.append(_SIMULATORS_FILE)
    else:
        skipped.append(_SIMULATORS_FILE)

    # launchers.toml
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

    # refs/ — clone simulator doc repos
    if sim_names:
        refs_created, refs_skipped = _clone_doc_repos(project_dir, sim_names)
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

    # Bootstrap: .venv + tools/runops + editable install
    import runops.cli.init as init_facade

    init_facade._bootstrap_environment(
        project_dir,
        sim_names,
        runops_repo,
        created,
        skipped,
    )

    # Discover agent docs after bootstrap so tools/runops/docs/ can be imported.
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


def doctor(
    path: Annotated[
        Optional[Path],
        typer.Argument(help="Project directory to check."),
    ] = None,
) -> None:
    """Check the environment and project configuration for issues."""
    project_dir = (path or Path.cwd()).resolve()
    failures: list[str] = []

    # Check runops.toml exists and is valid
    simproject_path = project_dir / _SIMPROJECT_FILE
    if not simproject_path.exists():
        typer.echo("[FAIL] runops.toml not found")
        failures.append(_SIMPROJECT_FILE)
    else:
        try:
            load_project(project_dir)
            typer.echo("[PASS] runops.toml is valid")
        except ProjectConfigError as e:
            typer.echo(f"[FAIL] runops.toml: {e}")
            failures.append(_SIMPROJECT_FILE)

    # Check simulators.toml exists
    if (project_dir / _SIMULATORS_FILE).exists():
        typer.echo("[PASS] simulators.toml found")
    else:
        typer.echo("[FAIL] simulators.toml not found")
        failures.append(_SIMULATORS_FILE)

    # Check launchers.toml exists
    if (project_dir / _LAUNCHERS_FILE).exists():
        typer.echo("[PASS] launchers.toml found")
    else:
        typer.echo("[FAIL] launchers.toml not found")
        failures.append(_LAUNCHERS_FILE)

    # Check sbatch availability
    if shutil.which("sbatch") is not None:
        typer.echo("[PASS] sbatch is available")
    else:
        typer.echo("[FAIL] sbatch not found in PATH")
        failures.append("sbatch")

    # Check simulator adapters from simulators.toml
    simulators_path = project_dir / _SIMULATORS_FILE
    if simulators_path.exists():
        try:
            with open(simulators_path, "rb") as f:
                sim_data = tomllib.load(f)
            simulators: dict[str, Any] = sim_data.get("simulators", {})
            if simulators:
                from runops.adapters.registry import AdapterRegistry

                registry = AdapterRegistry()
                for sim_name, sim_cfg in simulators.items():
                    if not isinstance(sim_cfg, dict):
                        continue
                    adapter_name = sim_cfg.get("adapter", "")
                    if not adapter_name:
                        continue
                    try:
                        registry.load_from_config({"simulators": {sim_name: sim_cfg}})
                        typer.echo(
                            f"[PASS] Simulator adapter '{adapter_name}' "
                            f"for '{sim_name}' is importable"
                        )
                    except Exception as e:
                        typer.echo(
                            f"[FAIL] Simulator adapter '{adapter_name}' "
                            f"for '{sim_name}': {e}"
                        )
                        failures.append(f"adapter:{adapter_name}")
        except tomllib.TOMLDecodeError as e:
            typer.echo(f"[FAIL] simulators.toml parse error: {e}")
            failures.append(_SIMULATORS_FILE)

    # Check launcher configs from launchers.toml
    launchers_path = project_dir / _LAUNCHERS_FILE
    if launchers_path.exists():
        try:
            with open(launchers_path, "rb") as f:
                launcher_data = tomllib.load(f)
            launchers: dict[str, Any] = launcher_data.get("launchers", {})
            if launchers:
                from runops.launchers.base import Launcher, LauncherConfigError

                for lname, lcfg in launchers.items():
                    if not isinstance(lcfg, dict):
                        continue
                    try:
                        Launcher.from_config(lname, lcfg)
                        typer.echo(f"[PASS] Launcher profile '{lname}' is valid")
                    except LauncherConfigError as e:
                        typer.echo(f"[FAIL] Launcher profile '{lname}': {e}")
                        failures.append(f"launcher:{lname}")
        except tomllib.TOMLDecodeError as e:
            typer.echo(f"[FAIL] launchers.toml parse error: {e}")
            failures.append(_LAUNCHERS_FILE)

    # Check run_id uniqueness
    runs_dir = project_dir / "runs"
    if runs_dir.is_dir():
        try:
            validate_uniqueness(runs_dir)
            typer.echo("[PASS] No duplicate run_ids")
        except DuplicateRunIdError as e:
            typer.echo(f"[FAIL] Duplicate run_id: {e}")
            failures.append("run_id uniqueness")
    else:
        typer.echo("[PASS] No runs/ directory (nothing to check)")

    # Environment detection
    typer.echo("\n--- Environment ---")
    try:
        from runops.core.environment import (
            detect_environment,
            load_environment,
            save_environment,
        )

        existing = load_environment(project_dir)
        if existing:
            typer.echo(
                f"[PASS] environment.toml found (cluster: {existing.cluster_name})"
            )
            if existing.partitions:
                for p in existing.partitions:
                    default_mark = " (default)" if p.default else ""
                    typer.echo(f"       partition: {p.name}{default_mark}")
        else:
            typer.echo("[INFO] Detecting environment...")
            env_info = detect_environment()
            if env_info.partitions:
                typer.echo(
                    f"       Detected {len(env_info.partitions)} Slurm partition(s)"
                )
            try:
                env_path = save_environment(project_dir, env_info)
                typer.echo(
                    f"[PASS] Saved environment to {env_path.relative_to(project_dir)}"
                )
            except RuntimeError:
                typer.echo(
                    "[WARN] Could not save environment.toml (tomli_w not installed)"
                )
    except Exception as e:
        typer.echo(f"[WARN] Environment detection failed: {e}")

    # Campaign check
    campaign_file = project_dir / "campaign.toml"
    if campaign_file.is_file():
        try:
            from runops.core.campaign import load_campaign

            campaign = load_campaign(project_dir)
            if campaign:
                typer.echo(f"[PASS] campaign.toml: {campaign.name}")
        except Exception as e:
            typer.echo(f"[FAIL] campaign.toml: {e}")
            failures.append("campaign.toml")
    else:
        typer.echo("[INFO] No campaign.toml (optional)")

    # Final verdict
    if failures:
        typer.echo(f"\n{len(failures)} check(s) failed.")
        raise typer.Exit(code=1)
    else:
        typer.echo("\nAll checks passed.")
