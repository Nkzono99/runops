"""Action registry facade for CLI and agent workflows.

This package keeps the stable ``runops.core.actions`` import surface while
splitting implementation by responsibility.
"""

from __future__ import annotations

from runops.core.actions.admin import (
    archive_run as archive_run,
)
from runops.core.actions.admin import (
    cancel_run as cancel_run,
)
from runops.core.actions.admin import (
    delete_run as delete_run,
)
from runops.core.actions.admin import (
    purge_work as purge_work,
)
from runops.core.actions.analysis import (
    collect_survey as collect_survey,
)
from runops.core.actions.analysis import (
    export_publication as export_publication,
)
from runops.core.actions.analysis import (
    show_log as show_log,
)
from runops.core.actions.analysis import (
    summarize_run as summarize_run,
)
from runops.core.actions.knowledge import (
    add_fact as add_fact,
)
from runops.core.actions.knowledge import (
    promote_fact as promote_fact,
)
from runops.core.actions.knowledge import (
    save_insight as save_insight,
)
from runops.core.actions.registry import _DISPATCH as _DISPATCH
from runops.core.actions.registry import execute_action as execute_action
from runops.core.actions.result import (
    ActionResult as ActionResult,
)
from runops.core.actions.result import (
    ActionStatus as ActionStatus,
)
from runops.core.actions.run_lifecycle import (
    create_run as create_run,
)
from runops.core.actions.run_lifecycle import (
    create_survey as create_survey,
)
from runops.core.actions.run_lifecycle import (
    retry_run as retry_run,
)
from runops.core.actions.run_lifecycle import (
    submit_run as submit_run,
)
from runops.core.actions.run_lifecycle import (
    sync_run as sync_run,
)
from runops.core.actions.specs import (
    ACTION_SPECS as ACTION_SPECS,
)
from runops.core.actions.specs import (
    ActionSpec as ActionSpec,
)
from runops.core.actions.specs import (
    get_action_spec as get_action_spec,
)
from runops.core.actions.specs import (
    list_actions as list_actions,
)

__all__ = [
    "ACTION_SPECS",
    "ActionResult",
    "ActionSpec",
    "ActionStatus",
    "add_fact",
    "archive_run",
    "cancel_run",
    "collect_survey",
    "create_run",
    "create_survey",
    "delete_run",
    "execute_action",
    "export_publication",
    "get_action_spec",
    "list_actions",
    "promote_fact",
    "purge_work",
    "retry_run",
    "save_insight",
    "show_log",
    "submit_run",
    "summarize_run",
    "sync_run",
]
