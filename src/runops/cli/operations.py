"""Explicit bindings between public CLI paths and application actions."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from runops.application.actions.specs import ACTION_SPECS, ActionSpec

OperationEffect = Literal["read", "write", "external", "destructive"]


@dataclass(frozen=True)
class CliOperationBinding:
    """Bind one public CLI command path to its application actions."""

    command_path: tuple[str, ...]
    action_names: tuple[str, ...]
    effect: OperationEffect


CLI_OPERATION_BINDINGS: tuple[CliOperationBinding, ...] = (
    CliOperationBinding(("runs", "create"), ("create_run",), "write"),
    CliOperationBinding(("runs", "sweep"), ("create_survey",), "write"),
    CliOperationBinding(("runs", "submit"), ("submit_run",), "external"),
    CliOperationBinding(("runs", "sync"), ("sync_run",), "external"),
    CliOperationBinding(("runs", "log"), ("show_log",), "read"),
    CliOperationBinding(("analyze", "summarize"), ("summarize_run",), "write"),
    CliOperationBinding(("analyze", "collect"), ("collect_survey",), "write"),
    CliOperationBinding(("analyze", "export"), ("export_publication",), "write"),
    CliOperationBinding(
        ("runs", "retry"),
        ("plan_retry", "retry_run"),
        "write",
    ),
    CliOperationBinding(("runs", "archive"), ("archive_run",), "destructive"),
    CliOperationBinding(
        ("runs", "purge-work"),
        ("purge_work",),
        "destructive",
    ),
    CliOperationBinding(("runs", "cancel"), ("cancel_run",), "destructive"),
    CliOperationBinding(("runs", "delete"), ("delete_run",), "destructive"),
    CliOperationBinding(("knowledge", "save"), ("save_insight",), "write"),
    CliOperationBinding(("knowledge", "add-fact"), ("add_fact",), "write"),
    CliOperationBinding(
        ("knowledge", "promote-fact"),
        ("promote_fact",),
        "write",
    ),
)


def cli_operation_issues(
    bindings: Sequence[CliOperationBinding] = CLI_OPERATION_BINDINGS,
    action_specs: Mapping[str, ActionSpec] = ACTION_SPECS,
) -> tuple[str, ...]:
    """Return deterministic violations in the CLI/action contract."""
    issues: list[str] = []
    path_counts = Counter(binding.command_path for binding in bindings)
    for command_path, count in path_counts.items():
        if count > 1:
            issues.append(
                f"Duplicate CLI binding path: '{' '.join(command_path)}'."
            )

    expected_pairs = {
        (command_path, action_name)
        for action_name, spec in action_specs.items()
        for command_path in spec.cli_commands
    }
    actual_pairs: set[tuple[tuple[str, ...], str]] = set()
    for binding in bindings:
        for action_name in binding.action_names:
            if action_name not in action_specs:
                issues.append(
                    f"CLI path '{' '.join(binding.command_path)}' references "
                    f"unknown action '{action_name}'."
                )
                continue
            actual_pairs.add((binding.command_path, action_name))

    for command_path, action_name in expected_pairs - actual_pairs:
        issues.append(
            f"Missing CLI binding for action '{action_name}' at "
            f"'{' '.join(command_path)}'."
        )
    for command_path, action_name in actual_pairs - expected_pairs:
        issues.append(
            f"Unexpected CLI binding for action '{action_name}' at "
            f"'{' '.join(command_path)}'."
        )

    return tuple(sorted(issues))
