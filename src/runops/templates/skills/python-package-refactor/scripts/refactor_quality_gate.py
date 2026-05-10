#!/usr/bin/env python3
"""Plan or run verification gates for a Python package refactor.

The gate stack is inferred from repository files and pyproject/setup config.
Only standard-library code is used here; external tools are invoked only when
configured and importable as `python -m <tool>`.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "build",
    "dist",
    "site-packages",
    "node_modules",
}
COMMON_NON_PACKAGE_DIRS = {"tests", "test", "docs", "doc", "examples", "example", "scripts", "tools", "ci", ".github"}
SINGLE_MODULE_EXCLUDE = {"setup.py", "conftest.py", "noxfile.py"}


@dataclass
class Gate:
    name: str
    command: list[str]
    reason: str
    default_run: bool = True
    heavy: bool = False
    requires_module: str | None = None
    requires_executable: str | None = None
    timeout_seconds: float | None = None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def load_pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    if not path.exists() or tomllib is None:
        return {}
    try:
        return tomllib.loads(read_text(path))
    except Exception as exc:
        return {"__parse_error__": str(exc)}


def is_excluded(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part in EXCLUDED_DIRS for part in parts)


def has_python_files(path: Path) -> bool:
    return any(p.suffix == ".py" and not is_excluded(p, path) for p in path.rglob("*.py"))


def discover_source_roots(root: Path) -> list[Path]:
    roots: list[Path] = []
    src = root / "src"
    if src.exists() and src.is_dir() and has_python_files(src):
        roots.append(src)
    for child in root.iterdir():
        if child.name in EXCLUDED_DIRS or child.name in COMMON_NON_PACKAGE_DIRS:
            continue
        if child.is_dir() and (child / "__init__.py").exists():
            roots.append(root)
            break
        if child.is_file() and child.suffix == ".py" and child.name not in SINGLE_MODULE_EXCLUDE:
            roots.append(root)
            break
    unique: list[Path] = []
    seen: set[Path] = set()
    for item in roots:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


def discover_top_level_modules(root: Path) -> list[str]:
    modules: set[str] = set()
    for source_root in discover_source_roots(root):
        for child in source_root.iterdir():
            if child.name.startswith(".") or child.name in EXCLUDED_DIRS:
                continue
            if source_root == root and child.name in COMMON_NON_PACKAGE_DIRS:
                continue
            if child.is_dir() and has_python_files(child):
                if source_root != root or (child / "__init__.py").exists():
                    modules.add(child.name)
            elif child.is_file() and child.suffix == ".py" and child.name not in SINGLE_MODULE_EXCLUDE:
                modules.add(child.stem)
    return sorted(modules)


def has_tests(root: Path, pyproject: dict[str, Any]) -> bool:
    if (root / "pytest.ini").exists() or (root / "tests").exists() or (root / "test").exists():
        return True
    tool = pyproject.get("tool") if isinstance(pyproject.get("tool"), dict) else {}
    if isinstance(tool, dict) and "pytest" in tool:
        return True
    for path in root.rglob("test_*.py"):
        if not is_excluded(path, root):
            return True
    for path in root.rglob("*_test.py"):
        if not is_excluded(path, root):
            return True
    return False


def module_available(module: str | None) -> bool:
    if not module:
        return True
    return importlib.util.find_spec(module) is not None


def command_text(command: list[str]) -> str:
    return " ".join(_quote(part) for part in command)


def _quote(part: str) -> str:
    if not part:
        return "''"
    if all(c.isalnum() or c in "@%_+=:,./-" for c in part):
        return part
    return "'" + part.replace("'", "'\\''") + "'"


def detect_gates(root: Path) -> list[Gate]:
    root = root.resolve()
    pyproject = load_pyproject(root)
    tool = pyproject.get("tool") if isinstance(pyproject.get("tool"), dict) else {}
    tool = tool if isinstance(tool, dict) else {}
    scripts_dir = Path(__file__).resolve().parent
    top_modules = discover_top_level_modules(root)
    gates: list[Gate] = []

    gates.append(
        Gate(
            name="inspect",
            command=[sys.executable, str(scripts_dir / "inspect_python_package.py"), "--root", str(root), "--format", "json", "--output", "/tmp/python-package-refactor-inspect.json"],
            reason="Static repository inspection and AST syntax parse without importing project code.",
            timeout_seconds=60,
        )
    )

    if top_modules:
        gates.append(
            Gate(
                name="api-snapshot",
                command=[sys.executable, str(scripts_dir / "api_surface_snapshot.py"), "snapshot", "--root", str(root), "--output", "/tmp/python-package-refactor-api-current.json", "--format", "json"],
                reason="Capture current static public API candidates after the refactor.",
                timeout_seconds=60,
            )
        )
        gates.append(
            Gate(
                name="import-smoke",
                command=[sys.executable, str(scripts_dir / "import_smoke.py"), "--root", str(root), "--format", "json", "--output", "/tmp/python-package-refactor-import-smoke.json"],
                reason="Verify top-level packages still import in isolated subprocesses. Skip manually if imports have unsafe side effects.",
                timeout_seconds=max(30, 12 * len(top_modules)),
            )
        )

    if has_tests(root, pyproject):
        gates.append(
            Gate(
                name="pytest",
                command=[sys.executable, "-m", "pytest"],
                reason="Run the repository test suite because tests or pytest configuration were detected.",
                requires_module="pytest",
                timeout_seconds=300,
            )
        )

    if "ruff" in tool or (root / "ruff.toml").exists() or (root / ".ruff.toml").exists():
        gates.append(
            Gate(
                name="ruff-check",
                command=["ruff", "check", "."],
                reason="Run configured Ruff lint checks.",
                requires_executable="ruff",
                timeout_seconds=180,
            )
        )

    if "mypy" in tool or (root / "mypy.ini").exists() or (root / ".mypy.ini").exists():
        targets = top_modules if top_modules else ["."]
        gates.append(
            Gate(
                name="mypy",
                command=["mypy", *targets],
                reason="Run configured mypy type checks on discovered top-level modules.",
                requires_executable="mypy",
                timeout_seconds=300,
            )
        )

    if "pyright" in tool or (root / "pyrightconfig.json").exists():
        gates.append(
            Gate(
                name="pyright",
                command=["pyright"],
                reason="Run configured pyright checks if the Python pyright wrapper is installed.",
                requires_executable="pyright",
                timeout_seconds=300,
            )
        )

    if (root / ".git").exists():
        gates.append(
            Gate(
                name="git-diff-check",
                command=["git", "diff", "--check"],
                reason="Catch whitespace errors and conflict markers in the current diff.",
                timeout_seconds=60,
            )
        )

    if (root / "tox.ini").exists() or "tox" in tool:
        gates.append(
            Gate(
                name="tox",
                command=[sys.executable, "-m", "tox"],
                reason="Run the tox matrix for release-level confidence.",
                default_run=False,
                heavy=True,
                requires_module="tox",
                timeout_seconds=1200,
            )
        )

    if (root / "noxfile.py").exists():
        gates.append(
            Gate(
                name="nox",
                command=[sys.executable, "-m", "nox"],
                reason="Run nox sessions for release-level confidence.",
                default_run=False,
                heavy=True,
                requires_module="nox",
                timeout_seconds=1200,
            )
        )

    if (root / "pyproject.toml").exists() or (root / "setup.py").exists() or (root / "setup.cfg").exists():
        gates.append(
            Gate(
                name="build",
                command=[sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", "/tmp/python-package-refactor-build"],
                reason="Validate package build metadata and included files. Useful after packaging changes.",
                default_run=False,
                heavy=True,
                requires_module="build",
                timeout_seconds=600,
            )
        )

    return gates


def render_plan(gates: list[Gate], include_heavy: bool = False) -> str:
    lines: list[str] = []
    lines.append("# Refactor quality gate plan")
    lines.append("")
    for gate in gates:
        selected = gate.default_run or (include_heavy and gate.heavy)
        badge = "default" if selected else "optional"
        if gate.heavy:
            badge += ", heavy"
        install = ""
        if gate.requires_module and not module_available(gate.requires_module):
            install = f" (will skip unless `{gate.requires_module}` is installed)"
        lines.append(f"## {gate.name} [{badge}]")
        lines.append(f"Reason: {gate.reason}{install}")
        lines.append("")
        lines.append("```bash")
        lines.append(command_text(gate.command))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def run_gate(root: Path, gate: Gate, timeout_override: float | None = None) -> dict[str, Any]:
    if gate.requires_executable and shutil.which(gate.requires_executable) is None:
        return {
            "name": gate.name,
            "status": "skipped",
            "reason": f"Executable '{gate.requires_executable}' is not available in PATH.",
            "command": command_text(gate.command),
        }
    if gate.requires_module and not module_available(gate.requires_module):
        return {
            "name": gate.name,
            "status": "skipped",
            "reason": f"Python module '{gate.requires_module}' is not installed in this environment.",
            "command": command_text(gate.command),
        }
    timeout = timeout_override if timeout_override is not None else gate.timeout_seconds
    started = time.monotonic()
    try:
        proc = subprocess.run(
            gate.command,
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        elapsed = time.monotonic() - started
        return {
            "name": gate.name,
            "status": "pass" if proc.returncode == 0 else "fail",
            "returncode": proc.returncode,
            "elapsed_seconds": round(elapsed, 3),
            "command": command_text(gate.command),
            "stdout_tail": "\n".join(proc.stdout.splitlines()[-80:]),
            "stderr_tail": "\n".join(proc.stderr.splitlines()[-80:]),
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        return {
            "name": gate.name,
            "status": "fail",
            "returncode": None,
            "elapsed_seconds": round(elapsed, 3),
            "command": command_text(gate.command),
            "stdout_tail": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr_tail": f"timeout after {timeout} seconds",
        }


def render_run_markdown(report: dict[str, Any]) -> str:
    results = report.get("results") or []
    failed = [r for r in results if r.get("status") == "fail"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    lines: list[str] = []
    lines.append("# Refactor quality gate run")
    lines.append("")
    lines.append(f"Root: `{report.get('root')}`")
    lines.append(f"Result: `{'FAIL' if failed else 'PASS'}`")
    lines.append(f"Gates: `{len(results)}` run/planned, `{len(failed)}` failed, `{len(skipped)}` skipped")
    lines.append("")
    for item in results:
        status = str(item.get("status", "unknown")).upper()
        lines.append(f"## {status}: {item.get('name')}")
        lines.append("")
        lines.append("```bash")
        lines.append(str(item.get("command") or ""))
        lines.append("```")
        if item.get("reason"):
            lines.append(f"Reason: {item['reason']}")
        if item.get("elapsed_seconds") is not None:
            lines.append(f"Elapsed: `{item['elapsed_seconds']}s`")
        if item.get("stdout_tail"):
            lines.append("")
            lines.append("stdout tail:")
            lines.append("```text")
            lines.append(str(item["stdout_tail"])[-4000:])
            lines.append("```")
        if item.get("stderr_tail"):
            lines.append("")
            lines.append("stderr tail:")
            lines.append("```text")
            lines.append(str(item["stderr_tail"])[-4000:])
            lines.append("```")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan or run Python package refactor verification gates.")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Print detected verification gates.")
    plan.add_argument("--root", default=".")
    plan.add_argument("--include-heavy", action="store_true")

    run = sub.add_parser("run", help="Run default verification gates.")
    run.add_argument("--root", default=".")
    run.add_argument("--include-heavy", action="store_true", help="Also run tox/nox/build gates when detected.")
    run.add_argument("--only", nargs="*", help="Run only these gate names.")
    run.add_argument("--skip", nargs="*", default=[], help="Skip these gate names.")
    run.add_argument("--timeout", type=float, help="Override timeout per gate in seconds.")
    run.add_argument("--format", choices=["markdown", "json"], default="markdown")
    run.add_argument("--output")
    run.add_argument("--allow-fail", action="store_true", help="Return exit code 0 even if gates fail.")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.exists():
        print(f"error: root does not exist: {root}", file=sys.stderr)
        return 2
    gates = detect_gates(root)

    if args.command == "plan":
        print(render_plan(gates, include_heavy=args.include_heavy))
        return 0

    only = set(args.only or [])
    skip = set(args.skip or [])
    selected: list[Gate] = []
    for gate in gates:
        if only and gate.name not in only:
            continue
        if gate.name in skip:
            continue
        if gate.default_run or (args.include_heavy and gate.heavy) or only:
            selected.append(gate)

    results = [run_gate(root, gate, timeout_override=args.timeout) for gate in selected]
    report = {"root": str(root), "results": results}
    text = json.dumps(report, indent=2, sort_keys=True) if args.format == "json" else render_run_markdown(report)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    failed = any(item.get("status") == "fail" for item in results)
    return 1 if failed and not args.allow_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
