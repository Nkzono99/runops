"""Simulator adapters for abstracting simulator-specific behavior.

Importing this package automatically registers the built-in adapters
(e.g. ``GenericAdapter``) in the global registry.
"""

from __future__ import annotations

from runops.adapters.base import SimulatorAdapter
from runops.adapters.bundled import register_bundled_adapters
from runops.adapters.contrib.beach import BeachAdapter
from runops.adapters.contrib.emses import EmseAdapter
from runops.adapters.generic import GenericAdapter
from runops.adapters.registry import (
    get,
    get_global_registry,
    list_adapters,
    load_entry_points,
    register,
)

# Register bundled adapters first.  External packages can provide additional
# adapters through the `runops.adapters` Python entry point group.
register_bundled_adapters()
load_entry_points(fail_on_error=False)

__all__ = [
    "BeachAdapter",
    "EmseAdapter",
    "GenericAdapter",
    "SimulatorAdapter",
    "get",
    "get_global_registry",
    "list_adapters",
    "load_entry_points",
    "register",
]
