"""Contract tests for the AI-facing action registry."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pytest

from runops.application import actions
from runops.application.actions import ActionStatus
from runops.cli.main import app as cli_app
from runops.cli.operations import (
    CLI_OPERATION_BINDINGS,
    CliOperationBinding,
    cli_operation_issues,
)
from runops.mcp.registry import all_tool_specs


def _command_name(command: Any) -> str:
    """Return Typer's public command name for a registered command."""
    if command.name:
        return command.name
    if command.callback is None:
        raise AssertionError("Registered CLI command is missing a callback.")
    return command.callback.__name__.replace("_", "-")


def _collect_cli_commands(
    typer_app: Any,
    prefix: tuple[str, ...] = (),
) -> set[tuple[str, ...]]:
    """Collect public command paths from a Typer app tree."""
    commands = {
        (*prefix, _command_name(command)) for command in typer_app.registered_commands
    }
    for group in typer_app.registered_groups:
        commands.update(
            _collect_cli_commands(
                group.typer_instance,
                (*prefix, group.name),
            )
        )
    return commands


def _find_cli_callback(
    typer_app: Any,
    command_path: tuple[str, ...],
) -> Callable[..., Any]:
    """Return the Typer callback for a public command path."""
    if not command_path:
        raise AssertionError("Command path must not be empty.")
    if len(command_path) == 1:
        for command in typer_app.registered_commands:
            if _command_name(command) == command_path[0]:
                if command.callback is None:
                    raise AssertionError(f"Command {command_path} has no callback.")
                return command.callback
        raise AssertionError(f"Command not found: {command_path}")

    for group in typer_app.registered_groups:
        if group.name == command_path[0]:
            return _find_cli_callback(group.typer_instance, command_path[1:])
    raise AssertionError(f"Command group not found: {command_path[0]}")


