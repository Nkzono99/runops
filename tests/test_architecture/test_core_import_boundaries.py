"""Enforce inward-only imports for the domain core."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN = {"adapters", "application", "cli", "harness", "mcp", "slurm"}
CORE_ROOT = Path(__file__).parents[2] / "src" / "runops" / "core"


def _absolute_imports(tree: ast.AST) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            imports.extend(
                (node.lineno, ".".join(part for part in (module, alias.name) if part))
                for alias in node.names
            )
    return imports


def test_core_does_not_import_outer_layers() -> None:
    violations: list[str] = []

    for path in sorted(CORE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, imported_module in _absolute_imports(tree):
            parts = imported_module.split(".")
            if len(parts) >= 2 and parts[0] == "runops" and parts[1] in FORBIDDEN:
                relative_path = path.relative_to(CORE_ROOT.parents[2])
                violations.append(f"{relative_path}:{lineno}: {imported_module}")

    assert not violations, "core imports outer layers:\n" + "\n".join(violations)
