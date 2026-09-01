"""Dispatch registry for agent actions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from runops.application.actions.admin import (
    archive_run,
    cancel_run,
    delete_run,
    purge_work,
    restore_run,
    review_run,
)
from runops.application.actions.analysis import (
    collect_survey,
    export_publication,
    show_log,
    summarize_run,
)
from runops.application.actions.bundle_archive import archive_bundle, restore_bundle
from runops.application.actions.derivation import (
    clone_run,
    extend_run,
    inspect_regeneration,
)
from runops.application.actions.knowledge import add_fact, promote_fact, save_insight
from runops.application.actions.relabel import relabel_run
from runops.application.actions.research_ops import (
    archive_result,
    check_result,
    clean_test_attempts,
    close_experiment,
    create_experiment,
    create_result,
    prepare_test_attempt,
    record_test_result,
    restore_result,
    review_experiment,
    seal_result,
)
from runops.application.actions.result import ActionResult, ActionStatus
from runops.application.actions.run_lifecycle import (
    create_run,
    create_survey,
    plan_retry,
    plan_survey,
    retry_run,
    submit_run,
    sync_run,
)

logger = logging.getLogger(__name__)


#: Map action name -> callable.
_DISPATCH: dict[str, Callable[..., ActionResult]] = {
    "create_experiment": create_experiment,
    "review_experiment": review_experiment,
    "close_experiment": close_experiment,
    "prepare_test_attempt": prepare_test_attempt,
    "record_test_result": record_test_result,
    "clean_test_attempts": clean_test_attempts,
    "create_result": create_result,
    "check_result": check_result,
    "seal_result": seal_result,
    "archive_result": archive_result,
    "restore_result": restore_result,
    "create_run": create_run,
    "clone_run": clone_run,
    "extend_run": extend_run,
    "inspect_regeneration": inspect_regeneration,
    "create_survey": create_survey,
    "plan_survey": plan_survey,
    "submit_run": submit_run,
    "sync_run": sync_run,
    "show_log": show_log,
    "summarize_run": summarize_run,
    "collect_survey": collect_survey,
    "export_publication": export_publication,
    "plan_retry": plan_retry,
    "retry_run": retry_run,
    "relabel_run": relabel_run,
    "archive_run": archive_run,
    "archive_bundle": archive_bundle,
    "restore_run": restore_run,
    "restore_bundle": restore_bundle,
    "purge_work": purge_work,
    "review_run": review_run,
    "cancel_run": cancel_run,
    "delete_run": delete_run,
    "save_insight": save_insight,
    "add_fact": add_fact,
    "promote_fact": promote_fact,
}


def execute_action(action_name: str, **kwargs: Any) -> ActionResult:
    """Execute a named action with keyword arguments.

    This is the primary entry point for agents.

    Args:
        action_name: Action name (must be in ACTION_SPECS).
        **kwargs: Arguments matching the action's parameter spec.

    Returns:
        ActionResult with status, message, and data.
    """
    if action_name not in _DISPATCH:
        return ActionResult(
            action=action_name,
            status=ActionStatus.ERROR,
            message=(
                f"Unknown action: {action_name!r}. Available: {sorted(_DISPATCH)}"
            ),
        )

    fn = _DISPATCH[action_name]
    try:
        result: ActionResult = fn(**kwargs)
        return result
    except TypeError as e:
        return ActionResult(
            action=action_name,
            status=ActionStatus.ERROR,
            message=f"Invalid arguments for {action_name}: {e}",
        )
    except Exception as e:
        logger.exception("Unexpected error in action %s", action_name)
        return ActionResult(
            action=action_name,
            status=ActionStatus.ERROR,
            message=f"Unexpected error: {e}",
        )