def _signature_params(
    fn: Callable[..., Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return required and optional parameter names from a callable signature."""
    required: list[str] = []
    optional: list[str] = []

    for param in inspect.signature(fn).parameters.values():
        if param.kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue
        if param.default is inspect.Signature.empty:
            required.append(param.name)
        else:
            optional.append(param.name)

    return tuple(required), tuple(optional)


def test_action_specs_and_dispatch_cover_the_same_actions() -> None:
    """Every advertised action must be executable, and vice versa."""
    assert set(actions.ACTION_SPECS) == set(actions._DISPATCH)
    for name, spec in actions.ACTION_SPECS.items():
        assert spec.name == name


@pytest.mark.parametrize("name", sorted(actions.ACTION_SPECS))
def test_action_spec_matches_dispatch_signature(name: str) -> None:
    """required_params/optional_params must match the callable signature."""
    spec = actions.ACTION_SPECS[name]
    required_params, optional_params = _signature_params(actions._DISPATCH[name])

    assert spec.required_params == required_params
    assert spec.optional_params == optional_params


def test_list_actions_exposes_all_registered_specs() -> None:
    """The public registry listing should expose every registered action."""
    assert {spec.name for spec in actions.list_actions()} == set(actions.ACTION_SPECS)


def test_get_action_spec_returns_registered_spec() -> None:
    """Named lookups should round-trip to the stored ActionSpec objects."""
    for name, expected in actions.ACTION_SPECS.items():
        assert actions.get_action_spec(name) == expected

    assert actions.get_action_spec("missing_action") is None


def test_action_specs_advertise_existing_cli_commands() -> None:
    """ActionSpec CLI metadata should stay aligned with the Typer surface."""
    known_commands = _collect_cli_commands(cli_app)
    unmapped_actions = sorted(
        name for name, spec in actions.ACTION_SPECS.items() if not spec.cli_commands
    )
    missing_commands = {
        name: spec.cli_commands
        for name, spec in actions.ACTION_SPECS.items()
        if any(command not in known_commands for command in spec.cli_commands)
    }

    assert unmapped_actions == []
    assert missing_commands == {}


def test_cli_operation_bindings_round_trip_action_specs() -> None:
    """The explicit CLI catalog should exactly match ActionSpec metadata."""
    advertised = {
        command_path: tuple(
            sorted(
                name
                for name, spec in actions.ACTION_SPECS.items()
                if command_path in spec.cli_commands
            )
        )
        for spec in actions.ACTION_SPECS.values()
        for command_path in spec.cli_commands
    }
    bound = {
        binding.command_path: tuple(sorted(binding.action_names))
        for binding in CLI_OPERATION_BINDINGS
    }

    assert cli_operation_issues() == ()
    assert bound == advertised
    assert set(bound) <= _collect_cli_commands(cli_app)
    assert bound[("runs", "retry")] == ("plan_retry", "retry_run")


def test_cli_operation_validator_reports_unknown_actions() -> None:
    """Unknown action names should be reported with their CLI path."""
    altered = [
        binding
        for binding in CLI_OPERATION_BINDINGS
        if binding.command_path != ("runs", "create")
    ]
    altered.append(
        CliOperationBinding(
            command_path=("runs", "create"),
            action_names=("missing_action",),
            effect="write",
        )
    )

    assert cli_operation_issues(altered) == (
        "CLI path 'runs create' references unknown action 'missing_action'.",
        "Missing CLI binding for action 'create_run' at 'runs create'.",
    )


def test_cli_operation_validator_reports_duplicate_paths() -> None:
    """Duplicate paths should fail instead of collapsing into one mapping."""
    binding = CLI_OPERATION_BINDINGS[0]

    issues = cli_operation_issues((*CLI_OPERATION_BINDINGS, binding))

    assert f"Duplicate CLI binding path: '{' '.join(binding.command_path)}'." in issues


def test_cli_operation_validator_reports_missing_and_extra_pairs() -> None:
    """Bindings must not omit or invent an ActionSpec path relation."""
    create_binding = next(
        binding
        for binding in CLI_OPERATION_BINDINGS
        if binding.command_path == ("runs", "create")
    )
    altered = [
        binding
        for binding in CLI_OPERATION_BINDINGS
        if binding.command_path != create_binding.command_path
    ]
    altered.append(
        CliOperationBinding(
            command_path=create_binding.command_path,
            action_names=("show_log",),
            effect=create_binding.effect,
        )
    )

    issues = cli_operation_issues(altered)

    assert "Missing CLI binding for action 'create_run' at 'runs create'." in issues
    assert "Unexpected CLI binding for action 'show_log' at 'runs create'." in issues


def test_action_specs_advertise_existing_mcp_tools() -> None:
    """ActionSpec MCP metadata should point only at registered tool names."""
    known_tools = {spec.name for spec in all_tool_specs()}
    missing_tools = {
        name: tuple(
            tool_name for tool_name in spec.mcp_tools if tool_name not in known_tools
        )
        for name, spec in actions.ACTION_SPECS.items()
        if any(tool_name not in known_tools for tool_name in spec.mcp_tools)
    }

    assert missing_tools == {}


def test_mcp_tool_bindings_round_trip_action_specs() -> None:
    """ActionSpec and ToolSpec metadata should agree in both directions."""
    specs = {spec.name: spec for spec in all_tool_specs()}
    expected = {
        "runops.job.plan_submit": "submit_run",
        "runops.job.submit": "submit_run",
        "runops.job.cancel": "cancel_run",
        "runops.run.delete": "delete_run",
        "runops.run.logs": "show_log",
        "runops.experiment.create": "create_experiment",
    }

    assert {
        name: spec.action_name for name, spec in specs.items() if spec.action_name
    } == expected
    for tool_name, action_name in expected.items():
        assert tool_name in actions.ACTION_SPECS[action_name].mcp_tools


def test_external_and_destructive_mcp_tools_have_action_bindings() -> None:
    """Unsafe tools need an action relation and explicit confirmation metadata."""
    unsafe = {
        spec.name: spec
        for spec in all_tool_specs()
        if spec.safety.safety_class in {"external", "destructive"}
    }

    assert unsafe
    for spec in unsafe.values():
        assert spec.action_name
        assert spec.safety.requires_confirmation is True
        assert spec.safety.confirmation_field


def test_action_spec_dict_includes_interface_metadata() -> None:
    """Serialized ActionSpecs should expose CLI and MCP surface metadata."""
    data = actions.ACTION_SPECS["submit_run"].to_dict()

    assert data["cli_commands"] == [["runs", "submit"]]
    assert data["mcp_tools"] == ["runops.job.plan_submit", "runops.job.submit"]


def test_human_gate_actions_require_confirmation_metadata() -> None:
    """Always-gated lifecycle actions should advertise confirmation metadata."""
    gated_actions = {"archive_run", "purge_work", "cancel_run", "delete_run"}

    for action_name in gated_actions:
        spec = actions.ACTION_SPECS[action_name]
        assert spec.requires_confirmation is True
        assert spec.confirmation_reason


def test_dynamic_submit_and_retry_gates_are_advertised() -> None:
    """Conditionally-gated expensive actions should describe trigger cases."""
    for action_name in ("submit_run", "retry_run", "add_fact"):
        spec = actions.ACTION_SPECS[action_name]
        assert spec.confirmation_conditions


def test_gated_cli_commands_offer_yes_option() -> None:
    """Human-gated CLI commands should expose an explicit confirmation bypass."""
    gated_commands = {
        ("runs", "archive"),
        ("runs", "cancel"),
        ("runs", "delete"),
        ("runs", "purge-work"),
        ("runs", "submit"),
    }

    for command_path in gated_commands:
        callback = _find_cli_callback(cli_app, command_path)
        assert "yes" in inspect.signature(callback).parameters


def test_execute_action_rejects_unknown_actions() -> None:
    """Unknown actions should return a structured error instead of raising."""
    result = actions.execute_action("missing_action")

    assert result.status is ActionStatus.ERROR
    assert "Unknown action" in result.message
