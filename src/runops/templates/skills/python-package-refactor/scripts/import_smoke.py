#!/usr/bin/env python3
"""Smoke-test imports for top-level Python package names.

This command imports each module in a fresh subprocess with the repository root
and src/ on PYTHONPATH. It can trigger import-time side effects from the target
project, so use it only when imports are expected to be safe.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

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


def run_import(root: Path, module: str, timeout: float) -> dict[str, object]:
    env = os.environ.copy()
    pythonpath_items = [str(root / "src"), str(root)]
    existing = env.get("PYTHONPATH")
    if existing:
        pythonpath_items.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_items)
    code = "import importlib, sys; importlib.import_module(sys.argv[1]); print('import ok:', sys.argv[1])"
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, module],
            cwd=str(root),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        elapsed = time.monotonic() - started
        return {
            "module": module,
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "elapsed_seconds": round(elapsed, 3),
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        return {
            "module": module,
            "ok": False,
            "returncode": None,
            "elapsed_seconds": round(elapsed, 3),
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": f"timeout after {timeout} seconds",
        }


def render_markdown(report: dict[str, object]) -> str:
    results = report.get("results") or []
    failures = [item for item in results if not item.get("ok")]
    lines: list[str] = []
    lines.append("# Import smoke report")
    lines.append("")
    lines.append(f"Root: `{report.get('root')}`")
    lines.append(f"Modules: `{len(results)}`")
    lines.append(f"Failures: `{len(failures)}`")
    lines.append("")
    for item in results:
        status = "PASS" if item.get("ok") else "FAIL"
        lines.append(f"- {status} `{item.get('module')}` ({item.get('elapsed_seconds')}s)")
        if not item.get("ok"):
            stderr = str(item.get("stderr") or "").splitlines()
            for line in stderr[-8:]:
                lines.append(f"  - {line}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run top-level import smoke tests in subprocesses.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--modules", nargs="*", help="Explicit module names. Defaults to auto-discovered top-level packages/modules.")
    parser.add_argument("--skip", nargs="*", default=[], help="Module names to skip.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-module timeout in seconds.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output")
    parser.add_argument("--allow-fail", action="store_true", help="Return exit code 0 even if imports fail.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    modules = args.modules if args.modules else discover_top_level_modules(root)
    skip = set(args.skip or [])
    modules = [m for m in modules if m not in skip]
    results = [run_import(root, module, args.timeout) for module in modules]
    report: dict[str, object] = {"root": str(root), "results": results}
    text = json.dumps(report, indent=2, sort_keys=True) if args.format == "json" else render_markdown(report)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    failed = any(not item.get("ok") for item in results)
    return 1 if failed and not args.allow_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
