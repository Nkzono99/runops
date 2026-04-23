"""CLI commands for project initialization and environment checks."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from runops.cli.init_bootstrap import _bootstrap_environment
from runops.cli.init_scaffold import (
    _create_materials_skeleton,
    _create_notes_skeleton,
    _create_runops_skeleton,
    _mkdir_if_missing,
    _write_if_missing,
)
from runops.core.discovery import validate_uniqueness
from runops.core.exceptions import DuplicateRunIdError, ProjectConfigError
from runops.core.project import load_project
from runops.harness.builder import _collect_doc_repos

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_SIMPROJECT_FILE = "runops.toml"
_SIMULATORS_FILE = "simulators.toml"
_LAUNCHERS_FILE = "launchers.toml"
_CAMPAIGN_FILE = "campaign.toml"
_CLAUDE_MD = "CLAUDE.md"
_AGENTS_MD = "AGENTS.md"
_SKILLS_DIR = ".claude/skills"
_RULES_DIR = ".claude/rules"
_CLAUDE_SETTINGS = ".claude/settings.json"
_VSCODE_DIR = ".vscode"
_VSCODE_SETTINGS = "settings.json"

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


def _build_simulators_toml(simulator_names: list[str]) -> str:
    """Build simulators.toml content from adapter default configs.

    Args:
        simulator_names: List of simulator adapter names (e.g. ["emses", "beach"]).

    Returns:
        TOML string for simulators.toml.

    Raises:
        typer.BadParameter: If a simulator name is not recognized.
    """
    # Ensure built-in adapters are registered
    import runops.adapters  # noqa: F401
    from runops.adapters.registry import get_global_registry

    registry = get_global_registry()
    available = registry.list_adapters()

    config: dict[str, Any] = {"simulators": {}}
    for sim_name in simulator_names:
        if sim_name not in available:
            msg = f"Unknown simulator: '{sim_name}'. Available: {', '.join(available)}"
            raise typer.BadParameter(msg)
        adapter_cls = registry.get(sim_name)
        config["simulators"][sim_name] = adapter_cls.default_config()

    if tomli_w is None:
        # Fallback to manual TOML generation
        lines = ["[simulators]", ""]
        for sim_name, sim_cfg in config["simulators"].items():
            lines.append(f"[simulators.{sim_name}]")
            for key, value in sim_cfg.items():
                if isinstance(value, list):
                    items = ", ".join(f'"{v}"' for v in value)
                    lines.append(f"{key} = [{items}]")
                elif isinstance(value, str):
                    lines.append(f'{key} = "{value}"')
                else:
                    lines.append(f"{key} = {value}")
            lines.append("")
        return "\n".join(lines) + "\n"

    import io

    buf = io.BytesIO()
    tomli_w.dump(config, buf)
    return buf.getvalue().decode("utf-8")


def _clone_doc_repos(
    project_dir: Path, simulator_names: list[str]
) -> tuple[list[str], list[str]]:
    """Clone documentation repos into project_dir/refs/.

    Returns:
        Tuple of (created_list, skipped_list).
    """
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
    project_dir: Path, doc_repos: list[tuple[str, str]]
) -> list[str]:
    """Discover manifest-declared agent doc imports from cloned repos.

    Returns:
        List of relative import paths rooted at the project directory.
    """
    from runops.core.knowledge_source import discover_repo_imports

    refs_dir = project_dir / "refs"
    paths: list[str] = []
    for _url, dest in doc_repos:
        repo_root = refs_dir / dest
        if not repo_root.is_dir():
            continue
        for rel_path in discover_repo_imports(repo_root):
            paths.append(f"refs/{dest}/{rel_path}".replace("\\", "/"))

    runops_root = project_dir / "tools" / "runops"
    if runops_root.is_dir():
        for rel_path in discover_repo_imports(runops_root):
            paths.append(f"tools/runops/{rel_path}".replace("\\", "/"))
    return paths


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

    doc_repos = _collect_doc_repos(simulator_names) if simulator_names else []
    agent_doc_imports = _discover_agent_docs(project_dir, doc_repos)

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


def _search_knowledge_repos() -> list[tuple[str, str]]:
    """Search GitHub for shared knowledge repos using ``gh``.

    Looks for repos matching ``*shared_knowledge*`` in the
    authenticated user's repositories.

    Returns:
        List of (full_name, clone_url) tuples.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "repo",
                "list",
                "--limit",
                "50",
                "--json",
                "nameWithOwner,sshUrl,description",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []

    import json

    try:
        repos = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return []

    candidates: list[tuple[str, str]] = []
    for repo in repos:
        name = repo.get("nameWithOwner", "")
        # Match *shared_knowledge* or *shared-knowledge* (case-insensitive)
        repo_name = name.rsplit("/", 1)[-1] if "/" in name else name
        lower = repo_name.lower()
        if "shared_knowledge" in lower or "shared-knowledge" in lower:
            ssh_url = repo.get("sshUrl", "")
            if ssh_url:
                candidates.append((name, ssh_url))

    return candidates


