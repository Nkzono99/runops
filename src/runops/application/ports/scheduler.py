"""Narrow scheduler port used by the submission application workflow."""

from __future__ import annotations

from collections.abc import Callable

Submitter = Callable[[tuple[str, ...]], str]

__all__ = ["Submitter"]
