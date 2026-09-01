"""Job script (job.sh) generation.

Generates Slurm batch scripts from run configuration, launcher profile,
and site profile (HPC environment abstraction).

Supports two resource specification modes:

- **Standard mode**: ``#SBATCH --nodes`` / ``#SBATCH --ntasks``
- **RSC mode**: ``#SBATCH --rsc p=N:t=T:c=C`` (custom Slurm environments)
"""

from __future__ import annotations

import re
import shlex
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runops.core.case import parse_walltime_hours

if TYPE_CHECKING:
    from runops.core.site import SiteProfile


class JobScriptError(RuntimeError):
    """Raised when job script generation fails due to invalid parameters."""


_SHELL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def generate_job_script(
    run_dir: Path,
    job_config: dict[str, Any],
    exec_line: str,
    *,
    run_id: str = "",
    site: SiteProfile | None = None,
    simulator_name: str = "",
    extra_setup_commands: list[str] | None = None,
    # --- Legacy kwargs (used when site is None) ---
    extra_sbatch: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    modules: list[str] | None = None,
    setup_commands: list[str] | None = None,
    version_commands: list[str] | None = None,
    post_commands: list[str] | None = None,
    script_run_dir: Path | None = None,
    resource_style: str = "standard",
    stdout_format: str | None = None,
    stderr_format: str | None = None,
) -> Path:
    """Generate a ``job.sh`` script for Slurm submission.

    The script is written to ``<run_dir>/submit/job.sh`` and made executable.

    When *site* is provided, environment-dependent values (resource_style,
    modules, extra_sbatch, env, stdout/stderr formats, setup_commands) are
    taken from the :class:`~runops.core.site.SiteProfile`.  The legacy
    keyword arguments are ignored in that case.

    Args:
        run_dir: Target run directory.
        job_config: Job parameters.  Required keys: ``walltime``.
            Optional: ``partition``, ``nodes``, ``ntasks``, ``job_name``.
        exec_line: The execution line produced by the launcher.
        run_id: Run identifier used as the default job name.
        site: Site profile supplying environment-dependent settings.
        simulator_name: Simulator name (for per-simulator module lookup
            in *site*).
        extra_setup_commands: Additional setup commands to prepend
            (e.g. venv activation).  These are prepended before
            site/job_config setup commands.
        extra_sbatch: (Legacy) Additional ``#SBATCH`` lines.
        extra_env: (Legacy) Extra environment variables.
        modules: (Legacy) Module names to load.
        setup_commands: (Legacy) Shell commands before execution.
        version_commands: Shell commands that capture simulator/runtime
            version information before execution.
        post_commands: Shell commands after execution.
        script_run_dir: Run directory path embedded in the generated script.
            Defaults to *run_dir*. Used when writing into a staging directory
            before atomically moving the completed run into place.
        resource_style: (Legacy) ``"standard"`` or ``"rsc"``.
        stdout_format: (Legacy) Custom stdout format.
        stderr_format: (Legacy) Custom stderr format.

    Returns:
        Path to the generated ``submit/job.sh`` file.

    Raises:
        JobScriptError: If required keys are missing from *job_config*.
    """
    _validate_job_config(job_config)

    # Resolve settings from SiteProfile or legacy kwargs
    if site is not None:
        effective_resource_style = site.resource_style
        effective_modules = site.modules_for(simulator_name)
        effective_extra_sbatch = list(site.extra_sbatch)
        effective_env = dict(site.env)
        effective_stdout = site.stdout_format
        effective_stderr = site.stderr_format
        effective_setup: list[str] = list(extra_setup_commands or [])
        effective_setup.extend(site.setup_commands)
    else:
        effective_resource_style = resource_style
        effective_modules = list(modules or [])
        effective_extra_sbatch = list(extra_sbatch or [])
        effective_env = dict(extra_env or {})
        effective_stdout = stdout_format
        effective_stderr = stderr_format
        effective_setup = list(extra_setup_commands or [])
        effective_setup.extend(setup_commands or [])

    # Merge modules from job_config
    config_modules = job_config.get("modules", [])
    if isinstance(config_modules, list):
        for m in config_modules:
            if m not in effective_modules:
                effective_modules.append(m)

    # Merge setup/post commands from job_config
    config_pre = job_config.get("pre_commands", job_config.get("setup_commands", []))
    if isinstance(config_pre, list):
        effective_setup.extend(config_pre)

    all_post = list(job_config.get("post_commands", []))
    if post_commands:
        all_post.extend(post_commands)

    content = _render_script(
        job_config=job_config,
        exec_line=exec_line,
        run_dir=script_run_dir or run_dir,
        run_id=run_id,
        extra_sbatch=effective_extra_sbatch,
        extra_env=effective_env,
        modules=effective_modules,
        setup_commands=effective_setup,
        version_commands=list(version_commands or []),
        post_commands=all_post,
        resource_style=effective_resource_style,
        stdout_format=effective_stdout,
        stderr_format=effective_stderr,
    )

    return write_job_script(run_dir, content)


def write_job_script(run_dir: Path, content: str) -> Path:
    """Write job script content to ``<run_dir>/submit/job.sh``.

    Creates the ``submit/`` directory if it does not exist and sets the
    executable permission bit on the resulting file.

    Args:
        run_dir: Target run directory.
        content: Full shell script content.

    Returns:
        Path to the written job script.
    """
    submit_dir = run_dir / "submit"
    submit_dir.mkdir(parents=True, exist_ok=True)

    job_sh = submit_dir / "job.sh"
    job_sh.write_text(content)
    job_sh.chmod(job_sh.stat().st_mode | stat.S_IEXEC)
    return job_sh


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_REQUIRED_JOB_KEYS = ("walltime",)


