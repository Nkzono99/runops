"""Tests for runops update notices."""

from __future__ import annotations

from datetime import datetime, timezone

from runops.cli.update_notice import (
    build_update_notice,
    should_check_for_update,
)


def test_update_notice_points_to_project_skill(tmp_path) -> None:
    """A newer PyPI version produces the update-runops guidance."""
    cache_path = tmp_path / "update-check.json"

    message = build_update_notice(
        "0.9.0",
        program="runo",
        cache_path=cache_path,
        now=datetime(2026, 5, 13, tzinfo=timezone.utc),
        fetch_latest=lambda: "0.9.1",
    )

    assert message is not None
    assert "0.9.0 -> 0.9.1" in message
    assert "$update-runops" in message
    assert "/update-runops" in message
    assert "uvx --from runops runo update-harness --plan" in message
    assert "uvx --from runops runo update-harness --apply-chain" in message


def test_update_notice_is_throttled_by_cache(tmp_path) -> None:
    """The same latest version is not announced repeatedly within a day."""
    cache_path = tmp_path / "update-check.json"
    now = datetime(2026, 5, 13, tzinfo=timezone.utc)

    first = build_update_notice(
        "0.9.0",
        program="runo",
        cache_path=cache_path,
        now=now,
        fetch_latest=lambda: "0.9.1",
    )
    assert first is not None

    repeated = build_update_notice(
        "0.9.0",
        program="runo",
        cache_path=cache_path,
        now=now,
        fetch_latest=lambda: "0.9.1",
    )
    assert repeated is None


def test_update_notice_reports_stale_project_harness(tmp_path) -> None:
    """A newer running CLI prompts a project harness refresh."""
    cache_path = tmp_path / "update-check.json"

    message = build_update_notice(
        "0.9.1",
        program="runo",
        cache_path=cache_path,
        now=datetime(2026, 5, 13, tzinfo=timezone.utc),
        fetch_latest=lambda: None,
        applied_version="0.9.0",
    )

    assert message is not None
    assert "project's runops harness is older" in message
    assert "0.9.0 -> 0.9.1" in message
    assert "uvx --from runops runo update-harness --plan" in message
    assert "uvx --from runops runo update-harness --apply-chain" in message


def test_update_notice_warns_about_older_cli_than_harness(tmp_path) -> None:
    """A stale project-local CLI is detected from harness.lock metadata."""
    cache_path = tmp_path / "update-check.json"

    message = build_update_notice(
        "0.9.0",
        program="runo",
        cache_path=cache_path,
        now=datetime(2026, 5, 13, tzinfo=timezone.utc),
        fetch_latest=lambda: None,
        applied_version="0.9.1",
    )

    assert message is not None
    assert "newer runops version (0.9.1)" in message
    assert "uvx --from runops runo <command>" in message


def test_update_notice_uses_canonical_runo_for_legacy_alias(tmp_path) -> None:
    """Guidance points to runo even when invoked through the runops alias."""
    cache_path = tmp_path / "update-check.json"

    message = build_update_notice(
        "0.9.0",
        program="runops",
        cache_path=cache_path,
        now=datetime(2026, 5, 13, tzinfo=timezone.utc),
        fetch_latest=lambda: "0.9.1",
    )

    assert message is not None
    assert "uvx --from runops runo update-harness --plan" in message
    assert "uvx --from runops runops update-harness" not in message


def test_update_notice_compares_pep440_versions(tmp_path) -> None:
    """Development releases compare correctly against final PyPI releases."""
    cache_path = tmp_path / "update-check.json"

    message = build_update_notice(
        "0.9.1.dev0",
        program="runo",
        cache_path=cache_path,
        now=datetime(2026, 5, 13, tzinfo=timezone.utc),
        fetch_latest=lambda: "0.9.1",
    )

    assert message is not None
    assert "0.9.1.dev0 -> 0.9.1" in message


def test_update_notice_skips_machine_readable_invocations() -> None:
    """JSON and MCP invocations must not be polluted by update text."""
    assert not should_check_for_update(
        ["context", "--json"],
        env={},
        stderr_is_tty=True,
    )
    assert not should_check_for_update(
        ["mcp", "serve", "--transport", "stdio"],
        env={},
        stderr_is_tty=True,
    )
