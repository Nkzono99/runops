"""Job script (job.sh) generation.

Generates scheduler batch scripts from run configuration, launcher profile,
and site profile (HPC environment abstraction).

Supports Slurm resource specification modes:

- **Standard mode**: ``#SBATCH --nodes`` / ``#SBATCH --ntasks``
- **RSC mode**: ``#SBATCH --rsc p=N:t=T:c=C`` (custom Slurm environments)

For PBS sites, emits ``#PBS`` directives with ``select=...`` resources.
"""

from __future__ import annotations

import re
import shlex
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    extra_pbs: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    modules: list[str] | None = None,
    setup_commands: list[str] | None = None,
    version_commands: list[str] | None = None,
    post_commands: list[str] | None = None,
    script_run_dir: Path | None = None,
    scheduler: str = "slurm",
    resource_style: str = "standard",
    stdout_format: str | None = None,
    stderr_format: str | None = None,
) -> Path:
    """Generate a ``job.sh`` script for scheduler submission.

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
        extra_pbs: (Legacy) Additional ``#PBS`` lines.
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
        scheduler: (Legacy) Scheduler backend (``"slurm"`` or ``"pbs"``).
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
        effective_scheduler = site.scheduler
        effective_resource_style = site.resource_style
        effective_modules = site.modules_for(simulator_name)
        effective_extra_sbatch = list(site.extra_sbatch)
        effective_extra_pbs = list(site.extra_pbs)
        effective_env = dict(site.env)
        effective_stdout = site.stdout_format
        effective_stderr = site.stderr_format
        effective_setup: list[str] = list(extra_setup_commands or [])
        effective_setup.extend(site.setup_commands)
    else:
        effective_scheduler = scheduler
        effective_resource_style = resource_style
        effective_modules = list(modules or [])
        effective_extra_sbatch = list(extra_sbatch or [])
        effective_extra_pbs = list(extra_pbs or [])
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

    if site is not None and site.pbs_group and not job_config.get("group"):
        job_config = dict(job_config)
        job_config["group"] = site.pbs_group

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
        scheduler=effective_scheduler,
        extra_sbatch=effective_extra_sbatch,
        extra_pbs=effective_extra_pbs,
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
    scheduler: str,
    extra_sbatch: list[str],
    extra_pbs: list[str],
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
    normalized_scheduler = scheduler.lower()
    if normalized_scheduler == "slurm":
        return _render_slurm_script(
            job_config=job_config,
            exec_line=exec_line,
            run_dir=run_dir,
            run_id=run_id,
            extra_sbatch=extra_sbatch,
            extra_env=extra_env,
            modules=modules,
            setup_commands=setup_commands,
            version_commands=version_commands,
            post_commands=post_commands,
            resource_style=resource_style,
            stdout_format=stdout_format,
            stderr_format=stderr_format,
        )
    if normalized_scheduler == "pbs":
        return _render_pbs_script(
            job_config=job_config,
            exec_line=exec_line,
            run_dir=run_dir,
            run_id=run_id,
            extra_pbs=extra_pbs,
            extra_env=extra_env,
            modules=modules,
            setup_commands=setup_commands,
            version_commands=version_commands,
            post_commands=post_commands,
            stdout_format=stdout_format,
            stderr_format=stderr_format,
        )
    raise JobScriptError(f"Unsupported scheduler: {scheduler!r}")


def _render_slurm_script(
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
    """Render a Slurm job script as a string."""
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

    _append_script_body(
        lines,
        run_dir=run_dir,
        exec_line=exec_line,
        extra_env=extra_env,
        modules=modules,
        setup_commands=setup_commands,
        version_commands=version_commands,
        post_commands=post_commands,
    )

    return "\n".join(lines)


def _pbs_select_value(job_config: dict[str, Any]) -> str:
    """Render a PBS ``select=`` resource value."""
    nodes = int(job_config.get("nodes", 1))
    if nodes < 1:
        raise JobScriptError("PBS nodes must be >= 1")

    chunks: list[str] = []
    gpus = int(job_config.get("gpus", 0) or 0)
    if gpus:
        chunks.append(f"ngpus={gpus}")
    else:
        sockets = int(job_config.get("sockets", 1))
        if sockets < 1:
            raise JobScriptError("PBS sockets must be >= 1")
        chunks.append(f"nsockets={sockets}")

    mpiprocs = int(job_config.get("mpiprocs", 0) or 0)
    if not mpiprocs:
        ntasks = int(job_config.get("ntasks", 0) or 0)
        if ntasks:
            if ntasks % nodes != 0:
                raise JobScriptError(
                    "PBS ntasks must be divisible by nodes, or set mpiprocs"
                )
            mpiprocs = ntasks // nodes
    if mpiprocs:
        chunks.append(f"mpiprocs={mpiprocs}")

    ompthreads = int(job_config.get("ompthreads", 0) or 0)
    if ompthreads:
        chunks.append(f"ompthreads={ompthreads}")

    return f"{nodes}:{':'.join(chunks)}"


def _render_pbs_script(
    *,
    job_config: dict[str, Any],
    exec_line: str,
    run_dir: Path,
    run_id: str,
    extra_pbs: list[str],
    extra_env: dict[str, str],
    modules: list[str],
    setup_commands: list[str],
    version_commands: list[str],
    post_commands: list[str],
    stdout_format: str | None = None,
    stderr_format: str | None = None,
) -> str:
    """Render a PBS Professional job script as a string."""
    lines: list[str] = ["#!/bin/bash -l"]

    queue = job_config.get("queue") or job_config.get("partition", "")
    if queue:
        lines.append(f"#PBS -q {queue}")

    lines.append(f"#PBS -l select={_pbs_select_value(job_config)}")
    lines.append(f"#PBS -l walltime={job_config['walltime']}")

    group = job_config.get("group", "")
    if group:
        lines.append(f"#PBS -W group_list={group}")

    if stdout_format:
        lines.append(f"#PBS -o {stdout_format}")
    if stderr_format:
        lines.append(f"#PBS -e {stderr_format}")
    if not stderr_format:
        lines.append("#PBS -j oe")

    job_name = job_config.get("job_name", run_id or "runops-job")
    if job_name:
        lines.append(f"#PBS -N {job_name}")

    for directive in extra_pbs:
        lines.append(f"#PBS {directive}")

    lines.append("")
    lines.append("set -euo pipefail")

    _append_script_body(
        lines,
        run_dir=run_dir,
        exec_line=exec_line,
        extra_env=extra_env,
        modules=modules,
        setup_commands=setup_commands,
        version_commands=version_commands,
        post_commands=post_commands,
    )

    return "\n".join(lines)


def _append_script_body(
    lines: list[str],
    *,
    run_dir: Path,
    exec_line: str,
    extra_env: dict[str, str],
    modules: list[str],
    setup_commands: list[str],
    version_commands: list[str],
    post_commands: list[str],
) -> None:
    """Append common shell body shared by Slurm and PBS scripts."""
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
    # Use absolute path so the script works regardless of scheduler cwd.
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
