"""Registration helpers for adapters bundled with runops."""

from __future__ import annotations

from runops.adapters.contrib.beach import BeachAdapter
from runops.adapters.contrib.emses import EmseAdapter
from runops.adapters.generic import GenericAdapter
from runops.adapters.registry import AdapterRegistry, get_global_registry

BUNDLED_ADAPTERS = (GenericAdapter, EmseAdapter, BeachAdapter)


def register_bundled_adapters(registry: AdapterRegistry | None = None) -> None:
    """Register adapters shipped in the runops wheel.

    Keeping this list out of ``runops.adapters.__init__`` gives the bundled
    adapters a narrow boundary.  Future simulator packages can move out of
    ``contrib`` and expose the same names through the ``runops.adapters`` entry
    point group without changing callers.
    """
    target = registry or get_global_registry()
    registered = set(target.list_adapters())
    for adapter_cls in BUNDLED_ADAPTERS:
        adapter_name = getattr(adapter_cls, "adapter_name", "")
        if adapter_name in registered:
            continue
        target.register(adapter_cls)
        registered.add(adapter_name)