def _prompt_knowledge_sources(
    project_dir: Path,
) -> list[Any]:
    """Interactively prompt the user to attach knowledge sources.

    Searches GitHub for repos matching ``*shared_knowledge*`` or
    ``*shared-knowledge*`` first, then presents them as candidates.
    Also allows manual URL entry.

    Returns:
        List of KnowledgeSource to attach.
    """
    from runops.core.knowledge_source import KnowledgeSource

    # Search first, then ask
    typer.echo("\n  Searching GitHub for shared knowledge repos...")
    candidates = _search_knowledge_repos()

    selected_sources: list[KnowledgeSource] = []

    if candidates:
        typer.echo("\n  Found knowledge repositories:")
        for i, (full_name, _url) in enumerate(candidates, 1):
            typer.echo(f"    {i}. {full_name}")

        selection = typer.prompt(
            "\n  Select repos to attach (comma-separated numbers, Enter to skip)",
            default="",
        )

        for token in selection.split(","):
            token = token.strip()
            if not token:
                continue
            if token.isdigit():
                idx = int(token) - 1
                if 0 <= idx < len(candidates):
                    full_name, url = candidates[idx]
                    repo_name = full_name.rsplit("/", 1)[-1]
                    selected_sources.append(
                        KnowledgeSource(
                            name=repo_name,
                            source_type="git",
                            url=url,
                            ref="main",
                            mount=f"refs/knowledge/{repo_name}",
                        )
                    )
                else:
                    typer.echo(f"    Warning: ignoring invalid number '{token}'")
    else:
        typer.echo("  No shared knowledge repos found on GitHub.")

    # Allow manual entry
    while True:
        manual = typer.prompt(
            "\n  Add a knowledge source manually? "
            "(git URL, local path, or Enter to finish)",
            default="",
        )
        if not manual.strip():
            break

        manual = manual.strip()
        # Detect type
        is_git = (
            manual.startswith("https://")
            or manual.startswith("http://")
            or manual.startswith("git@")
        )
        if is_git:
            # Extract name from URL
            stem = manual.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
            if stem.endswith(".git"):
                stem = stem[:-4]
            source_name = typer.prompt("    Source name", default=stem)
            selected_sources.append(
                KnowledgeSource(
                    name=source_name,
                    source_type="git",
                    url=manual,
                    ref="main",
                    mount=f"refs/knowledge/{source_name}",
                )
            )
        else:
            # Local path
            p = Path(manual).expanduser()
            source_name = typer.prompt("    Source name", default=p.name)
            selected_sources.append(
                KnowledgeSource(
                    name=source_name,
                    source_type="path",
                    url=manual,
                    mount=f"refs/knowledge/{source_name}",
                )
            )
        typer.echo(f"    Added: {source_name}")

    if selected_sources:
        typer.echo(f"\n  {len(selected_sources)} knowledge source(s) selected.")
    return selected_sources


