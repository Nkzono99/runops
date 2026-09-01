"""Action registry facade for CLI and agent workflows.

This package keeps the stable ``runops.application.actions`` import surface while
splitting implementation by responsibility.
"""

from __future__ import annotations

from runops.application.actions.admin import (
    archive_run as archive_run,
)
from runops.application.actions.admin import (
    cancel_run as cancel_run,
)
from runops.application.actions.admin import (
    default_archive_destination as default_archive_destination,
)
from runops.application.actions.admin import (
    delete_run as delete_run,
)
from runops.application.actions.admin import (
    purge_work as purge_work,
)
from runops.application.actions.admin import (
    restore_run as restore_run,
)
from runops.application.actions.admin import review_run as review_run
from runops.application.actions.analysis import (
    collect_survey as collect_survey,
)
from runops.application.actions.analysis import (
    export_publication as export_publication,
)
from runops.application.actions.analysis import (
    show_log as show_log,
)
from runops.application.actions.analysis import (
    summarize_run as summarize_run,
)
from runops.application.actions.bundle_archive import (
    archive_bundle as archive_bundle,
)
from runops.application.actions.bundle_archive import (
    default_bundle_archive_destination as default_bundle_archive_destination,
)
from runops.application.actions.bundle_archive import (
    plan_bundle_archive as plan_bundle_archive,
)
from runops.application.actions.bundle_archive import (
    restore_bundle as restore_bundle,
)
from runops.application.actions.derivation import clone_run as clone_run
from runops.application.actions.derivation import extend_run as extend_run
from runops.application.actions.derivation import (
    inspect_regeneration as inspect_regeneration,
)
from runops.application.actions.knowledge import (
    add_fact as add_fact,
)
from runops.application.actions.knowledge import (
    promote_fact as promote_fact,
)
from runops.application.actions.knowledge import (
    save_insight as save_insight,
)
from runops.application.actions.registry import _DISPATCH as _DISPATCH
from runops.application.actions.registry import execute_action as execute_action
from runops.application.actions.relabel import (
    plan_run_relabel as plan_run_relabel,
)
from runops.application.actions.relabel import relabel_run as relabel_run
from runops.application.actions.research_ops import (
    archive_result as archive_result,
)
from runops.application.actions.research_ops import (
    check_result as check_result,
)
from runops.application.actions.research_ops import (
    clean_test_attempts as clean_test_attempts,
)
from runops.application.actions.research_ops import (
    close_experiment as close_experiment,
)
from runops.application.actions.research_ops import (
    create_experiment as create_experiment,
)
from runops.application.actions.research_ops import (
    create_result as create_result,
)
from runops.application.actions.research_ops import (
    prepare_test_attempt as prepare_test_attempt,
)
from runops.application.actions.research_ops import (
    record_test_result as record_test_result,
)
from runops.application.actions.research_ops import (
    restore_result as restore_result,
)
from runops.application.actions.research_ops import (
    review_experiment as review_experiment,
)
from runops.application.actions.research_ops import (
    seal_result as seal_result,
)
from runops.application.actions.result import (
    ActionResult as ActionResult,
)
from runops.application.actions.result import (
    ActionStatus as ActionStatus,
)
from runops.application.actions.run_lifecycle import (
    create_run as create_run,
)
from runops.application.actions.run_lifecycle import (
    create_survey as create_survey,
)
from runops.application.actions.run_lifecycle import (
    plan_retry as plan_retry,
)
from runops.application.actions.run_lifecycle import (
    plan_survey as plan_survey,
)
from runops.application.actions.run_lifecycle import (
    retry_run as retry_run,
)
from runops.application.actions.run_lifecycle import (
    submit_planned_run as submit_planned_run,
)
from runops.application.actions.run_lifecycle import (
    submit_run as submit_run,
)
from runops.application.actions.run_lifecycle import (
    sync_run as sync_run,
)
from runops.application.actions.specs import (
    ACTION_SPECS as ACTION_SPECS,
)
from runops.application.actions.specs import (
    ActionSpec as ActionSpec,
)
from runops.application.actions.specs import (
    get_action_spec as get_action_spec,
)
from runops.application.actions.specs import (
    list_actions as list_actions,
)

__all__ = [
    "ACTION_SPECS",
    "ActionResult",
    "ActionSpec",
    "ActionStatus",
    "add_fact",
    "archive_bundle",
    "archive_result",
    "archive_run",
    "cancel_run",
    "check_result",
    "clean_test_attempts",
    "clone_run",
    "close_experiment",
    "collect_survey",
    "create_experiment",
    "create_result",
    "create_run",
    "create_survey",
    "default_archive_destination",
    "default_bundle_archive_destination",
    "delete_run",
    "execute_action",
    "export_publication",
    "extend_run",
    "get_action_spec",
    "inspect_regeneration",
    "list_actions",
    "plan_bundle_archive",
    "plan_retry",
    "plan_run_relabel",
    "plan_survey",
    "prepare_test_attempt",
    "promote_fact",
    "purge_work",
    "record_test_result",
    "relabel_run",
    "restore_bundle",
    "restore_result",
    "restore_run",
    "retry_run",
    "review_experiment",
    "review_run",
    "save_insight",
    "seal_result",
    "show_log",
    "submit_planned_run",
    "submit_run",
    "summarize_run",
    "sync_run",
]
