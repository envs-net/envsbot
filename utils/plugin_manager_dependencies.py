"""Dependency helpers for the async plugin manager."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from types import ModuleType
from typing import Any

log = logging.getLogger(__name__)


def get_dependents(meta_by_plugin: dict[str, dict[str, Any]], name: str) -> set[str]:
    """Find all plugins that depend on ``name`` recursively."""
    dependents: set[str] = set()
    to_process: deque[str] = deque([name])

    while to_process:
        current = to_process.popleft()
        for plugin_name, meta in meta_by_plugin.items():
            if plugin_name in dependents:
                continue
            if current in meta.get("requires", []):
                dependents.add(plugin_name)
                to_process.append(plugin_name)
    return dependents


def topological_sort(meta_by_plugin: dict[str, dict[str, Any]], plugin_names) -> list[str]:
    """Sort plugins by dependency order, dependencies first."""
    plugin_set = set(plugin_names)
    sorted_plugins: list[str] = []
    visited: set[str] = set()
    temp_marked: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in temp_marked:
            log.warning("[PLUGIN] circular dependency: %s", node)
            return

        temp_marked.add(node)
        meta = meta_by_plugin.get(node, {})
        for dep in meta.get("requires", []):
            if dep in plugin_set and dep not in visited:
                visit(dep)
        temp_marked.remove(node)
        visited.add(node)
        sorted_plugins.append(node)

    for plugin_name in sorted(plugin_names):
        visit(plugin_name)
    return sorted_plugins


def dependency_conflict(meta_by_plugin: dict[str, dict[str, Any]], name: str) -> tuple[bool, str]:
    """Return whether unloading ``name`` would break loaded dependents."""
    dependents = get_dependents(meta_by_plugin, name)
    if dependents:
        dependents_list = ", ".join(sorted(dependents))
        return True, f"Plugins depend on {name}: {dependents_list}"
    return False, ""


def validate_dependencies(
    name: str,
    *,
    meta_by_plugin: dict[str, dict[str, Any]],
    discovered: set[str],
    module_path: Callable[[str], str],
    import_module: Callable[[str], ModuleType],
    visited: set[str] | None = None,
) -> tuple[bool, str]:
    """Validate that all dependencies of a plugin are available."""
    if visited is None:
        visited = set()

    if name in visited:
        return False, f"Circular dependency detected involving {name}"

    visited.add(name)

    if name not in meta_by_plugin:
        try:
            module = import_module(module_path(name))
            meta = getattr(module, "PLUGIN_META", {})
        except Exception as exc:
            return False, f"Cannot load {name}: {exc}"
    else:
        meta = meta_by_plugin[name]

    for dep in meta.get("requires", []):
        if dep not in discovered:
            return False, f"Plugin {name} requires {dep}, which is not available"
        valid, message = validate_dependencies(
            dep,
            meta_by_plugin=meta_by_plugin,
            discovered=discovered,
            module_path=module_path,
            import_module=import_module,
            visited=visited.copy(),
        )
        if not valid:
            return False, message
    return True, ""