def _prompt_simulators() -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Interactively prompt the user to select and configure simulators.

    Returns:
        Tuple of (simulator_names, {name: config_dict}).
    """
    import runops.adapters  # noqa: F401
    from runops.adapters.registry import get_global_registry

    registry = get_global_registry()
    available = registry.list_adapters()

    typer.echo("\nAvailable simulators:")
    for i, name in enumerate(available, 1):
        typer.echo(f"  {i}. {name}")

    selection = typer.prompt(
        "\nSelect simulators (comma-separated numbers or names, Enter to skip)",
        default="",
    )

    if not selection.strip():
        return [], {}

    # Parse selection — accept both numbers and names
    selected: list[str] = []
    for token in selection.split(","):
        token = token.strip()
        if not token:
            continue
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(available):
                selected.append(available[idx])
            else:
                typer.echo(f"  Warning: ignoring invalid number '{token}'")
        elif token in available:
            selected.append(token)
        else:
            typer.echo(f"  Warning: unknown simulator '{token}', skipping")

    if not selected:
        return [], {}

    # Interactive config for each selected simulator
    use_interactive = typer.confirm("\nCustomize simulator settings?", default=False)

    configs: dict[str, dict[str, Any]] = {}
    for sim_name in selected:
        adapter_cls = registry.get(sim_name)
        if use_interactive:
            configs[sim_name] = adapter_cls.interactive_config()
        else:
            configs[sim_name] = adapter_cls.default_config()

    return selected, configs


@dataclass
class _BundledSiteProfile:
    """A bundled site profile loaded from sites/*.toml.

    Used during ``runo init`` to offer preconfigured site choices.
    The file uses the same ``[site]`` format as project-level ``site.toml``,
    plus an optional ``[launcher]`` section for launcher defaults.

    Attributes:
        name: Site name (file stem, e.g. "camphor").
        launcher: Launcher-only configuration dict for launchers.toml.
        source_path: Path to the bundled .toml file (copied as site.toml).
        docs_path: Path to companion .md documentation (may not exist).
    """

    name: str
    launcher: dict[str, Any]
    source_path: Path
    docs_path: Path | None = None


# Legacy alias for backward compatibility with code that references the old name.
SiteProfile = _BundledSiteProfile


def _load_site_profiles() -> dict[str, _BundledSiteProfile]:
    """Load site profiles from bundled TOML files in runops/sites/.

    Each file uses the unified format:
    - ``[site]`` section → copied as-is to project ``site.toml``
    - ``[launcher]`` section → used for ``launchers.toml`` defaults
    """
    sites_dir = Path(__file__).resolve().parent.parent / "sites"
    profiles: dict[str, _BundledSiteProfile] = {}
    if not sites_dir.is_dir():
        return profiles
    for toml_file in sorted(sites_dir.glob("*.toml")):
        with open(toml_file, "rb") as f:
            data = tomllib.load(f)
        # Require at least a [site] or [launcher] section
        if "site" not in data and "launcher" not in data:
            continue
        launcher_data = dict(data.get("launcher", {}))
        docs_file = toml_file.with_suffix(".md")
        profiles[toml_file.stem] = _BundledSiteProfile(
            name=toml_file.stem,
            launcher=launcher_data,
            source_path=toml_file,
            docs_path=docs_file if docs_file.is_file() else None,
        )
    return profiles


def _prompt_launchers() -> tuple[dict[str, dict[str, Any]], _BundledSiteProfile | None]:
    """Interactively prompt for launcher configuration.

    Returns:
        Tuple of (launcher config dict, selected _BundledSiteProfile or None).
    """
    site_profiles = _load_site_profiles()

    typer.echo("\nLauncher configuration:")
    typer.echo("  Site profiles (preconfigured):")
    site_names = list(site_profiles.keys())
    for i, sname in enumerate(site_names, start=1):
        typer.echo(f"    {i}. {sname}")
    offset = len(site_names)
    typer.echo("  Launcher types:")
    typer.echo(f"    {offset + 1}. srun (Slurm)")
    typer.echo(f"    {offset + 2}. mpirun (OpenMPI)")
    typer.echo(f"    {offset + 3}. mpiexec (MPICH)")

    selection = typer.prompt(
        "\nSelect site profile or launcher type (number or name, Enter to skip)",
        default="",
    )

    sel = selection.strip()
    if not sel:
        return {}, None

    # Check site profiles first
    site_map = {str(i): name for i, name in enumerate(site_names, start=1)}
    if sel in site_map:
        profile_name = site_map[sel]
        profile = site_profiles[profile_name]
        return {profile_name: dict(profile.launcher)}, profile
    if sel in site_profiles:
        profile = site_profiles[sel]
        return {sel: dict(profile.launcher)}, profile

    # Launcher types
    launcher_map = {
        str(offset + 1): "srun",
        str(offset + 2): "mpirun",
        str(offset + 3): "mpiexec",
    }
    launcher_type = launcher_map.get(sel, sel)

    if launcher_type not in ("srun", "mpirun", "mpiexec"):
        typer.echo(f"  Unknown selection '{sel}', skipping")
        return {}, None

    launcher_name = typer.prompt("  Launcher profile name", default=launcher_type)

    config: dict[str, Any] = {"type": launcher_type}

    if launcher_type == "srun":
        use_slurm = typer.confirm(
            "  Use SLURM_NTASKS (rely on #SBATCH --ntasks)?", default=True
        )
        config["use_slurm_ntasks"] = use_slurm
        config["args"] = typer.prompt(
            "  Extra srun arguments (e.g. --mpi=pmix)", default=""
        )
    elif launcher_type in ("mpirun", "mpiexec"):
        config["args"] = typer.prompt(f"  Extra {launcher_type} arguments", default="")

    # Module loading
    modules_str = typer.prompt(
        "  Modules to load (space-separated, Enter to skip)", default=""
    )
    if modules_str.strip():
        config["modules"] = modules_str.strip().split()

    # Clean empty args
    if not config.get("args"):
        config.pop("args", None)

    return {launcher_name: config}, None


def _build_simulators_toml_from_configs(
    configs: dict[str, dict[str, Any]],
) -> str:
    """Serialize simulator configs to TOML string."""
    full_config: dict[str, Any] = {"simulators": configs}

    if tomli_w is None:
        lines = ["[simulators]", ""]
        for sim_name, sim_cfg in configs.items():
            lines.append(f"[simulators.{sim_name}]")
            for key, value in sim_cfg.items():
                if isinstance(value, list):
                    items = ", ".join(f'"{v}"' for v in value)
                    lines.append(f"{key} = [{items}]")
                elif isinstance(value, str):
                    lines.append(f'{key} = "{value}"')
                else:
                    lines.append(f"{key} = {value}")
            lines.append("")
        return "\n".join(lines) + "\n"

    import io

    buf = io.BytesIO()
    tomli_w.dump(full_config, buf)
    return buf.getvalue().decode("utf-8")


def _build_launchers_toml(launchers: dict[str, dict[str, Any]]) -> str:
    """Serialize launcher configs to TOML string."""
    if not launchers:
        return "[launchers]\n"

    full_config: dict[str, Any] = {"launchers": launchers}

    if tomli_w is None:
        lines = ["[launchers]", ""]
        for name, cfg in launchers.items():
            lines.append(f"[launchers.{name}]")
            for key, value in cfg.items():
                if isinstance(value, list):
                    items = ", ".join(f'"{v}"' for v in value)
                    lines.append(f"{key} = [{items}]")
                elif isinstance(value, str):
                    lines.append(f'{key} = "{value}"')
                elif isinstance(value, bool):
                    lines.append(f"{key} = {str(value).lower()}")
                else:
                    lines.append(f"{key} = {value}")
            lines.append("")
        return "\n".join(lines) + "\n"

    import io

    buf = io.BytesIO()
    tomli_w.dump(full_config, buf)
    return buf.getvalue().decode("utf-8")


def _build_campaign_toml(project_name: str, simulator_names: list[str]) -> str:
    """Build a minimal campaign.toml skeleton."""
    from runops.templates import render

    return render(
        "scaffold/campaign.toml.j2",
        schema_base_url=_SCHEMA_BASE_URL,
        project_name=project_name,
        simulator=simulator_names[0] if simulator_names else "",
    )


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
        f"#:schema {_SCHEMA_BASE_URL}/simproject.json\n"
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
        sim_names, sim_configs = _prompt_simulators()
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
        launcher_configs, site_profile = _prompt_launchers()
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
        from runops.core.site import _load_site_toml

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
    campaign_content = _build_campaign_toml(project_name, sim_names)
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

    # refs/ — clone simulator doc repos
    if sim_names:
        refs_created, refs_skipped = _clone_doc_repos(project_dir, sim_names)
        created.extend(refs_created)
        skipped.extend(refs_skipped)

    # .gitignore
    from runops.templates import load_static

    if _write_if_missing(
        project_dir / ".gitignore", load_static("scaffold/gitignore.txt")
    ):
        created.append(".gitignore")
    else:
        skipped.append(".gitignore")

    # Interactive knowledge source selection
    if interactive:
        knowledge_sources = _prompt_knowledge_sources(project_dir)
        if knowledge_sources:
            from runops.core.knowledge_source import save_knowledge_source

            for ks in knowledge_sources:
                save_knowledge_source(project_dir, ks)

    # Bootstrap: .venv + tools/runops + editable install
    _bootstrap_environment(project_dir, sim_names, runops_repo, created, skipped)

    # Discover agent docs after bootstrap so tools/runops/docs/ can be imported.
    knowledge_imports_path = _prepare_knowledge_imports(
        project_dir,
        sim_names,
        sync_sources=True,
    )

    # Build all harness files (CLAUDE.md, AGENTS.md, skills, rules,
    # settings.json, subdirectory CLAUDE.md) via the shared builder so that
    # `runo update-harness` can re-render the same set later.
    from runops.harness.builder import build_harness_bundle, save_harness_lock

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
    save_harness_lock(project_dir, harness.hashes())

    # .vscode/settings.json
    vscode_dir = project_dir / _VSCODE_DIR
    vscode_settings = vscode_dir / _VSCODE_SETTINGS
    if vscode_settings.exists():
        skipped.append(f"{_VSCODE_DIR}/{_VSCODE_SETTINGS}")
    else:
        vscode_dir.mkdir(exist_ok=True)
        vscode_settings.write_text(
            load_static("scaffold/vscode_settings.json"), encoding="utf-8"
        )
        created.append(f"{_VSCODE_DIR}/{_VSCODE_SETTINGS}")

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
