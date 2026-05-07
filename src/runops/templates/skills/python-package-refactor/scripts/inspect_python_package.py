#!/usr/bin/env python3
"""Inspect a Python package repository before a refactor.

The script intentionally uses only the standard library. It does not import the
project under inspection, so it is suitable for packages with import-time side
effects.
"""
from __future__ import annotations

import argparse
import ast
import configparser
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

try:  # Python 3.11+
    import tomllib  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - Python < 3.11 fallback if tomli exists
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
COMMON_NON_PACKAGE_DIRS = {
    "tests",
    "test",
    "docs",
    "doc",
    "examples",
    "example",
    "scripts",
    "tools",
    "ci",
    ".github",
}
SINGLE_MODULE_EXCLUDE = {"setup.py", "conftest.py", "noxfile.py"}


@dataclass
class PackageCandidate:
    name: str
    path: str
    source_root: str
    kind: str  # package | namespace-package | module


@dataclass
class FileSummary:
    path: str
    module: str | None
    lines: int
    classes: int
    functions: int
    async_functions: int
    imports: list[str]
    from_imports: list[dict[str, Any]]
    public_defs: list[str]
    dunder_all: list[str] | None
    syntax_error: str | None


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def is_excluded(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part in EXCLUDED_DIRS for part in parts)


def iter_py_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if not is_excluded(path, root):
            yield path


def has_python_files(path: Path) -> bool:
    return any(p.suffix == ".py" and not is_excluded(p, path) for p in path.rglob("*.py"))


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


def load_ini(path: Path) -> configparser.ConfigParser | None:
    if not path.exists():
        return None
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except Exception:
        return None
    return parser


def discover_source_roots(root: Path) -> list[Path]:
    roots: list[Path] = []
    src = root / "src"
    if src.exists() and src.is_dir() and has_python_files(src):
        roots.append(src)

    # Include the repository root when it contains flat-layout packages/modules.
    for child in root.iterdir():
        if child.name in EXCLUDED_DIRS or child.name in COMMON_NON_PACKAGE_DIRS:
            continue
        if child.is_dir() and (child / "__init__.py").exists():
            roots.append(root)
            break
        if child.is_file() and child.suffix == ".py" and child.name not in SINGLE_MODULE_EXCLUDE:
            roots.append(root)
            break

    # De-duplicate while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for item in roots:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


def discover_packages(root: Path, source_roots: list[Path]) -> list[PackageCandidate]:
    candidates: list[PackageCandidate] = []
    for source_root in source_roots:
        for child in sorted(source_root.iterdir(), key=lambda p: p.name):
            if child.name.startswith(".") or child.name in EXCLUDED_DIRS:
                continue
            if source_root == root and child.name in COMMON_NON_PACKAGE_DIRS:
                continue
            if child.is_dir() and has_python_files(child):
                kind = "package" if (child / "__init__.py").exists() else "namespace-package"
                # In a flat layout, be conservative with namespace package guesses.
                if source_root == root and kind == "namespace-package":
                    continue
                candidates.append(
                    PackageCandidate(
                        name=child.name,
                        path=rel(child, root),
                        source_root=rel(source_root, root),
                        kind=kind,
                    )
                )
            elif child.is_file() and child.suffix == ".py" and child.name not in SINGLE_MODULE_EXCLUDE:
                candidates.append(
                    PackageCandidate(
                        name=child.stem,
                        path=rel(child, root),
                        source_root=rel(source_root, root),
                        kind="module",
                    )
                )
    return candidates


def module_name_for(path: Path, root: Path, source_roots: list[Path]) -> str | None:
    for source_root in source_roots:
        try:
            relative = path.relative_to(source_root)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] in COMMON_NON_PACKAGE_DIRS and source_root == root:
            return None
        parts = list(relative.with_suffix("").parts)
        if not parts:
            return None
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            return None
        return ".".join(parts)
    return None


def literal_dunder_all(node: ast.AST) -> list[str] | None:
    if isinstance(node, (ast.List, ast.Tuple)):
        values: list[str] = []
        for item in node.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                values.append(item.value)
            else:
                return None
        return values
    return None


