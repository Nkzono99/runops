"""Project and environment doctor workflow."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from runops.application.gateway.plugins import check_project_codex_plugins
from runops.core.discovery import validate_uniqueness
from runops.core.exceptions import DuplicateRunIdError, ProjectConfigError
from runops.core.project import load_project

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_SIMPROJECT_FILE = "runops.toml"
_SIMULATORS_FILE = "simulators.toml"
_LAUNCHERS_FILE = "launchers.toml"


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

    # Codex plugin recommendation metadata. This does not inspect user-local
    # plugin installation state; it only validates project-side recommendations.
    try:
        plugin_check = check_project_codex_plugins(project_dir)
        errors = [issue for issue in plugin_check.issues if issue.severity == "error"]
        warnings = [
            issue for issue in plugin_check.issues if issue.severity == "warning"
        ]
        if errors:
            typer.echo(
                "[FAIL] Codex plugin recommendation metadata: "
                f"{len(errors)} error(s), {len(warnings)} warning(s)"
            )
            failures.append("codex_plugins")
        elif warnings:
            typer.echo(
                "[WARN] Codex plugin recommendation metadata: "
                f"0 error(s), {len(warnings)} warning(s)"
            )
        else:
            typer.echo("[PASS] Codex plugin recommendation metadata OK")
        for issue in plugin_check.issues:
            source = f" source={issue.source}" if issue.source else ""
            typer.echo(
                f"       [{issue.severity}] {issue.plugin_name}.{issue.field}:"
                f"{source} {issue.message}"
            )
    except Exception as e:
        typer.echo(f"[FAIL] Codex plugin recommendation metadata: {e}")
        failures.append("codex_plugins")

    # Final verdict
    if failures:
        typer.echo(f"\n{len(failures)} check(s) failed.")
        raise typer.Exit(code=1)
    else:
        typer.echo("\nAll checks passed.")
