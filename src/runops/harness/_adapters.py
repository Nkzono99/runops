"""Adapter metadata helpers used by harness generation and init bootstrap."""

from __future__ import annotations

from runops.core.codex_plugin import CodexPluginRecommendation


def collect_doc_repos(simulator_names: list[str]) -> list[tuple[str, str]]:
    """Return unique ``(url, dest)`` pairs from the given adapters."""
    import runops.adapters  # noqa: F401
    from runops.adapters.registry import get_global_registry

    registry = get_global_registry()
    seen: set[str] = set()
    repos: list[tuple[str, str]] = []
    for sim_name in simulator_names:
        try:
            adapter_cls = registry.get(sim_name)
        except KeyError:
            continue
        for url, dest in adapter_cls.doc_repos():
            if dest in seen:
                continue
            seen.add(dest)
            repos.append((url, dest))
    return repos


def collect_pip_packages(simulator_names: list[str]) -> list[str]:
    """Return unique pip packages declared by the given adapters."""
    import runops.adapters  # noqa: F401
    from runops.adapters.registry import get_global_registry

    registry = get_global_registry()
    seen: set[str] = set()
    packages: list[str] = []
    for sim_name in simulator_names:
        try:
            adapter_cls = registry.get(sim_name)
        except KeyError:
            continue
        for pkg in adapter_cls.pip_packages():
            if pkg in seen:
                continue
            seen.add(pkg)
            packages.append(pkg)
    return packages


def collect_codex_plugins(
    simulator_names: list[str],
) -> list[CodexPluginRecommendation]:
    """Return unique Codex plugins recommended by the given adapters."""
    import runops.adapters  # noqa: F401
    from runops.adapters.registry import get_global_registry

    registry = get_global_registry()
    seen: set[str] = set()
    plugins: list[CodexPluginRecommendation] = []
    for sim_name in simulator_names:
        try:
            adapter_cls = registry.get(sim_name)
        except KeyError:
            continue
        for plugin in adapter_cls.codex_plugins():
            if plugin.name in seen:
                continue
            seen.add(plugin.name)
            plugins.append(plugin)
    return plugins
