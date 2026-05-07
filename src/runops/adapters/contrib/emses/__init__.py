"""EMSES simulator adapter."""

from __future__ import annotations

from .adapter import EmseAdapter
from .constants import (
    DOMAIN_DECOMP_KEY,
    DOMAIN_DECOMP_SECTION,
    INPUT_DIR,
    LATEST_OUTPUT_DIR,
    WORK_DIR,
)
from .validation import compute_mpi_processes

__all__ = [
    "DOMAIN_DECOMP_KEY",
    "DOMAIN_DECOMP_SECTION",
    "INPUT_DIR",
    "LATEST_OUTPUT_DIR",
    "WORK_DIR",
    "EmseAdapter",
    "compute_mpi_processes",
]
