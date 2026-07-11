"""Evaluate critical-module coverage floors from coverage.py JSON output."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass(frozen=True)
class CoverageViolation:
    """One missing or below-floor critical module."""

    path: str
    actual: float | None
    required: float
    reason: str


def _mapping(value: object, *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a table or object")
    return value


def _percentage(value: object, *, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    percentage = float(value)
    if not 0.0 <= percentage <= 100.0:
        raise ValueError(f"{context} must be between 0 and 100")
    return percentage


def load_coverage_policy(config_path: Path) -> dict[str, float]:
    """Load and validate critical-module floors from a pyproject file."""
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    try:
        modules = data["tool"]["runops"]["coverage-policy"]["modules"]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "missing [tool.runops.coverage-policy.modules] table"
        ) from exc
    module_table = _mapping(
        modules,
        context="[tool.runops.coverage-policy.modules]",
    )
    if not module_table:
        raise ValueError("[tool.runops.coverage-policy.modules] must not be empty")
    return {
        path: _percentage(value, context=f"coverage floor for {path}")
        for path, value in module_table.items()
    }


def evaluate_coverage_policy(
    report_path: Path,
    policy: Mapping[str, float],
) -> tuple[CoverageViolation, ...]:
    """Return sorted violations from one coverage.py JSON report."""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid coverage JSON: {exc.msg}") from exc
    root = _mapping(report, context="coverage JSON root")
    files = _mapping(root.get("files"), context="coverage JSON files")

    violations: list[CoverageViolation] = []
    for path, required in sorted(policy.items()):
        entry = files.get(path)
        if entry is None:
            violations.append(
                CoverageViolation(
                    path=path,
                    actual=None,
                    required=required,
                    reason="module is missing from the coverage report",
                )
            )
            continue
        file_data = _mapping(entry, context=f"coverage entry for {path}")
        summary = _mapping(
            file_data.get("summary"),
            context=f"coverage summary for {path}",
        )
        actual = _percentage(
            summary.get("percent_covered"),
            context=f"percent_covered for {path}",
        )
        if actual < required:
            violations.append(
                CoverageViolation(
                    path=path,
                    actual=actual,
                    required=required,
                    reason="coverage is below the required floor",
                )
            )
    return tuple(violations)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the critical-module coverage policy checker."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--config", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args(argv)

    try:
        policy = load_coverage_policy(args.config)
        violations = evaluate_coverage_policy(args.coverage_json, policy)
    except (OSError, ValueError) as exc:
        print(f"coverage policy error: {exc}", file=sys.stderr)
        return 1

    if violations:
        for violation in violations:
            if violation.actual is None:
                detail = violation.reason
            else:
                detail = (
                    f"{violation.actual:.2f}% < {violation.required:.2f}% "
                    f"({violation.reason})"
                )
            print(f"{violation.path}: {detail}", file=sys.stderr)
        return 1

    print(f"{len(policy)} critical modules meet their coverage floors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
