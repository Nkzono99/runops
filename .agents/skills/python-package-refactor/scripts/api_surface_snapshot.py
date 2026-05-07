#!/usr/bin/env python3
"""Create and compare a static public API surface snapshot for a Python package.

This script parses source files with ast and never imports the project.
"""
from __future__ import annotations

import argparse
import ast
import configparser
import json
import sys
from pathlib import Path
from typing import Any, Iterable

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


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


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


def top_level_names(root: Path, source_roots: list[Path]) -> set[str]:
    names: set[str] = set()
    for source_root in source_roots:
        for child in source_root.iterdir():
            if child.name.startswith(".") or child.name in EXCLUDED_DIRS:
                continue
            if source_root == root and child.name in COMMON_NON_PACKAGE_DIRS:
                continue
            if child.is_dir() and has_python_files(child):
                if source_root != root or (child / "__init__.py").exists():
                    names.add(child.name)
            elif child.is_file() and child.suffix == ".py" and child.name not in SINGLE_MODULE_EXCLUDE:
                names.add(child.stem)
    return names


def module_name_for(path: Path, root: Path, source_roots: list[Path]) -> str | None:
    for source_root in source_roots:
        try:
            relative = path.relative_to(source_root)
        except ValueError:
            continue
        if relative.parts and source_root == root and relative.parts[0] in COMMON_NON_PACKAGE_DIRS:
            return None
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            return None
        return ".".join(parts)
    return None


def iter_source_py_files(root: Path, source_roots: list[Path], top_levels: set[str]) -> Iterable[Path]:
    for source_root in source_roots:
        for path in source_root.rglob("*.py"):
            if is_excluded(path, root):
                continue
            try:
                relative = path.relative_to(source_root)
            except ValueError:
                continue
            if not relative.parts:
                continue
            first = relative.parts[0]
            if first in top_levels or (len(relative.parts) == 1 and path.stem in top_levels):
                yield path


def literal_str_list(node: ast.AST) -> list[str] | None:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values: list[str] = []
    for item in node.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            values.append(item.value)
        else:
            return None
    return values


def public_assignment_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name) and not target.id.startswith("_"):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(public_assignment_names(elt))
        return names
    return []


def parse_module(path: Path, root: Path, source_roots: list[Path]) -> dict[str, Any]:
    module = module_name_for(path, root, source_roots)
    text = read_text(path)
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return {
            "path": rel(path, root),
            "module": module,
            "syntax_error": f"{exc.msg} at line {exc.lineno}",
            "public_defs": [],
            "dunder_all": None,
            "reexports": [],
        }

    public_defs: set[str] = set()
    reexports: list[dict[str, str | None]] = []
    dunder_all: list[str] | None = None

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                public_defs.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".", 1)[0]
                if not name.startswith("_"):
                    public_defs.add(name)
                    reexports.append({"name": name, "source": alias.name})
        elif isinstance(node, ast.ImportFrom):
            source = "." * node.level + (node.module or "")
            for alias in node.names:
                name = alias.asname or alias.name
                if name != "*" and not name.startswith("_"):
                    public_defs.add(name)
                    reexports.append({"name": name, "source": source or None})
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    parsed = literal_str_list(node.value)
                    if parsed is not None:
                        dunder_all = parsed
                else:
                    for name in public_assignment_names(target):
                        public_defs.add(name)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "__all__" and node.value is not None:
                parsed = literal_str_list(node.value)
                if parsed is not None:
                    dunder_all = parsed
            else:
                for name in public_assignment_names(node.target):
                    public_defs.add(name)

    return {
        "path": rel(path, root),
        "module": module,
        "syntax_error": None,
        "public_defs": sorted(public_defs),
        "dunder_all": sorted(dunder_all) if dunder_all is not None else None,
        "reexports": sorted(reexports, key=lambda x: (x.get("name") or "", x.get("source") or "")),
    }


def load_pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    if not path.exists() or tomllib is None:
        return {}
    try:
        return tomllib.loads(read_text(path))
    except Exception as exc:
        return {"__parse_error__": str(exc)}


def parse_setup_cfg_entry_points(root: Path) -> dict[str, dict[str, str]]:
    path = root / "setup.cfg"
    if not path.exists():
        return {}
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except Exception:
        return {}
    result: dict[str, dict[str, str]] = {}
    if parser.has_section("options.entry_points"):
        for group, value in parser.items("options.entry_points"):
            entries: dict[str, str] = {}
            for line in value.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, target = line.split("=", 1)
                entries[name.strip()] = target.strip()
            if entries:
                result[group] = entries
    return result


