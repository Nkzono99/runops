"""Interactive prompting helpers for ``runo init``."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from runops.core.codex_plugin import CodexPluginRecommendation

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def _search_knowledge_repos() -> list[tuple[str, str]]:
    """Search GitHub for shared knowledge repos using ``gh``."""
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
    """Interactively prompt the user to attach knowledge sources."""
    from runops.core.knowledge_source import KnowledgeSource

    del project_dir  # reserved for future prompt context

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

    while True:
        manual = typer.prompt(
            "\n  Add a knowledge source manually? "
            "(git URL, local path, or Enter to finish)",
            default="",
        )
        if not manual.strip():
            break

        manual = manual.strip()
        is_git = (
            manual.startswith("https://")
            or manual.startswith("http://")
            or manual.startswith("git@")
        )
        if is_git:
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
            source_path = Path(manual).expanduser()
            source_name = typer.prompt("    Source name", default=source_path.name)
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
    """Interactively prompt the user to select and configure simulators."""
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
    """A bundled site profile loaded from sites/*.toml."""

    name: str
    launcher: dict[str, Any]
    source_path: Path
    docs_path: Path | None = None
    codex_plugins: list[CodexPluginRecommendation] | None = None


SiteProfile = _BundledSiteProfile


def _load_site_profiles() -> dict[str, _BundledSiteProfile]:
    """Load site profiles from bundled TOML files in runops/sites/."""
    sites_dir = Path(__file__).resolve().parents[2] / "sites"
    profiles: dict[str, _BundledSiteProfile] = {}
    if not sites_dir.is_dir():
        return profiles
    for toml_file in sorted(sites_dir.glob("*.toml")):
        with open(toml_file, "rb") as f:
            data = tomllib.load(f)
        if "site" not in data and "launcher" not in data:
            continue
        from runops.core.site.profile import _load_site_toml

        site_profile = _load_site_toml(toml_file)
        launcher_data = dict(data.get("launcher", {}))
        docs_file = toml_file.with_suffix(".md")
        profiles[toml_file.stem] = _BundledSiteProfile(
            name=toml_file.stem,
            launcher=launcher_data,
            source_path=toml_file,
            docs_path=docs_file if docs_file.is_file() else None,
            codex_plugins=site_profile.codex_plugins,
        )
    return profiles


def _prompt_launchers() -> tuple[dict[str, dict[str, Any]], _BundledSiteProfile | None]:
    """Interactively prompt for launcher configuration."""
    site_profiles = _load_site_profiles()

    typer.echo("\nLauncher configuration:")
    typer.echo("  Site profiles (preconfigured):")
    site_names = list(site_profiles.keys())
    for i, sname in enumerate(site_names, start=1):
        suffix = "" if site_profiles[sname].launcher else " (site docs/plugin only)"
        typer.echo(f"    {i}. {sname}{suffix}")
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

    site_map = {str(i): name for i, name in enumerate(site_names, start=1)}
    if sel in site_map:
        profile_name = site_map[sel]
        profile = site_profiles[profile_name]
        launchers = {profile_name: dict(profile.launcher)} if profile.launcher else {}
        return launchers, profile
    if sel in site_profiles:
        profile = site_profiles[sel]
        launchers = {sel: dict(profile.launcher)} if profile.launcher else {}
        return launchers, profile

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
            "  Use SLURM_NTASKS (rely on #SBATCH --ntasks)?",
            default=True,
        )
        config["use_slurm_ntasks"] = use_slurm
        config["args"] = typer.prompt(
            "  Extra srun arguments (e.g. --mpi=pmix)",
            default="",
        )
    elif launcher_type in ("mpirun", "mpiexec"):
        config["args"] = typer.prompt(f"  Extra {launcher_type} arguments", default="")

    modules_str = typer.prompt(
        "  Modules to load (space-separated, Enter to skip)",
        default="",
    )
    if modules_str.strip():
        config["modules"] = modules_str.strip().split()

    if not config.get("args"):
        config.pop("args", None)

    return {launcher_name: config}, None
