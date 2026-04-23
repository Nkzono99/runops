"""Environment bootstrap helpers for ``runo init``."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import typer

from runops.harness.builder import _collect_pip_packages


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


def _find_uv() -> str:
    """Find the uv executable, falling back to 'uv'."""
    uv_path = shutil.which("uv")
    return uv_path if uv_path else "uv"


def _python_in_venv(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _activation_hint() -> str:
    if sys.platform == "win32":
        return r".venv\Scripts\activate"
    return "source .venv/bin/activate"


def _bootstrap_environment(
    project_dir: Path,
    sim_names: list[str],
    runops_repo: str,
    created: list[str],
    skipped: list[str],
) -> None:
    """Bootstrap .venv, clone runops into tools/, and editable-install."""
    uv = _find_uv()
    venv_dir = project_dir / ".venv"
    tools_dir = project_dir / "tools"
    runops_dir = tools_dir / "runops"
    python_path = _python_in_venv(venv_dir)

    if venv_dir.exists():
        skipped.append(".venv")
    else:
        typer.echo("  Creating .venv ...")
        venv_result = subprocess.run(
            [uv, "venv", str(venv_dir)],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if venv_result.returncode == 0:
            created.append(".venv")
        else:
            typer.echo(
                f"  Warning: uv venv failed: {(venv_result.stderr or '').strip()}"
            )
            return

    if runops_dir.exists():
        skipped.append("tools/runops")
    else:
        typer.echo("  Cloning runops into tools/ ...")
        tools_dir.mkdir(exist_ok=True)
        clone_result = subprocess.run(
            ["git", "clone", runops_repo, str(runops_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if clone_result.returncode == 0:
            created.append("tools/runops")
        else:
            typer.echo(
                f"  Warning: git clone failed: "
                f"{(clone_result.stderr or '').strip()[:300]}"
            )
            return

    typer.echo("  Installing runops (editable) ...")
    install_result = subprocess.run(
        [
            uv,
            "pip",
            "install",
            "-e",
            str(runops_dir),
            "--python",
            str(python_path),
        ],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if install_result.returncode == 0:
        created.append("uv pip install -e tools/runops")
    else:
        typer.echo(
            f"  Warning: editable install failed:\n"
            f"    {(install_result.stderr or '').strip()[:300]}"
        )

    pip_pkgs = _collect_pip_packages(sim_names) if sim_names else []
    if pip_pkgs:
        typer.echo(f"  Installing: {', '.join(pip_pkgs)} ...")
        pkg_result = subprocess.run(
            [
                uv,
                "pip",
                "install",
                *pip_pkgs,
                "--python",
                str(python_path),
            ],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if pkg_result.returncode == 0:
            created.append(f"pip install ({len(pip_pkgs)} packages)")
        else:
            _safe_echo(
                f"  Warning: pip install failed:\n"
                f"    {(pkg_result.stderr or '').strip()[:300]}",
            )

    typer.echo(f"\n  Next: {_activation_hint()}")
    typer.echo("  Then: runo doctor")