def entry_points(root: Path, pyproject: dict[str, Any]) -> dict[str, Any]:
    project = pyproject.get("project") or {}
    result: dict[str, Any] = {}
    if isinstance(project, dict):
        for key in ("scripts", "gui-scripts", "entry-points"):
            value = project.get(key)
            if isinstance(value, dict):
                result[f"project.{key}"] = value
    setup_cfg = parse_setup_cfg_entry_points(root)
    if setup_cfg:
        result["setup.cfg:options.entry_points"] = setup_cfg
    return result


def create_snapshot(root: Path) -> dict[str, Any]:
    root = root.resolve()
    pyproject = load_pyproject(root)
    source_roots = discover_source_roots(root)
    top_levels = top_level_names(root, source_roots)
    modules: dict[str, Any] = {}
    syntax_errors: list[dict[str, str | None]] = []
    for path in sorted(set(iter_source_py_files(root, source_roots, top_levels))):
        parsed = parse_module(path, root, source_roots)
        module = parsed.get("module")
        if not module:
            continue
        modules[module] = parsed
        if parsed.get("syntax_error"):
            syntax_errors.append({"module": module, "path": parsed.get("path"), "error": parsed.get("syntax_error")})
    return {
        "schema": "python-package-refactor.api-surface.v1",
        "root": str(root),
        "source_roots": [rel(p, root) for p in source_roots],
        "top_level_names": sorted(top_levels),
        "entry_points": entry_points(root, pyproject),
        "modules": dict(sorted(modules.items())),
        "syntax_errors": syntax_errors,
    }


def exported_names(module_data: dict[str, Any]) -> set[str]:
    dunder_all = module_data.get("dunder_all")
    if dunder_all is not None:
        return set(dunder_all)
    return set(module_data.get("public_defs") or [])


