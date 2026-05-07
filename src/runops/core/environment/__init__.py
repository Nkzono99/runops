"""Execution environment description and auto-detection."""

from __future__ import annotations

from .runtime import (
    EnvironmentInfo,
    PartitionInfo,
    detect_environment,
    load_environment,
    save_environment,
)

__all__ = [
    "EnvironmentInfo",
    "PartitionInfo",
    "detect_environment",
    "load_environment",
    "save_environment",
]
