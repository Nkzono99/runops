"""Run review record validation tests."""

from __future__ import annotations

import pytest

from runops.core.run.curation import has_valid_run_review


def test_complete_timezone_aware_review_is_valid() -> None:
    assert has_valid_run_review(
        {
            "review_status": "reviewed",
            "reviewed_at": "2026-09-01T00:00:00Z",
            "reviewed_by": "human",
            "reason": "Checked diagnostics and outputs.",
        }
    )


@pytest.mark.parametrize(
    "curation",
    [
        {},
        {"review_status": "unreviewed"},
        {
            "review_status": "reviewed",
            "reviewed_at": "2026-09-01T00:00:00+00:00",
            "reviewed_by": "human",
            "reason": "",
        },
        {
            "review_status": "reviewed",
            "reviewed_at": "2026-09-01T00:00:00+00:00",
            "reviewed_by": 1,
            "reason": "checked",
        },
        {
            "review_status": "reviewed",
            "reviewed_at": "",
            "reviewed_by": "human",
            "reason": "checked",
        },
        {
            "review_status": "reviewed",
            "reviewed_at": 1,
            "reviewed_by": "human",
            "reason": "checked",
        },
        {
            "review_status": "reviewed",
            "reviewed_at": "yesterday",
            "reviewed_by": "human",
            "reason": "checked",
        },
        {
            "review_status": "reviewed",
            "reviewed_at": "2026-09-01T00:00:00",
            "reviewed_by": "human",
            "reason": "checked",
        },
    ],
)
def test_incomplete_or_unverifiable_review_is_invalid(
    curation: dict[str, object],
) -> None:
    assert not has_valid_run_review(curation)