def flatten_entry_points(data: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(f"{prefix}.{key}" if prefix else str(key), nested)
        else:
            flat[prefix] = value
    walk("", data.get("entry_points") or {})
    return flat


def compare_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_modules = before.get("modules") or {}
    after_modules = after.get("modules") or {}
    removed_modules = sorted(set(before_modules) - set(after_modules))
    added_modules = sorted(set(after_modules) - set(before_modules))
    common_modules = sorted(set(before_modules) & set(after_modules))

    symbol_changes: dict[str, Any] = {}
    for module in common_modules:
        before_symbols = exported_names(before_modules[module])
        after_symbols = exported_names(after_modules[module])
        removed = sorted(before_symbols - after_symbols)
        added = sorted(after_symbols - before_symbols)
        before_all = before_modules[module].get("dunder_all")
        after_all = after_modules[module].get("dunder_all")
        all_changed = before_all != after_all
        if removed or added or all_changed:
            symbol_changes[module] = {
                "path_before": before_modules[module].get("path"),
                "path_after": after_modules[module].get("path"),
                "removed_symbols": removed,
                "added_symbols": added,
                "dunder_all_before": before_all,
                "dunder_all_after": after_all,
            }

    before_ep = flatten_entry_points(before)
    after_ep = flatten_entry_points(after)
    removed_entry_points = sorted(set(before_ep) - set(after_ep))
    added_entry_points = sorted(set(after_ep) - set(before_ep))
    changed_entry_points = sorted(k for k in set(before_ep) & set(after_ep) if before_ep[k] != after_ep[k])

    potential_breaks = bool(
        removed_modules
        or removed_entry_points
        or changed_entry_points
        or any(change["removed_symbols"] for change in symbol_changes.values())
    )
    return {
        "schema": "python-package-refactor.api-surface-comparison.v1",
        "potential_breaks": potential_breaks,
        "removed_modules": removed_modules,
        "added_modules": added_modules,
        "symbol_changes": symbol_changes,
        "entry_point_changes": {
            "removed": removed_entry_points,
            "added": added_entry_points,
            "changed": {key: {"before": before_ep[key], "after": after_ep[key]} for key in changed_entry_points},
        },
        "syntax_errors_before": before.get("syntax_errors") or [],
        "syntax_errors_after": after.get("syntax_errors") or [],
    }


def render_comparison_markdown(comparison: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# API surface comparison")
    lines.append("")
    lines.append(f"Potential breaking changes: `{'yes' if comparison['potential_breaks'] else 'no'}`")
    lines.append("")

    if comparison.get("removed_modules"):
        lines.append("## Removed modules")
        lines.append("")
        for module in comparison["removed_modules"]:
            lines.append(f"- `{module}`")
        lines.append("")

    symbol_changes = comparison.get("symbol_changes") or {}
    removed_any = {m: c for m, c in symbol_changes.items() if c.get("removed_symbols")}
    if removed_any:
        lines.append("## Removed public symbols")
        lines.append("")
        for module, change in removed_any.items():
            lines.append(f"- `{module}`: {', '.join('`' + s + '`' for s in change['removed_symbols'])}")
        lines.append("")

    changed_ep = comparison.get("entry_point_changes") or {}
    if changed_ep.get("removed") or changed_ep.get("changed"):
        lines.append("## Entry point risks")
        lines.append("")
        for name in changed_ep.get("removed") or []:
            lines.append(f"- removed `{name}`")
        for name, value in (changed_ep.get("changed") or {}).items():
            lines.append(f"- changed `{name}`: `{value['before']}` -> `{value['after']}`")
        lines.append("")

    additions = []
    if comparison.get("added_modules"):
        additions.append(f"added modules: {', '.join('`' + m + '`' for m in comparison['added_modules'][:20])}")
    added_symbols = {m: c for m, c in symbol_changes.items() if c.get("added_symbols")}
    if added_symbols:
        additions.append(f"modules with added symbols: {', '.join('`' + m + '`' for m in list(added_symbols)[:20])}")
    if changed_ep.get("added"):
        additions.append(f"added entry points: {', '.join('`' + e + '`' for e in changed_ep['added'][:20])}")
    if additions:
        lines.append("## Additions")
        lines.append("")
        for item in additions:
            lines.append(f"- {item}")
        lines.append("")

    if comparison.get("syntax_errors_after"):
        lines.append("## Syntax errors after")
        lines.append("")
        for item in comparison["syntax_errors_after"]:
            lines.append(f"- `{item.get('path')}`: {item.get('error')}")
        lines.append("")

    if not comparison["potential_breaks"] and not comparison.get("syntax_errors_after"):
        lines.append("No potential public API removals, entry point regressions, or static syntax errors were detected.")
    else:
        lines.append("Review every listed change against the intended compatibility policy before signing off.")
    lines.append("")
    return "\n".join(lines)


def write_output(data: Any, fmt: str, output: str | None, markdown_renderer=None) -> None:
    if fmt == "json":
        text = json.dumps(data, indent=2, sort_keys=True)
    else:
        if markdown_renderer is None:
            raise ValueError("markdown renderer is required")
        text = markdown_renderer(data)
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def render_snapshot_markdown(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# API surface snapshot")
    lines.append("")
    lines.append(f"Root: `{snapshot['root']}`")
    lines.append(f"Source roots: `{', '.join(snapshot.get('source_roots') or []) or 'none detected'}`")
    lines.append(f"Top-level names: `{', '.join(snapshot.get('top_level_names') or []) or 'none detected'}`")
    lines.append(f"Modules: `{len(snapshot.get('modules') or {})}`")
    lines.append(f"Entry point groups: `{len(snapshot.get('entry_points') or {})}`")
    lines.append(f"Syntax errors: `{len(snapshot.get('syntax_errors') or [])}`")
    lines.append("")
    modules = snapshot.get("modules") or {}
    for module, data in list(modules.items())[:80]:
        symbols = sorted(exported_names(data))
        lines.append(f"- `{module}` ({data.get('path')}): {', '.join(symbols[:30]) or 'no public symbols detected'}")
    if len(modules) > 80:
        lines.append(f"- ... {len(modules) - 80} more modules omitted from markdown output")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot or compare Python package public API surface statically.")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="Create an API surface snapshot.")
    snap.add_argument("--root", default=".")
    snap.add_argument("--output", help="Output JSON file. If omitted, prints markdown unless --format json is set.")
    snap.add_argument("--format", choices=["json", "markdown"], default="json")

    comp = sub.add_parser("compare", help="Compare two API surface snapshot JSON files.")
    comp.add_argument("before")
    comp.add_argument("after")
    comp.add_argument("--format", choices=["markdown", "json"], default="markdown")
    comp.add_argument("--output")
    comp.add_argument("--no-fail", action="store_true", help="Return exit code 0 even when potential breaks are detected.")

    args = parser.parse_args(argv)
    if args.command == "snapshot":
        snapshot = create_snapshot(Path(args.root))
        write_output(snapshot, args.format, args.output, render_snapshot_markdown)
        return 1 if snapshot.get("syntax_errors") else 0

    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    comparison = compare_snapshots(before, after)
    write_output(comparison, args.format, args.output, render_comparison_markdown)
    if comparison["potential_breaks"] and not args.no_fail:
        return 1
    if comparison.get("syntax_errors_after") and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
