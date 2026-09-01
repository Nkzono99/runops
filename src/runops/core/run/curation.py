"""Validation helpers for durable Run review records."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime


def has_valid_run_review(curation: Mapping[str, object]) -> bool:
    """Return whether curation contains a complete, timestamped review.

    ``review_status = "reviewed"`` alone is not authoritative.  Budget and
    evidence gates only accept records written with an actor, reason, and a
    timezone-aware ISO-8601 timestamp.
    """
    if curation.get("review_status") != "reviewed":
        return False
    for key in ("reviewed_by", "reason"):
        value = curation.get(key)
        if not isinstance(value, str) or not value.strip():
            return False

    raw_timestamp = curation.get("reviewed_at")
    if not isinstance(raw_timestamp, str) or not raw_timestamp.strip():
        return False
    timestamp = raw_timestamp.strip()
    if timestamp.endswith(("Z", "z")):
        timestamp = f"{timestamp[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


__all__ = ["has_valid_run_review"]
