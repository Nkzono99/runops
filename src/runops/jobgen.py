"""job.sh generation (SPEC §5, §6.1).

The script ``cd``s to the run directory; the program command from the
adapter is relative to it.  Slurm stdout/stderr go to ``work/``.  On exit
the script writes ``submit/exit.<job_id>`` (exit code, start/end time) so
``sync`` can settle the run without Slurm accounting.
"""

from __future__ import annotations

import re
import shlex
import stat
from pathlib import Path
from typing import Any

from runops.case import walltime_hours
from runops.config import LauncherConfig, SimulatorConfig, SiteConfig
from runops.errors import UsageError
from runops.launchers import exec_line

_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EXIT_RECORD_DIR = "submit"


def render_job_script(
    *,
    run_dir: Path,
    run_id: str,
    job: dict[str, Any],
    site: SiteConfig,
    launcher: LauncherConfig,
    sim: SimulatorConfig,
    program: list[str],
    prelude: list[str] | None = None,
    venv_activate: Path | None = None,
) -> str:
    walltime = str(job.get("walltime", ""))
    if walltime_hours(walltime) is None:
        raise UsageError(f"{run_id}: [job].walltime must be [D-]H:MM:SS, got {walltime!r}")
    lines = ["#!/bin/bash"]
    if job.get("partition"):
        lines.append(f"#SBATCH -p {job['partition']}")
    if job.get("qos"):
        lines.append(f"#SBATCH --qos={job['qos']}")
    if site.resource_style == "rsc":
        p = int(job.get("processes", job.get("ntasks", 1)) or 1)
        t = int(job.get("threads", 1) or 1)
        c = int(job.get("cores", t) or t)
        rsc = f"p={p}:t={t}:c={c}"
        if job.get("memory"):
            rsc += f":m={job['memory']}"
        if job.get("gpus"):
            rsc += f":g={job['gpus']}"
        lines.append(f"#SBATCH --rsc {rsc}")
    else:
        for key, flag in (
            ("nodes", "--nodes"),
            ("ntasks", "--ntasks"),
            ("cpus_per_task", "--cpus-per-task"),
            ("memory", "--mem"),
            ("gpus", "--gpus"),
        ):
            if job.get(key):
                lines.append(f"#SBATCH {flag}={job[key]}")
    lines.append(f"#SBATCH -t {walltime}")
    work = run_dir / "work"
    lines.append(f"#SBATCH -o {site.stdout or work / '%j.out'}")
    lines.append(f"#SBATCH -e {site.stderr or work / '%j.err'}")
    lines.append(f"#SBATCH -J {job.get('job_name') or run_id}")
    for directive in [*site.extra_sbatch, *_list(job.get("extra_sbatch"))]:
        lines.append(f"#SBATCH {directive}")
    lines.append("")
    lines.append("set -o pipefail")

    modules: list[str] = []
    for module in [
        *site.modules,
        *launcher.modules,
        *sim.modules,
        *_list(job.get("modules")),
    ]:
        if module not in modules:
            modules.append(module)
    if modules:
        lines.append("module load " + " ".join(shlex.quote(m) for m in modules))

    env = {**site.env, **{str(k): str(v) for k, v in sim.raw.get("env", {}).items()}}
    for key, value in sorted(env.items()):
        if not _ENV_RE.match(key):
            raise UsageError(f"invalid environment variable name {key!r}")
        lines.append(f"export {key}={shlex.quote(value)}")

    lines.append(f"cd {shlex.quote(str(run_dir))}")
    if venv_activate is not None:
        lines.append(f"source {shlex.quote(str(venv_activate))}")
    setup = [*site.setup_commands, *_list(job.get("pre_commands")), *(prelude or [])]
    lines.extend(setup)
    lines.append("runops_start=$(date -Is)")
    lines.append('echo "runops: start ${runops_start} on $(hostname)"')
    lines.append(exec_line(launcher, program, job))
    lines.append("status=$?")
    lines.extend(_list(job.get("post_commands")))
    lines.append('echo "runops: end $(date -Is) exit=${status}"')
    lines.append(
        'printf \'exit_code = %s\\nstarted_at = "%s"\\nfinished_at = "%s"\\nhostname = "%s"\\n\' '
        '"${status}" "${runops_start}" "$(date -Is)" "$(hostname)" '
        f'> "{EXIT_RECORD_DIR}/exit.${{SLURM_JOB_ID:-local}}"'
    )
    lines.append("exit ${status}")
    return "\n".join(lines) + "\n"


def exit_record_path(run_dir: Path, job_id: str) -> Path:
    """``submit/exit.<job_id>``, written by job.sh when the program exits."""
    return run_dir / EXIT_RECORD_DIR / f"exit.{job_id}"


def write_job_script(run_dir: Path, content: str) -> Path:
    path = run_dir / "submit" / "job.sh"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return path


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]
