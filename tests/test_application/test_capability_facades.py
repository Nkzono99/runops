"""Compatibility contracts for Wave 4 capability facades."""

from runops.application.execution import submission
from runops.application.gateway import plugins


def test_submission_facade_exports_existing_public_contract() -> None:
    assert submission.SubmitRequest.__module__.endswith("submission.models")
    assert submission.plan_submit.__module__.endswith("submission.planning")
    assert callable(submission.apply_submit)
    assert callable(submission._fsync_directory)


def test_gateway_plugins_facade_exports_existing_public_contract() -> None:
    assert plugins.CodexPluginInventory.__module__.endswith("plugins.models")
    assert plugins.collect_codex_plugin_recommendations.__module__.endswith(
        "plugins.discovery"
    )
    assert plugins.check_project_codex_plugins.__module__.endswith("plugins.inventory")
