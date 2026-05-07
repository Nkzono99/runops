"""Shared constants for the EMSES adapter."""

from __future__ import annotations

INPUT_DIR = "input"
WORK_DIR = "work"
LATEST_OUTPUT_DIR = f"{WORK_DIR}/latest"

# Domain decomposition: [mpi] group, nodes = [nxdiv, nydiv, nzdiv]
DOMAIN_DECOMP_SECTION = "mpi"
DOMAIN_DECOMP_KEY = "nodes"