def summarize_py_file(path: Path, root: Path, source_roots: list[Path]) -> FileSummary:
    text = read_text(path)
    lines = text.count("\n") + (1 if text else 0)
    module = module_name_for(path, root, source_roots)
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return FileSummary(
            path=rel(path, root),
            module=module,
            lines=lines,
            classes=0,
            functions=0,
            async_functions=0,
            imports=[],
            from_imports=[],
            public_defs=[],
            dunder_all=None,
            syntax_error=f"{exc.msg} at line {exc.lineno}",
        )

    classes = functions = async_functions = 0
    imports: list[str] = []
    from_imports: list[dict[str, Any]] = []
    public_defs: list[str] = []
    dunder_all: list[str] | None = None

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes += 1
            if not node.name.startswith("_"):
                public_defs.append(node.name)
        elif isinstance(node, ast.FunctionDef):
            functions += 1
            if not node.name.startswith("_"):
                public_defs.append(node.name)
        elif isinstance(node, ast.AsyncFunctionDef):
            async_functions += 1
            if not node.name.startswith("_"):
                public_defs.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                public_name = alias.asname or alias.name.split(".", 1)[0]
                if not public_name.startswith("_"):
                    public_defs.append(public_name)
        elif isinstance(node, ast.ImportFrom):
            names = [alias.asname or alias.name for alias in node.names]
            from_imports.append({"module": node.module, "level": node.level, "names": names})
            for name in names:
                if name != "*" and not name.startswith("_"):
                    public_defs.append(name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets: list[ast.AST]
            value: ast.AST | None
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
                value = node.value
            else:
                targets = [node.target]
                value = node.value
            for target in targets:
                if isinstance(target, ast.Name):
                    if target.id == "__all__" and value is not None:
                        parsed = literal_dunder_all(value)
                        if parsed is not None:
                            dunder_all = parsed
                    elif not target.id.startswith("_"):
                        public_defs.append(target.id)

    return FileSummary(
        path=rel(path, root),
        module=module,
        lines=lines,
        classes=classes,
        functions=functions,
        async_functions=async_functions,
        imports=sorted(set(imports)),
        from_imports=from_imports,
        public_defs=sorted(set(public_defs)),
        dunder_all=dunder_all,
        syntax_error=None,
    )


def imported_candidates(summary: FileSummary) -> set[str]:
    names = set(summary.imports)
    current = summary.module or ""
    current_package = current.rsplit(".", 1)[0] if "." in current else current
    for item in summary.from_imports:
        module = item.get("module")
        level = int(item.get("level") or 0)
        if level == 0:
            if module:
                names.add(module)
            continue
        # Approximate relative import resolution.
        package_parts = current_package.split(".") if current_package else []
        if level > 1:
            package_parts = package_parts[: max(0, len(package_parts) - (level - 1))]
        base = ".".join(part for part in package_parts if part)
        if module:
            names.add(".".join(part for part in [base, module] if part))
        else:
            for imported_name in item.get("names", []):
                if imported_name != "*":
                    names.add(".".join(part for part in [base, imported_name] if part))
    return names


def best_local_target(import_name: str, modules: set[str], package_names: set[str]) -> str | None:
    if not import_name:
        return None
    first = import_name.split(".", 1)[0]
    if first not in package_names:
        return None
    parts = import_name.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in modules:
            return candidate
    return first if first in modules else None


def build_import_graph(summaries: list[FileSummary], package_names: set[str]) -> dict[str, list[str]]:
    modules = {s.module for s in summaries if s.module}
    graph: dict[str, set[str]] = {m: set() for m in modules if m}
    for summary in summaries:
        if not summary.module:
            continue
        for imported in imported_candidates(summary):
            target = best_local_target(imported, modules, package_names)
            if target and target != summary.module:
                graph[summary.module].add(target)
    return {key: sorted(value) for key, value in sorted(graph.items()) if value}


def strongly_connected_components(graph: dict[str, list[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    result: list[list[str]] = []

    nodes = set(graph)
    for deps in graph.values():
        nodes.update(deps)

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for dep in graph.get(node, []):
            if dep not in indices:
                visit(dep)
                lowlinks[node] = min(lowlinks[node], lowlinks[dep])
            elif dep in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[dep])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                current = stack.pop()
                on_stack.remove(current)
                component.append(current)
                if current == node:
                    break
            if len(component) > 1:
                result.append(sorted(component))

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return sorted(result, key=lambda x: (len(x), x))


def detect_tooling(root: Path, pyproject: dict[str, Any]) -> dict[str, Any]:
    files = sorted(
        p.name
        for p in root.iterdir()
        if p.is_file()
        and p.name
        in {
            "pyproject.toml",
            "setup.cfg",
            "setup.py",
            "requirements.txt",
            "requirements-dev.txt",
            "tox.ini",
            "noxfile.py",
            "pytest.ini",
            "mypy.ini",
            ".pre-commit-config.yaml",
            "uv.lock",
            "poetry.lock",
            "pdm.lock",
            "hatch.toml",
            "MANIFEST.in",
        }
    )
    tool_config = sorted((pyproject.get("tool") or {}).keys()) if isinstance(pyproject.get("tool"), dict) else []
    build_backend = None
    project_name = None
    requires_python = None
    dependencies_count = None
    optional_dependency_groups: list[str] = []
    if pyproject:
        build_backend = ((pyproject.get("build-system") or {}).get("build-backend"))
        project = pyproject.get("project") or {}
        if isinstance(project, dict):
            project_name = project.get("name")
            requires_python = project.get("requires-python")
            deps = project.get("dependencies")
            dependencies_count = len(deps) if isinstance(deps, list) else None
            optional = project.get("optional-dependencies")
            optional_dependency_groups = sorted(optional.keys()) if isinstance(optional, dict) else []
    setup_cfg = load_ini(root / "setup.cfg")
    setup_cfg_sections = sorted(setup_cfg.sections()) if setup_cfg else []
    return {
        "files": files,
        "pyproject_parse_error": pyproject.get("__parse_error__") if pyproject else None,
        "project_name": project_name,
        "requires_python": requires_python,
        "build_backend": build_backend,
        "dependencies_count": dependencies_count,
        "optional_dependency_groups": optional_dependency_groups,
        "tool_config": tool_config,
        "setup_cfg_sections": setup_cfg_sections,
    }


def find_tests(root: Path) -> dict[str, Any]:
    test_dirs = [rel(p, root) for p in root.iterdir() if p.is_dir() and p.name in {"tests", "test"}]
    test_files = [p for p in iter_py_files(root) if p.name.startswith("test_") or p.name.endswith("_test.py")]
    return {
        "test_dirs": sorted(test_dirs),
        "test_file_count": len(test_files),
        "sample_test_files": [rel(p, root) for p in sorted(test_files)[:20]],
    }


def hotspot_report(summaries: list[FileSummary]) -> list[dict[str, Any]]:
    hotspots: list[dict[str, Any]] = []
    for s in summaries:
        reasons: list[str] = []
        if s.syntax_error:
            reasons.append(f"syntax error: {s.syntax_error}")
        if s.lines >= 500:
            reasons.append(f"large file: {s.lines} lines")
        if s.functions + s.async_functions >= 25:
            reasons.append(f"many top-level functions: {s.functions + s.async_functions}")
        if s.classes >= 12:
            reasons.append(f"many top-level classes: {s.classes}")
        import_count = len(s.imports) + len(s.from_imports)
        if import_count >= 35:
            reasons.append(f"many imports: {import_count}")
        if s.path.endswith("__init__.py") and (s.lines >= 80 or import_count >= 20):
            reasons.append("heavy package __init__.py")
        if reasons:
            hotspots.append({"path": s.path, "module": s.module, "reasons": reasons})
    return hotspots


def api_signal_report(summaries: list[FileSummary]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for s in summaries:
        if s.dunder_all is not None or s.path.endswith("__init__.py"):
            signals.append(
                {
                    "path": s.path,
                    "module": s.module,
                    "dunder_all": s.dunder_all,
                    "public_defs": s.public_defs[:80],
                }
            )
    return signals


def inspect(root: Path, max_files: int | None = None) -> dict[str, Any]:
    root = root.resolve()
    pyproject = load_pyproject(root)
    source_roots = discover_source_roots(root)
    packages = discover_packages(root, source_roots)
    py_files = sorted(iter_py_files(root))
    if max_files is not None:
        py_files = py_files[:max_files]
    summaries = [summarize_py_file(path, root, source_roots) for path in py_files]
    package_names = {p.name for p in packages}
    graph = build_import_graph(summaries, package_names)
    cycles = strongly_connected_components(graph)
    syntax_errors = [s for s in summaries if s.syntax_error]
    return {
        "root": str(root),
        "tooling": detect_tooling(root, pyproject),
        "source_roots": [rel(p, root) for p in source_roots],
        "packages": [asdict(p) for p in packages],
        "tests": find_tests(root),
        "counts": {
            "python_files": len(py_files),
            "modules_mapped": len([s for s in summaries if s.module]),
            "syntax_errors": len(syntax_errors),
            "total_lines": sum(s.lines for s in summaries),
            "top_level_classes": sum(s.classes for s in summaries),
            "top_level_functions": sum(s.functions + s.async_functions for s in summaries),
        },
        "syntax_errors": [{"path": s.path, "error": s.syntax_error} for s in syntax_errors],
        "hotspots": hotspot_report(summaries),
        "api_signals": api_signal_report(summaries),
        "import_graph_edges": sum(len(v) for v in graph.values()),
        "import_cycles": cycles,
        "local_import_graph": graph,
        "files": [asdict(s) for s in summaries],
    }


def md_list(items: list[str], empty: str = "none detected") -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)


def render_markdown(data: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Python package inspection")
    lines.append("")
    lines.append(f"Root: `{data['root']}`")
    lines.append("")

    tooling = data["tooling"]
    lines.append("## Packaging and tooling")
    lines.append("")
    lines.append(f"- Project name: `{tooling.get('project_name') or 'unknown'}`")
    lines.append(f"- Requires Python: `{tooling.get('requires_python') or 'unknown'}`")
    lines.append(f"- Build backend: `{tooling.get('build_backend') or 'unknown'}`")
    deps = tooling.get("dependencies_count")
    lines.append(f"- Runtime dependencies in pyproject: `{deps if deps is not None else 'unknown'}`")
    lines.append(f"- Config files: `{', '.join(tooling.get('files') or []) or 'none detected'}`")
    lines.append(f"- pyproject tool sections: `{', '.join(tooling.get('tool_config') or []) or 'none detected'}`")
    if tooling.get("pyproject_parse_error"):
        lines.append(f"- pyproject parse error: `{tooling['pyproject_parse_error']}`")
    lines.append("")

    lines.append("## Source layout")
    lines.append("")
    lines.append("Source roots:")
    lines.append(md_list(data.get("source_roots", [])))
    lines.append("")
    lines.append("Package candidates:")
    packages = data.get("packages", [])
    if packages:
        for pkg in packages:
            lines.append(f"- `{pkg['name']}` ({pkg['kind']}) at `{pkg['path']}`; source root `{pkg['source_root']}`")
    else:
        lines.append("- none detected")
    lines.append("")

    counts = data["counts"]
    lines.append("## Code inventory")
    lines.append("")
    for key, value in counts.items():
        lines.append(f"- {key.replace('_', ' ').title()}: `{value}`")
    lines.append("")

    tests = data["tests"]
    lines.append("## Tests")
    lines.append("")
    lines.append(f"- Test directories: `{', '.join(tests.get('test_dirs') or []) or 'none detected'}`")
    lines.append(f"- Test file count: `{tests.get('test_file_count')}`")
    sample_tests = tests.get("sample_test_files") or []
    if sample_tests:
        lines.append("- Sample test files:")
        for path in sample_tests[:10]:
            lines.append(f"  - `{path}`")
    lines.append("")

    lines.append("## Hotspots")
    lines.append("")
    hotspots = data.get("hotspots", [])
    if hotspots:
        for item in hotspots[:30]:
            lines.append(f"- `{item['path']}`: {', '.join(item['reasons'])}")
    else:
        lines.append("- none detected by static heuristics")
    lines.append("")

    lines.append("## API signals")
    lines.append("")
    signals = data.get("api_signals", [])
    if signals:
        for item in signals[:30]:
            dunder = item.get("dunder_all")
            if dunder is not None:
                lines.append(f"- `{item['path']}` exports `__all__`: {', '.join(dunder) or '(empty)' }")
            else:
                public_defs = item.get("public_defs") or []
                lines.append(f"- `{item['path']}` public/re-export candidates: {', '.join(public_defs[:20]) or 'none detected'}")
    else:
        lines.append("- none detected")
    lines.append("")

    lines.append("## Import graph")
    lines.append("")
    lines.append(f"- Local import edges: `{data.get('import_graph_edges', 0)}`")
    cycles = data.get("import_cycles") or []
    if cycles:
        lines.append("- Potential cycles:")
        for cycle in cycles[:20]:
            lines.append(f"  - {' -> '.join(cycle)}")
    else:
        lines.append("- Potential cycles: none detected by static approximation")
    lines.append("")

    lines.append("## Suggested next step")
    lines.append("")
    if data.get("syntax_errors"):
        lines.append("Fix syntax errors before refactoring; AST-based safety checks are incomplete until parsing succeeds.")
    elif not packages:
        lines.append("Confirm the package root manually; automatic discovery did not find a clear package candidate.")
    elif not tests.get("test_file_count"):
        lines.append("Add characterization tests or import/API snapshots before changing internals; no test files were detected.")
    elif cycles:
        lines.append("Start with the smallest cycle-breaking refactor and verify with import smoke plus targeted tests.")
    elif hotspots:
        lines.append("Pick one hotspot and extract cohesive private helpers while preserving public imports.")
    else:
        lines.append("Proceed with a small scoped refactor and capture an API snapshot before editing.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Python package structure before refactoring.")
    parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Optional output file. Defaults to stdout.")
    parser.add_argument("--max-files", type=int, help="Limit parsed Python files for very large repositories.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"error: root does not exist: {root}", file=sys.stderr)
        return 2
    data = inspect(root, max_files=args.max_files)
    output = json.dumps(data, indent=2, sort_keys=True) if args.format == "json" else render_markdown(data)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
