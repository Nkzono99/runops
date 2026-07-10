"""Enforce inward-only imports for the domain core."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

FORBIDDEN = {
    "adapters",
    "application",
    "cli",
    "harness",
    "mcp",
    "slurm",
    "templates",
}
ALLOWED_OUTER_IMPORTS = {
    ("demo/replay.py", "runops.templates.render"),
}
CORE_ROOT = Path(__file__).parents[2] / "src" / "runops" / "core"


def _absolute_imports(
    tree: ast.AST,
    *,
    package: str,
) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name(f"{'.' * node.level}{module}", package)
            imports.extend(
                (node.lineno, ".".join(part for part in (module, alias.name) if part))
                for alias in node.names
            )
    return imports


def _is_forbidden(imported_module: str) -> bool:
    parts = imported_module.split(".")
    return len(parts) >= 2 and parts[0] == "runops" and parts[1] in FORBIDDEN


def test_internal_relative_import_resolves_within_core() -> None:
    imports = _absolute_imports(
        ast.parse("from .models import X"),
        package="runops.core",
    )

    assert imports == [(1, "runops.core.models.X")]
    assert not _is_forbidden(imports[0][1])


def test_relative_imports_escaping_core_are_forbidden() -> None:
    root_imports = _absolute_imports(
        ast.parse("from ..application import service"),
        package="runops.core",
    )
    nested_imports = _absolute_imports(
        ast.parse("from ... import adapters"),
        package="runops.core.nested",
    )

    assert root_imports == [(1, "runops.application.service")]
    assert nested_imports == [(1, "runops.adapters")]
    assert all(_is_forbidden(name) for _, name in (*root_imports, *nested_imports))


def test_too_deep_relative_import_is_rejected() -> None:
    with pytest.raises(ImportError):
        _absolute_imports(
            ast.parse("from ....application import service"),
            package="runops.core",
        )


def test_core_does_not_import_outer_layers() -> None:
    violations: list[str] = []
    allowed_seen: set[tuple[str, str]] = set()

    for path in sorted(CORE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative_parent = path.relative_to(CORE_ROOT).parent
        package = ".".join(("runops", "core", *relative_parent.parts))
        for lineno, imported_module in _absolute_imports(tree, package=package):
            if _is_forbidden(imported_module):
                import_key = (
                    path.relative_to(CORE_ROOT).as_posix(),
                    imported_module,
                )
                if import_key in ALLOWED_OUTER_IMPORTS:
                    allowed_seen.add(import_key)
                    continue
                relative_path = path.relative_to(CORE_ROOT.parents[2])
                violations.append(f"{relative_path}:{lineno}: {imported_module}")

    assert not violations, "core imports outer layers:\n" + "\n".join(violations)
    assert allowed_seen == ALLOWED_OUTER_IMPORTS
