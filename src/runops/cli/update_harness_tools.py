"""tools/runops update helpers for ``runo update-harness``."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_REEXEC_ENV_VAR = "RUNOPS_UPDATE_HARNESS_REEXEC"


def _find_uv() -> str:
    """Return the uv executable path, falling back to the bare name."""
    return shutil.which("uv") or "uv"


def _venv_python(project_dir: Path) -> Path | None:
    """Return the venv python path if it exists."""
    venv_dir = project_dir / ".venv"
    preferred = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    alternates = ("bin/python", "Scripts/python.exe")
    rel_candidates = [preferred, *(rel for rel in alternates if rel != preferred)]
    for python_rel in rel_candidates:
        python_path = venv_dir / python_rel
        if python_path.exists():
            return python_path
    return None


def _read_runops_version(pyproject_path: Path) -> str | None:
    """Return the version declared in ``pyproject.toml`` if available."""
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None

    project = data.get("project")
    if not isinstance(project, dict):
        return None

    version = project.get("version")
    if isinstance(version, str) and version:
        return version
    return None


def _direct_url_to_path(url: str) -> Path | None:
    """Convert a PEP 610 file URL to a local path when possible."""
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None

    raw_path = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc != "localhost":
        raw_path = f"//{parsed.netloc}{raw_path}"

    try:
        return Path(raw_path).resolve()
    except OSError:
        return Path(raw_path)


def _editable_install_needs_refresh(project_dir: Path) -> bool:
    """Return whether the venv's ``runops`` install should be refreshed.

    This catches the case where ``tools/runops`` was updated manually before
    ``runo update-harness`` runs: ``git pull`` reports "already up to date",
    but the virtualenv metadata still points to an older editable install.
    """
    runops_dir = project_dir / "tools" / "runops"
    pyproject_path = runops_dir / "pyproject.toml"
    if not pyproject_path.is_file():
        return False

    python_path = _venv_python(project_dir)
    if python_path is None:
        return False

    expected_version = _read_runops_version(pyproject_path)
    expected_path = runops_dir.resolve()
    probe = r"""
import json
from importlib import metadata

payload = {"installed": False}
try:
    dist = metadata.distribution("runops")
except metadata.PackageNotFoundError:
    print(json.dumps(payload))
    raise SystemExit(0)

payload["installed"] = True
payload["version"] = dist.version
direct_url = dist.read_text("direct_url.json")
if direct_url:
    try:
        data = json.loads(direct_url)
    except json.JSONDecodeError:
        data = {}
    payload["editable"] = bool(data.get("dir_info", {}).get("editable"))
    payload["url"] = data.get("url", "")
else:
    payload["editable"] = False
    payload["url"] = ""

print(json.dumps(payload))
"""
    result = subprocess.run(
        [str(python_path), "-c", probe],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return True

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return True
    if not isinstance(payload, dict):
        return True

    if payload.get("installed") is not True:
        return True
    if payload.get("editable") is not True:
        return True

    installed_url = payload.get("url")
    if not isinstance(installed_url, str):
        return True
    installed_path = _direct_url_to_path(installed_url)
    if installed_path != expected_path:
        return True

    installed_version = payload.get("version")
    return expected_version is not None and installed_version != expected_version


def _reinstall_editable(project_dir: Path) -> str | None:
    """Re-run ``uv pip install -e tools/runops`` to pick up new dependencies.

    Returns:
        Short status message, or ``None`` if the venv or tools/runops is missing.
    """
    runops_dir = project_dir / "tools" / "runops"
    if not (runops_dir / "pyproject.toml").is_file():
        return None

    python_path = _venv_python(project_dir)
    if python_path is None:
        return "skipped (no .venv)"

    uv = _find_uv()
    result = subprocess.run(
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
    if result.returncode == 0:
        return "editable install refreshed"
    return f"editable install failed: {(result.stderr or '').strip()[:200]}"


def _pull_tools_repo(project_dir: Path) -> str | None:
    """``git pull`` the ``tools/runops`` clone.

    Returns:
        Short status message, or ``None`` if the repo does not exist.
    """
    runops_dir = project_dir / "tools" / "runops"
    if not (runops_dir / ".git").is_dir():
        return None

    blocker = _tools_repo_update_blocker(runops_dir)
    if blocker is not None:
        return f"blocked: {blocker}"

    result = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=str(runops_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode == 0:
        stdout = (result.stdout or "").strip()
        if "Already up to date" in stdout:
            return "already up to date"
        return "updated"
    return f"pull failed: {(result.stderr or '').strip()[:200]}"


def _run_tools_git(
    runops_dir: Path, args: list[str]
) -> subprocess.CompletedProcess[str]:
    """Run a git command in ``tools/runops`` and return the completed process."""
    return subprocess.run(
        ["git", *args],
        cwd=str(runops_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _tools_repo_update_blocker(runops_dir: Path) -> str | None:
    """Return why ``tools/runops`` should not be pulled automatically."""
    status = _run_tools_git(runops_dir, ["status", "--porcelain"])
    if status.returncode != 0:
        detail = (status.stderr or status.stdout or "").strip()[:200]
        return f"could not inspect git status ({detail})"
    if status.stdout.strip():
        return (
            "local uncommitted changes exist; commit/stash them, use "
            "patch-runops, or rerun update-harness with --skip-pull to render "
            "the current local templates"
        )

    branch = _run_tools_git(runops_dir, ["branch", "--show-current"])
    if branch.returncode != 0:
        detail = (branch.stderr or branch.stdout or "").strip()[:200]
        return f"could not inspect current branch ({detail})"
    branch_name = branch.stdout.strip()
    if branch_name and branch_name != "main":
        return (
            f"current branch is {branch_name!r}; finish the local patch, open a "
            "feedback issue / draft PR, or switch back to main before pulling"
        )

    upstream = _run_tools_git(
        runops_dir,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
    )
    if upstream.returncode != 0:
        detail = (upstream.stderr or upstream.stdout or "").strip()[:200]
        return f"no upstream tracking branch is configured ({detail})"

    ahead = _run_tools_git(runops_dir, ["rev-list", "--count", "@{u}..HEAD"])
    if ahead.returncode != 0:
        detail = (ahead.stderr or ahead.stdout or "").strip()[:200]
        return f"could not inspect local commits ({detail})"
    try:
        ahead_count = int(ahead.stdout.strip() or "0")
    except ValueError:
        return f"could not parse local commit count ({ahead.stdout.strip()!r})"
    if ahead_count > 0:
        return (
            f"tools/runops has {ahead_count} local commit(s); push a PR, file a "
            "feedback issue, or rebase manually before pulling upstream"
        )

    return None


def _restart_with_skip_pull() -> None:
    """Re-exec ``update-harness`` so the pulled editable install is reloaded."""
    argv = [sys.executable, "-I", "-m", "runops.cli.main", *sys.argv[1:]]
    if "--skip-pull" not in argv[4:]:
        argv.append("--skip-pull")

    env = dict(os.environ)
    env[_REEXEC_ENV_VAR] = "1"
    os.execvpe(sys.executable, argv, env)