def _validate_job_config(job_config: dict[str, Any]) -> None:
    """Ensure all required keys are present in *job_config*.

    Raises:
        JobScriptError: If any required key is missing.
    """
    missing = [k for k in _REQUIRED_JOB_KEYS if k not in job_config]
    if missing:
        raise JobScriptError(f"Missing required job config keys: {', '.join(missing)}")

    walltime = job_config.get("walltime")
    if not isinstance(walltime, str) or parse_walltime_hours(walltime) is None:
        raise JobScriptError(
            "Invalid walltime: expected a positive H+:MM:SS or D-H+:MM:SS "
            "duration with minutes and seconds in 00..59"
        )

    qos = job_config.get("qos")
    if isinstance(qos, str) and any(char in qos for char in ("\n", "\r")):
        raise JobScriptError("Invalid qos: newline characters are not allowed")


def _quote_words(words: list[str]) -> str:
    """Quote a list of shell words while preserving simple values."""
    return " ".join(shlex.quote(word) for word in words)


def _export_line(key: str, value: str) -> str:
    """Render a safe shell export assignment."""
    if not _SHELL_IDENTIFIER_RE.match(key):
        raise JobScriptError(f"Invalid environment variable name: {key!r}")
    return f"export {key}={shlex.quote(value)}"


def _render_script(
    *,
    job_config: dict[str, Any],
    exec_line: str,
    run_dir: Path,
    run_id: str,
    extra_sbatch: list[str],
    extra_env: dict[str, str],
    modules: list[str],
    setup_commands: list[str],
    version_commands: list[str],
    post_commands: list[str],
    resource_style: str = "standard",
    stdout_format: str | None = None,
    stderr_format: str | None = None,
) -> str:
    """Render the complete job script as a string."""
    lines: list[str] = ["#!/bin/bash"]

    # --- SBATCH directives ---
    partition = job_config.get("partition", "")
    if partition:
        lines.append(f"#SBATCH -p {partition}")

    qos = job_config.get("qos", "")
    if qos:
        lines.append(f"#SBATCH --qos={qos}")

    if resource_style == "rsc":
        # Camphor-style: --rsc p=N:t=T:c=C[:m=MEM][:g=GPU]
        ntasks = job_config.get("ntasks", 1)
        threads = job_config.get("threads_per_process", 1)
        cores = job_config.get("cores_per_thread", 1)
        rsc_parts = f"p={ntasks}:t={threads}:c={cores}"
        memory = job_config.get("memory", "")
        if memory:
            rsc_parts += f":m={memory}"
        gpus = job_config.get("gpus", 0)
        if gpus:
            rsc_parts += f":g={gpus}"
        lines.append(f"#SBATCH --rsc {rsc_parts}")
    else:
        # Standard Slurm directives
        if "nodes" in job_config:
            lines.append(f"#SBATCH --nodes={job_config['nodes']}")
        if "ntasks" in job_config:
            lines.append(f"#SBATCH --ntasks={job_config['ntasks']}")
        if "cpus_per_task" in job_config:
            lines.append(f"#SBATCH --cpus-per-task={job_config['cpus_per_task']}")

    lines.append(f"#SBATCH -t {job_config['walltime']}")

    # stdout / stderr
    work_dir = run_dir / "work"
    if stdout_format:
        lines.append(f"#SBATCH -o {stdout_format}")
    else:
        lines.append(f"#SBATCH --output={work_dir / '%j.out'}")
    if stderr_format:
        lines.append(f"#SBATCH -e {stderr_format}")
    else:
        lines.append(f"#SBATCH --error={work_dir / '%j.err'}")

    job_name = job_config.get("job_name", run_id or "runops-job")
    if job_name:
        lines.append(f"#SBATCH -J {job_name}")

    for directive in extra_sbatch:
        lines.append(f"#SBATCH {directive}")

    lines.append("")

    # --- Module loads ---
    if modules:
        lines.append(f"module load {_quote_words(modules)}")
        lines.append("")

    # --- Environment variables ---
    if extra_env:
        for key, value in sorted(extra_env.items()):
            lines.append(_export_line(str(key), str(value)))
        lines.append("")

    # --- Change to run directory ---
    # Use absolute path so the script works regardless of sbatch cwd.
    # Simulators refer to input/ and work/ relative to the run root.
    lines.append(f"cd {shlex.quote(str(run_dir))}")
    lines.append("")

    lines.append("date")
    lines.append("")

    # --- Setup commands (before main execution) ---
    if setup_commands:
        for cmd in setup_commands:
            lines.append(cmd)
        lines.append("")

    if version_commands:
        lines.append("# Runtime metadata")
        for cmd in version_commands:
            lines.append(cmd)
        lines.append("")

    # --- Main execution ---
    lines.append(exec_line)
    lines.append("")

    lines.append("date")
    lines.append("")

    # --- Post commands (after main execution) ---
    if post_commands:
        lines.append("# Postprocessing")
        for cmd in post_commands:
            lines.append(cmd)
        lines.append("")

    return "\n".join(lines)
