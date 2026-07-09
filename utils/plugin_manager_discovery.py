"""Plugin discovery helpers for :mod:`utils.plugin_manager`."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from types import ModuleType
from typing import Any

log = logging.getLogger(__name__)

ImportModule = Callable[[str], ModuleType]
IterModules = Callable[[Iterable[str]], Iterable[Any]]


def discover_sources(
    sources: Iterable[tuple[str, bool]],
    *,
    import_module: ImportModule,
    iter_modules: IterModules,
) -> dict[str, dict[str, object]]:
    """Return plugin source metadata keyed by stable plugin name.

    ``sources`` is ordered by precedence.  The current runtime passes core
    plugins first and optional plugins second, so a duplicate optional plugin
    never shadows a core plugin.
    """
    result: dict[str, dict[str, object]] = {}
    for package_name, is_core in sources:
        try:
            package = import_module(package_name)
        except Exception:
            log.debug("[PLUGIN] source package unavailable: %s", package_name)
            continue

        package_path = getattr(package, "__path__", None)
        if package_path is None:
            log.debug("[PLUGIN] source is not a package: %s", package_name)
            continue

        for module_info in iter_modules(package_path):
            name = module_info.name
            if name in result and not is_core:
                continue
            result[name] = {"package": package_name, "core": is_core}
    return result


def source_info(
    name: str,
    *,
    plugin_sources: dict[str, dict[str, object]],
    discover: Callable[[], dict[str, dict[str, object]]],
    multi_source: bool,
    core_plugins: set[str],
    core_package: str | None,
    package: str,
) -> dict[str, object]:
    """Return source info for one stable plugin name."""
    if name in plugin_sources:
        return plugin_sources[name]

    discovered = discover()
    if name in discovered:
        plugin_sources[name] = discovered[name]
        return discovered[name]

    is_core = multi_source and name in core_plugins
    package_name = core_package if is_core and core_package is not None else package
    info: dict[str, object] = {"package": package_name, "core": is_core}
    plugin_sources[name] = info
    return info


def stable_discovery_order(discovered: dict[str, dict[str, object]]) -> list[str]:
    """Return deterministic core-first plugin discovery order."""
    return sorted(discovered, key=lambda name: (not discovered[name]["core"], name))
