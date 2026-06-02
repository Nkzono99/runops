"""Adapter registry for looking up simulator adapters by name.

Provides both a module-level functional API and an ``AdapterRegistry`` class
for explicit lifetime control.  The module-level functions delegate to a
shared global instance.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from collections.abc import Iterable
from importlib import metadata as importlib_metadata
from typing import Any, cast

from runops.adapters.base import SimulatorAdapter

logger = logging.getLogger(__name__)

ADAPTER_ENTRY_POINT_GROUP = "runops.adapters"


class AdapterImportError(RuntimeError):
    """Raised when a discovered adapter module fails during import."""


class AdapterRegistry:
    """Registry that maps simulator names to adapter classes.

    Attributes:
        _entries: Internal mapping from name to adapter class.
    """

    def __init__(self) -> None:
        self._entries: dict[str, type[SimulatorAdapter]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        adapter_cls: type[SimulatorAdapter],
        *,
        name: str | None = None,
    ) -> type[SimulatorAdapter]:
        """Register a simulator adapter class.

        Can be used as a decorator::

            @registry.register
            class MyAdapter(SimulatorAdapter):
                adapter_name = "my_sim"

        Args:
            adapter_cls: The adapter class to register.
            name: Explicit adapter name.  If not provided, reads the
                ``name`` property from a temporary instance or the
                ``adapter_name`` class attribute.

        Returns:
            The adapter class (unchanged).

        Raises:
            ValueError: If an adapter with the same name is already
                registered.
            AttributeError: If no name can be resolved.
        """
        resolved_name = self._resolve_name(adapter_cls, name)
        if resolved_name in self._entries:
            msg = f"Adapter already registered: {resolved_name}"
            raise ValueError(msg)
        self._entries[resolved_name] = adapter_cls
        logger.debug(
            "Registered adapter '%s' -> %s", resolved_name, adapter_cls.__name__
        )
        return adapter_cls

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> type[SimulatorAdapter]:
        """Retrieve a registered adapter class by name.

        Args:
            name: Canonical adapter name.

        Returns:
            The adapter class.

        Raises:
            KeyError: If no adapter is registered under the given name.
        """
        if name not in self._entries:
            msg = f"Unknown adapter: {name}. Available: {self.list_adapters()}"
            raise KeyError(msg)
        return self._entries[name]

    def list_adapters(self) -> list[str]:
        """Return the names of all registered adapters.

        Returns:
            Sorted list of adapter names.
        """
        return sorted(self._entries)

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def load_entry_points(
        self,
        names: Iterable[str] | None = None,
        *,
        fail_on_error: bool = True,
    ) -> None:
        """Load adapter classes from installed Python entry points.

        External simulator packages can expose adapters through the
        ``runops.adapters`` entry point group.  The entry point name is the
        adapter key used in ``simulators.toml``.
        """
        requested = set(names) if names is not None else None
        for entry_point in _adapter_entry_points():
            adapter_name = entry_point.name
            if requested is not None and adapter_name not in requested:
                continue
            if adapter_name in self._entries:
                continue
            try:
                loaded = entry_point.load()
                if not isinstance(loaded, type) or not issubclass(
                    loaded, SimulatorAdapter
                ):
                    msg = (
                        f"Adapter entry point '{adapter_name}' did not load a "
                        "SimulatorAdapter subclass"
                    )
                    raise TypeError(msg)
                self.register(loaded, name=adapter_name)
                logger.debug(
                    "Loaded adapter entry point '%s' -> %s",
                    adapter_name,
                    loaded.__name__,
                )
            except Exception as exc:
                if fail_on_error:
                    raise AdapterImportError(
                        "Failed to load adapter entry point "
                        f"'{adapter_name}' from group "
                        f"'{ADAPTER_ENTRY_POINT_GROUP}': {exc}"
                    ) from exc
                logger.warning(
                    "Skipping adapter entry point '%s': %s",
                    adapter_name,
                    exc,
                )

    def load_from_config(self, simulators_config: dict[str, Any]) -> None:
        """Auto-register adapters referenced in a simulators.toml config.

        For each simulator entry that specifies an ``adapter`` key, this
        method attempts to import and register the adapter module.  Entries
        whose adapter is already registered are silently skipped.

        Discovery checks external Python entry points first, then falls back to
        the bundled module conventions::

            runops.adapters.contrib.<adapter_name>
            runops.adapters.<adapter_name>

        Args:
            simulators_config: The parsed ``[simulators]`` table from
                ``simulators.toml``.
        """
        simulators = simulators_config.get("simulators", simulators_config)
        adapter_names = {
            str(sim_cfg.get("adapter", ""))
            for sim_cfg in simulators.values()
            if isinstance(sim_cfg, dict)
        }
        adapter_names.discard("")
        self.load_entry_points(adapter_names, fail_on_error=True)

        for sim_name, sim_cfg in simulators.items():
            if not isinstance(sim_cfg, dict):
                continue
            adapter_name = sim_cfg.get("adapter", "")
            if not adapter_name or adapter_name in self._entries:
                continue
            # Try contrib/ first, then top-level adapters/
            imported = False
            for module_path in (
                f"runops.adapters.contrib.{adapter_name}",
                f"runops.adapters.{adapter_name}",
            ):
                try:
                    spec = importlib.util.find_spec(module_path)
                except (AttributeError, ImportError):
                    spec = None
                if spec is None:
                    continue
                try:
                    importlib.import_module(module_path)
                    logger.debug(
                        "Auto-imported adapter module '%s' for simulator '%s'",
                        module_path,
                        sim_name,
                    )
                    imported = True
                    break
                except ImportError as exc:
                    raise AdapterImportError(
                        "Failed to import adapter module "
                        f"'{module_path}' for simulator '{sim_name}': {exc}"
                    ) from exc
            if not imported:
                logger.warning(
                    "Could not import adapter for simulator '%s'",
                    sim_name,
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_name(
        adapter_cls: type[SimulatorAdapter],
        explicit_name: str | None,
    ) -> str:
        """Determine the canonical name for an adapter class.

        Args:
            adapter_cls: The adapter class.
            explicit_name: An explicitly provided name, if any.

        Returns:
            The resolved adapter name.

        Raises:
            AttributeError: If no name can be determined.
        """
        if explicit_name is not None:
            return explicit_name
        # Try class-level adapter_name attribute first
        attr_name: str = getattr(adapter_cls, "adapter_name", "")
        if attr_name:
            return attr_name
        msg = (
            f"{adapter_cls.__name__} must define 'adapter_name' "
            "or pass 'name' to register()"
        )
        raise AttributeError(msg)


def _adapter_entry_points() -> list[importlib_metadata.EntryPoint]:
    """Return installed entry points that advertise runops adapters."""
    raw_entry_points: Any = importlib_metadata.entry_points()
    if hasattr(raw_entry_points, "select"):
        selected = raw_entry_points.select(group=ADAPTER_ENTRY_POINT_GROUP)
    else:  # pragma: no cover - compatibility with older importlib.metadata APIs
        selected = raw_entry_points.get(ADAPTER_ENTRY_POINT_GROUP, [])
    return list(cast("Iterable[importlib_metadata.EntryPoint]", selected))


# ------------------------------------------------------------------
# Global registry and module-level convenience functions
# ------------------------------------------------------------------

_global_registry = AdapterRegistry()


def register(
    adapter_cls: type[SimulatorAdapter],
    *,
    name: str | None = None,
) -> type[SimulatorAdapter]:
    """Register an adapter in the global registry.

    Args:
        adapter_cls: The adapter class to register.
        name: Explicit adapter name.

    Returns:
        The adapter class (unchanged).
    """
    return _global_registry.register(adapter_cls, name=name)


def get(name: str) -> type[SimulatorAdapter]:
    """Retrieve an adapter class from the global registry.

    Args:
        name: Canonical adapter name.

    Returns:
        The adapter class.
    """
    return _global_registry.get(name)


def list_adapters() -> list[str]:
    """Return all adapter names in the global registry.

    Returns:
        Sorted list of adapter names.
    """
    return _global_registry.list_adapters()


def load_entry_points(
    names: Iterable[str] | None = None,
    *,
    fail_on_error: bool = True,
) -> None:
    """Load installed adapter entry points into the global registry."""
    _global_registry.load_entry_points(names, fail_on_error=fail_on_error)


def load_from_config(simulators_config: dict[str, Any]) -> None:
    """Load adapters into the global registry from simulators.toml config.

    Args:
        simulators_config: The parsed simulators configuration.
    """
    _global_registry.load_from_config(simulators_config)


def get_global_registry() -> AdapterRegistry:
    """Return the global ``AdapterRegistry`` instance.

    Returns:
        The shared global registry.
    """
    return _global_registry
