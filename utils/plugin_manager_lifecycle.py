"""Lifecycle helpers for :mod:`utils.plugin_manager`."""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
from collections.abc import Callable
from types import ModuleType

log = logging.getLogger(__name__)


def detach_module(module: ModuleType, name: str, *, fallback_package: str) -> None:
    """Detach a plugin module and its submodules from the import system."""
    modname = getattr(module, "__name__", None) or f"{fallback_package}.{name}"
    sys.modules.pop(modname, None)

    pkg_name, _, child = modname.rpartition(".")
    if pkg_name and child:
        pkg = sys.modules.get(pkg_name)
        if pkg is not None and getattr(pkg, child, None) is module:
            try:
                delattr(pkg, child)
            except Exception:
                log.debug("[PLUGIN] failed to delattr(%s, %s)", pkg_name, child, exc_info=True)

    prefix = modname + "."
    for module_name in [key for key in sys.modules if key.startswith(prefix)]:
        sys.modules.pop(module_name, None)


async def run_hook(bot, hook) -> None:
    """Run a plugin hook that may be sync or async."""
    if hook is None:
        return
    if asyncio.iscoroutinefunction(hook):
        await hook(bot)
    else:
        await asyncio.to_thread(hook, bot)


async def import_module_async(module_path: str, *, import_module: Callable[[str], ModuleType] | None = None) -> ModuleType:
    """Import ``module_path`` in a worker thread after invalidating caches."""
    importlib.invalidate_caches()
    importer = import_module or importlib.import_module
    return await asyncio.to_thread(importer, module_path)
