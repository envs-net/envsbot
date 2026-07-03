"""
Async plugin manager for dynamic loading, unloading, and reloading of plugins.

This module provides the PluginManager class, which is responsible for:
- Discovering plugins from a package
- Loading plugins with dependency resolution
- Registering commands into the global COMMANDS registry
- Managing plugin lifecycle hooks (on_load / on_unload)
- Tracking plugin metadata and event handlers
- Safe plugin reloading with dependency-aware management

All lifecycle operations are fully asynchronous and must be awaited.
"""

import asyncio
import importlib
import pkgutil
import sys
import inspect
import logging
from collections import deque

from utils.command import COMMANDS, Role

log = logging.getLogger(__name__)


DEFAULT_OPTIONAL_PLUGIN_PACKAGE = "plugins"
DEFAULT_CORE_PLUGIN_PACKAGE = "core_plugins"

CORE_PLUGIN_NAMES = {
    "_admin",
    "_core",
    "_reg_profile",
    "audit",
    "backups",
    "config_cmd",
    "doctor",
    "help",
    "plugins",
    "presence",
    "rooms",
    "tasks",
    "users",
}


class PluginManager:
    """
    Manages plugin lifecycle and integration with the bot.

    This class is fully asynchronous. All lifecycle methods (load, unload,
    reload, load_all) must be awaited.

    Attributes:
        bot: The bot instance used for registering event handlers.
        package (str): Python package path where plugins are located.
        plugins (dict): Loaded plugin modules mapped by name.
        meta (dict): Cached PLUGIN_META per plugin.
        _event_handlers (dict): Registered event handlers per plugin.
        _lock (asyncio.Lock): Ensures safe concurrent lifecycle operations.
        _dependents (dict): Cache of plugins that depend on each plugin.
    """

    def __init__(
        self,
        bot,
        package=DEFAULT_OPTIONAL_PLUGIN_PACKAGE,
        *,
        core_package=DEFAULT_CORE_PLUGIN_PACKAGE,
        core_plugins=None,
    ):
        """Initialize the plugin manager.

        The default runtime layout has two sources:

        * ``core_plugins`` for built-in bot/admin plugins
        * ``plugins`` for optional feature plugins

        Plugin names stay stable (for example ``help`` or ``rooms``), even when
        their Python modules live in ``core_plugins``.  Tests and custom callers
        can still pass a custom ``package`` to manage a single package.
        """
        self.bot = bot
        self.package = package
        self.core_package = core_package
        self.core_plugins = set(core_plugins or CORE_PLUGIN_NAMES)

        self._multi_source = (
            package == DEFAULT_OPTIONAL_PLUGIN_PACKAGE
            and core_package is not None
        )
        if self._multi_source:
            self.sources = [(core_package, True), (package, False)]
        else:
            self.sources = [(package, False)]

        self.plugins = {}
        self.meta = {}
        self.plugin_sources = {}
        self._event_handlers = {}
        self._dependents = {}  # Cache: plugin -> plugins that depend on it

        self._lock = asyncio.Lock()

    # --------------------------------------------------
    # DEPENDENCY ANALYSIS
    # --------------------------------------------------

    def _get_dependents(self, name):
        """
        Find ALL plugins that depend on the given plugin (recursively).
        """
        dependents = set()
        to_process = deque([name])

        while to_process:
            current = to_process.popleft()

            for plugin_name, meta in self.meta.items():
                if plugin_name in dependents:
                    continue

                if current in meta.get("requires", []):
                    dependents.add(plugin_name)
                    to_process.append(plugin_name)

        return dependents

    def _topological_sort(self, plugin_names):
        """
        Sort plugins by their dependencies (topological sort).

        Ensures that if plugin A depends on plugin B, B is loaded BEFORE A.

        Args:
            plugin_names: Iterable of plugin names to sort

        Returns:
            list: Sorted plugin names (dependencies first)
        """
        plugin_set = set(plugin_names)
        sorted_plugins = []
        visited = set()
        temp_marked = set()

        def visit(node):
            if node in visited:
                return
            if node in temp_marked:
                log.warning("[PLUGIN] circular dependency: %s", node)
                return

            temp_marked.add(node)

            # Visit all dependencies of this node FIRST
            meta = self.meta.get(node, {})
            for dep in meta.get("requires", []):
                if dep in plugin_set and dep not in visited:
                    visit(dep)

            temp_marked.remove(node)
            visited.add(node)
            sorted_plugins.append(node)

        # Sort input for deterministic order
        for plugin_name in sorted(plugin_names):
            visit(plugin_name)

        return sorted_plugins

    def _check_dependency_conflict(self, name: str) -> tuple[bool, str]:
        """
        Check if unloading a plugin would break other plugins.

        Returns:
            (bool, str): (has_conflict, error_message)
        """
        dependents = self._get_dependents(name)
        if dependents:
            dependents_list = ", ".join(sorted(dependents))
            return True, f"Plugins depend on {name}: {dependents_list}"
        return False, ""

    def _validate_dependencies(
        self,
        name: str,
        _visited=None,
        _discovered=None,
    ) -> tuple[bool, str]:
        """
        Validate that all dependencies of a plugin are available.

        Returns:
            (bool, str): (valid, error_message)
        """
        if _visited is None:
            _visited = set()
        if _discovered is None:
            _discovered = self.discover()

        if name in _visited:
            return False, f"Circular dependency detected involving {name}"

        _visited.add(name)

        # Try to load metadata if not already loaded
        if name not in self.meta:
            try:
                module = importlib.import_module(self._module_path(name))
                meta = getattr(module, "PLUGIN_META", {})
            except Exception as e:
                return False, f"Cannot load {name}: {e}"
        else:
            meta = self.meta[name]

        # Check required dependencies
        for dep in meta.get("requires", []):
            if dep not in _discovered:
                return (
                    False,
                    f"Plugin {name} requires {dep}, which is not available",
                )

            # Recursively validate transitive dependencies
            valid, msg = self._validate_dependencies(
                dep,
                _visited.copy(),
                _discovered,
            )
            if not valid:
                return False, msg

        return True, ""

    # --------------------------------------------------
    # SOURCE HELPERS
    # --------------------------------------------------

    def _discover_sources(self):
        """Return plugin source metadata keyed by stable plugin name."""
        result = {}
        for package_name, is_core in self.sources:
            try:
                package = importlib.import_module(package_name)
            except Exception:
                log.debug("[PLUGIN] source package unavailable: %s", package_name)
                continue

            package_path = getattr(package, "__path__", None)
            if package_path is None:
                log.debug("[PLUGIN] source is not a package: %s", package_name)
                continue

            for module_info in pkgutil.iter_modules(package_path):
                name = module_info.name
                # Core plugins win over optional plugins if a duplicate exists.
                if name in result and not is_core:
                    continue
                result[name] = {"package": package_name, "core": is_core}

        return result

    def _source_info(self, name: str) -> dict:
        """Return source info for a plugin name."""
        if name in self.plugin_sources:
            return self.plugin_sources[name]

        discovered = self._discover_sources()
        if name in discovered:
            self.plugin_sources[name] = discovered[name]
            return discovered[name]

        # Fallback keeps tests with monkeypatched imports working.
        is_core = self._multi_source and name in self.core_plugins
        package = self.core_package if is_core else self.package
        info = {"package": package, "core": is_core}
        self.plugin_sources[name] = info
        return info

    def _module_path(self, name: str) -> str:
        """Return full Python module path for a stable plugin name."""
        return f"{self._source_info(name)['package']}.{name}"

    def is_core_plugin(self, name: str) -> bool:
        """Return whether a plugin is provided by the core plugin package."""
        return bool(self._source_info(name).get("core"))

    # --------------------------------------------------
    # EVENTS
    # --------------------------------------------------

    def register_event(self, plugin_name, event, handler):
        """
        Register an event handler for a plugin.

        Args:
            plugin_name (str): Name of the plugin.
            event (str): Event name.
            handler (callable): Event handler function.
        """
        self.bot.add_event_handler(event, handler)
        self._event_handlers.setdefault(plugin_name,
                                        []).append((event, handler))

    def create_task(self, plugin_name, coro, *, name=None):
        """Create a supervised background task for a plugin.

        Plugins should use this helper instead of bare ``asyncio.create_task``
        for long-running loops. The manager cancels these tasks on unload and
        exposes them to the status command.
        """
        supervisor = getattr(self.bot, "tasks", None)
        if supervisor is None:
            task = asyncio.create_task(coro, name=name)
            return task
        return supervisor.create(plugin_name, coro, name=name)

    async def _cancel_plugin_tasks(self, plugin_name):
        """Cancel supervised tasks that belong to one plugin."""
        supervisor = getattr(self.bot, "tasks", None)
        if supervisor is None:
            return 0
        cancelled = await supervisor.cancel_plugin(plugin_name)
        if cancelled:
            log.debug("[PLUGIN] cancelled %d task(s) for %s", cancelled, plugin_name)
        return cancelled

    # --------------------------------------------------
    # DISCOVERY
    # --------------------------------------------------

    def discover(self):
        """
        Discover available plugins from all configured sources.

        Returns:
            list[str]: Sorted list of stable plugin names. Core plugins are
            ordered before optional plugins for deterministic startup.
        """
        discovered = self._discover_sources()
        self.plugin_sources.update(discovered)
        return sorted(
            discovered,
            key=lambda name: (not discovered[name]["core"], name),
        )

    def list(self):
        """
        List currently loaded plugins.

        Returns:
            list[str]: Sorted list of loaded plugin names.
        """
        return sorted(self.plugins.keys())

    def available(self):
        """
        List plugins that are available but not currently loaded.

        Returns:
            list[str]: Sorted list of plugin names.
        """
        return sorted(set(self.discover()) - set(self.plugins))

    # --------------------------------------------------
    # INTERNAL HELPERS
    # --------------------------------------------------
    async def _try_loading_plugins(self, discovered, loaded, failed):
        """
        Extracted plugin load loop from load_all() method to decrease
        cyclomatic complexity.
        """
        made_progress = False
        for plugin in discovered:
            if plugin in loaded or plugin in failed:
                continue

            # Get metadata
            try:
                if plugin not in self.meta:
                    module = await self._import(self._module_path(plugin))
                    meta = getattr(module, "PLUGIN_META", {})
                else:
                    meta = self.meta[plugin]
            except Exception:
                failed.add(plugin)
                continue

            # Check if all dependencies are loaded
            requires = meta.get("requires", [])
            if all(dep in loaded for dep in requires):
                try:
                    await self.load(plugin)
                    loaded.add(plugin)
                    made_progress = True
                except Exception:
                    log.exception("[PLUGIN] failed to load: %s", plugin)
                    failed.add(plugin)
            else:
                log.debug(
                    "[PLUGIN] waiting for dependencies before loading %s",
                    plugin,
                )
        return loaded, failed, made_progress

    def _detach_module(self, module, name: str):
        """
        Deterministically detach a plugin module from the import system.

        This ensures the import system and parent package will not retain
        references to the old module object, preventing stale code from
        remaining reachable after unload / failed load.

        This does NOT rely on garbage collection.
        """
        modname = getattr(module, "__name__", None) or f"{self.package}.{name}"

        # Remove the module itself from sys.modules
        sys.modules.pop(modname, None)

        # Remove attribute from parent package (e.g. plugins.help)
        pkg_name, _, child = modname.rpartition(".")
        if pkg_name and child:
            pkg = sys.modules.get(pkg_name)
            if pkg is not None and getattr(pkg, child, None) is module:
                try:
                    delattr(pkg, child)
                except Exception:
                    # Best-effort cleanup; should not mask unload errors
                    log.debug("[PLUGIN] failed to delattr(%s, %s)",
                              pkg_name, child, exc_info=True)

        # Remove any submodules under this plugin namespace (plugins.<name>.*)
        prefix = modname + "."
        for k in [k for k in sys.modules.keys() if k.startswith(prefix)]:
            sys.modules.pop(k, None)

    async def _run_hook(self, hook):
        """
        Execute a plugin hook safely.

        Supports both sync and async functions.

        Args:
            hook (callable): Hook function.
        """
        if hook is None:
            return
        if inspect.iscoroutinefunction(hook):
            await hook(self.bot)
        else:
            await asyncio.to_thread(hook, self.bot)

    async def _import(self, module_path):
        """
        Import a module asynchronously.

        Args:
            module_path (str): Full module path.

        Returns:
            module: Imported module.
        """
        # Helps when tests create or modify modules dynamically.
        importlib.invalidate_caches()
        return await asyncio.to_thread(importlib.import_module, module_path)

    # --------------------------------------------------
    # CORE (ASYNC)
    # --------------------------------------------------

    async def load(self, name, _stack=None):
        """
        Load a plugin and its dependencies.

        Args:
            name (str): Plugin name.
            _stack (list, optional): Dependency stack for cycle detection.
        """
        if name in self.plugins:
            log.warning("[PLUGIN] already loaded: %s", name)
            return

        if _stack is None:
            _stack = []

        if name in _stack:
            log.error(
                "[PLUGIN] circular dependency: %s -> %s",
                " -> ".join(_stack),
                name,
            )
            return

        _stack = _stack + [name]

        module = None

        try:
            log.info("[PLUGIN] loading: %s", name)

            module = await self._import(self._module_path(name))
            meta = getattr(module, "PLUGIN_META", {})

            # Load dependencies first
            for dep in meta.get("requires", []):
                if dep not in self.plugins:
                    await self.load(dep, _stack)

            # Run on_load hook if present
            async with self._lock:
                if name in self.plugins:
                    return
                try:
                    if hasattr(module, "on_load"):
                        await self._run_hook(module.on_load)

                    # Register commands
                    self._register_commands(name, module)

                    self.plugins[name] = module
                    self.meta[name] = meta

                    log.info("[PLUGIN] loaded: %s", name)
                except Exception:
                    log.exception(
                        "[PLUGIN] 🔴 Failed to load plugin (on_load): '%s'",
                        name,
                    )
                    # Remove any commands that might have been registered
                    COMMANDS.remove_by_plugin(name)
                    # Ensure the partially-imported module is not left
                    # reachable
                    if module is not None:
                        self._detach_module(module, name)
                    raise

        finally:
            # no-op: kept for symmetry / future hooks
            pass

    async def unload(self, name, force=False, *, allow_core=False):
        """
        Unload a plugin and clean up all associated resources.

        Args:
            name (str): Plugin name.
            force (bool): If True, unload even if other plugins depend on it.

        Returns:
            tuple: (bool, str) - (success, message)
        """
        if self.is_core_plugin(name) and not allow_core:
            return False, f"Plugin {name} is a core plugin and cannot be unloaded"

        # Check for dependent plugins
        if not force:
            has_conflict, msg = self._check_dependency_conflict(name)
            if has_conflict:
                log.warning("[PLUGIN] cannot unload %s: %s", name, msg)
                return False, msg

        async with self._lock:
            module = self.plugins.pop(name, None)
            if module is None:
                return False, f"Plugin {name} is not loaded"

            try:
                # Remove event handlers with error handling
                removed_handlers = 0
                for event, handler in self._event_handlers.pop(name, []):
                    try:
                        self.bot.del_event_handler(event, handler)
                        removed_handlers += 1
                    except Exception as e:
                        log.warning(
                            "[PLUGIN] failed to remove event handler"
                            " %s.%s: %s",
                            name, event, e
                        )

                if removed_handlers > 0:
                    log.debug("[PLUGIN] removed %d event handlers from %s",
                              removed_handlers, name)

                # Run unload hook with error handling
                if hasattr(module, "on_unload"):
                    try:
                        await self._run_hook(module.on_unload)
                    except Exception as e:
                        log.exception("[PLUGIN] on_unload failed for %s: %s",
                                      name, e)
                        # Don't fail the entire unload, continue with cleanup

                await self._cancel_plugin_tasks(name)

                # Remove commands
                COMMANDS.remove_by_plugin(name)

                # Debug leak detection (if enabled)
                if log.isEnabledFor(logging.DEBUG):
                    from utils.command import debug_leaks
                    debug_leaks()

                # Cleanup metadata
                self.meta.pop(name, None)
                self.plugin_sources.pop(name, None)

                # Deterministically detach from import system (no GC reliance)
                self._detach_module(module, name)

                log.info("[PLUGIN] unloaded: %s", name)
                return True, f"Plugin {name} unloaded"

            except Exception as e:
                log.exception("[PLUGIN] error during unload of %s", name)
                # Attempt to restore plugin reference for recovery
                self.plugins[name] = module
                return False, f"Error unloading {name}: {e}"

    async def reload(self, name, auto=False):
        """
        Reload a plugin and optionally its dependents.

        Args:
            name (str): Plugin name.
            auto (bool): If True, automatically reload dependent plugins.
                        If False, return error if plugins depend on this one.

        Returns:
            tuple: (bool, str) - (success, message)
        """
        log.info("[PLUGIN] reloading: %s (auto=%s)", name, auto)

        # Check for dependent plugins
        dependents = self._get_dependents(name)

        if dependents and not auto:
            # Dependents exist but auto is False
            log.warning(
                "[PLUGIN] cannot reload %s safely: plugins depend on it: %s",
                name, ", ".join(sorted(dependents))
            )
            return False, (
                f"Cannot reload {name} safely. Plugins depend on it:"
                f" {', '.join(sorted(dependents))}. "
                f"Use 'plugin reload {name} auto' to reload with dependents."
            )

        try:
            # If auto mode: unload dependents first (in reverse
            # topological order)
            # u_order -> unload order
            # u_errors -> unload errors
            if auto and dependents:
                log.info("[PLUGIN] auto-unloading %d dependent(s)",
                         len(dependents))
                # Unload in reverse topological order (deepest first)
                u_order = list(reversed(self._topological_sort(dependents)))
                u_errors = []

                for dep_name in u_order:
                    try:
                        log.debug("[PLUGIN] unloading dependent: %s", dep_name)
                        await self.unload(dep_name, allow_core=True)
                    except Exception as e:
                        u_errors.append(f"{dep_name}: {e}")
                        log.exception("[PLUGIN] failed to unload dependent %s",
                                      dep_name)

                if u_errors:
                    error_msg = "; ".join(u_errors)
                    log.error("[PLUGIN] errors unloading dependents: %s",
                              error_msg)
                    return False, f"Error unloading dependents: {error_msg}"

            # Unload and reload target
            log.debug("[PLUGIN] unloading target: %s", name)
            await self.unload(name, allow_core=True)

            log.debug("[PLUGIN] loading target: %s", name)
            await self.load(name)

            # Reload dependents if auto mode (in topological order
            # - dependencies first)
            if auto and dependents:
                reload_errors = []
                # Load in topological order (dependencies first)
                load_order = self._topological_sort(dependents)

                for dep_name in load_order:
                    try:
                        log.debug("[PLUGIN] reloading dependent: %s", dep_name)
                        await self.load(dep_name)
                    except Exception as e:
                        reload_errors.append(f"{dep_name}: {e}")
                        log.exception("[PLUGIN] failed to reload dependent %s",
                                      dep_name)

                if reload_errors:
                    error_msg = "; ".join(reload_errors)
                    log.error("[PLUGIN] errors reloading dependents: %s",
                              error_msg)
                    return True, (
                        f"Plugin {name} reloaded, but errors occurred"
                        f" reloading {len(reload_errors)} dependent(s):"
                        f" {error_msg}"
                    )

                # Use len(load_order) instead of unique_dependents
                out = f"✅ Plugin {name} and {len(load_order)}"
                out += " dependent(s) reloaded successfully"
                return True, out

            return True, f"✅ Plugin {name} reloaded"

        except Exception as e:
            log.exception("[PLUGIN] error during reload of %s", name)
            return False, f"Error reloading {name}: {e}"

    async def load_all(self):
        """
        Load all available plugins in dependency order.
        """
        discovered = self.discover()
        loaded = set()
        failed = set()

        # Simple topological sort: try to load plugins with their
        # dependencies first
        max_iterations = len(discovered)
        iteration = 0

        while len(loaded) < len(discovered) and iteration < max_iterations:
            iteration += 1

            # calling _try_loading_plugins() method to reduce cyclomatic
            # complexity.
            loaded, failed, made_progress = await self._try_loading_plugins(
                discovered, loaded, failed)

            if not made_progress and len(loaded) < len(discovered):
                # No progress made but plugins still unloaded
                # Load remaining plugins anyway (may have unsatisfied deps)
                for plugin in discovered:
                    if plugin not in loaded and plugin not in failed:
                        try:
                            await self.load(plugin)
                            loaded.add(plugin)
                        except Exception:
                            log.exception("[PLUGIN] failed to load: %s",
                                          plugin)
                            failed.add(plugin)
                break
            log.info("[PLUGIN] load_all progress: %d/%d loaded, %d failed",
                     len(loaded), len(discovered), len(failed))
            if len(failed) > 0:
                log.warning("[PLUGIN] failed: %s", ", ".join(sorted(failed)))

    async def cleanup_room_state(self, room_jid: str) -> dict[str, dict]:
        """Ask loaded plugins to clean state for a deleted room.

        Plugins may expose either ``cleanup_room_state(bot, room_jid)`` or the
        older-compatible ``on_room_delete(bot, room_jid)`` hook.  The hook may
        be sync or async and should return a dict with cleanup counters.
        Failures are logged per plugin and returned to the caller instead of
        aborting the whole room deletion.
        """
        summaries = {}
        for name, module in tuple(self.plugins.items()):
            hook = getattr(module, "cleanup_room_state", None)
            if hook is None:
                hook = getattr(module, "on_room_delete", None)
            if hook is None:
                continue
            if not callable(hook):
                log.warning(
                    "[PLUGIN] cleanup_room_state on %s is not callable",
                    name,
                )
                continue
            try:
                result = hook(self.bot, room_jid)
                if inspect.isawaitable(result):
                    result = await result
                if result is None:
                    result = {}
                if not isinstance(result, dict):
                    result = {"result": result}
                summaries[name] = result
            except Exception as exc:
                log.exception(
                    "[PLUGIN] cleanup_room_state failed for %s in %s",
                    name,
                    room_jid,
                )
                summaries[name] = {"error": str(exc)}
        return summaries

    async def plugin_state(self, name: str, room_jid: str | None = None) -> dict:
        """Return plugin-provided runtime state for diagnostics.

        Plugins can expose ``get_runtime_state(bot, room_jid=None)``.  The hook
        may be sync or async and should return a small dict with counts/status
        values, not raw user data.  Missing hooks return an empty state rather
        than failing diagnostics.
        """
        module = self.plugins.get(name)
        if module is None:
            return {"loaded": False}

        hook = getattr(module, "get_runtime_state", None)
        if hook is None:
            return {"loaded": True}
        if not callable(hook):
            return {"loaded": True, "error": "get_runtime_state is not callable"}

        try:
            result = hook(self.bot, room_jid=room_jid)
            if inspect.isawaitable(result):
                result = await result
            if result is None:
                result = {}
            if not isinstance(result, dict):
                result = {"result": result}
            return {"loaded": True, **result}
        except Exception as exc:
            log.exception("[PLUGIN] get_runtime_state failed for %s", name)
            return {"loaded": True, "error": str(exc)}

    async def restart_tasks(self, name: str) -> tuple[bool, str, int]:
        """Restart supervised background tasks for one loaded plugin.

        A plugin may provide ``restart_tasks(bot)`` for targeted restoration.
        Without that hook, the plugin's ``on_ready(bot)`` hook is reused because
        current task-owning plugins already restore/schedule their loops there.
        Tasks are only cancelled after a usable restart hook is found; otherwise
        a diagnostic restart attempt must not accidentally stop live workers.
        """
        module = self.plugins.get(name)
        if module is None:
            return False, f"Plugin {name} is not loaded", 0

        hook = getattr(module, "restart_tasks", None) or getattr(module, "on_ready", None)
        if hook is None:
            return False, f"Plugin {name} has no task restart hook", 0
        if not callable(hook):
            return False, f"Plugin {name} task restart hook is not callable", 0

        cancelled = await self._cancel_plugin_tasks(name)
        try:
            await self._run_hook(hook)
        except Exception as exc:
            log.exception("[PLUGIN] task restart failed for %s", name)
            return False, f"Error restarting tasks for {name}: {exc}", cancelled
        return True, f"Plugin {name} tasks restarted", cancelled

    async def call_on_ready(self):
        """
        Call on_ready() hook for all loaded plugins.

        This should be called AFTER the bot is fully initialized and DB is
        connected. Use this for expensive initialization like loading data
        from the database.
        """
        for name, module in tuple(self.plugins.items()):
            if hasattr(module, "on_ready"):
                try:
                    log.debug("[PLUGIN] calling on_ready: %s", name)
                    await self._run_hook(module.on_ready)
                except Exception:
                    log.exception("[PLUGIN] 🔴 on_ready failed: %s", name)

    # --------------------------------------------------
    # COMMAND REGISTRATION
    # --------------------------------------------------

    def _register_commands(self, plugin_name, module):
        """
        Register commands defined in a plugin module.

        This preserves the existing command system behavior.

        Args:
            plugin_name (str): Plugin name.
            module (module): Plugin module.
        """
        is_internal = plugin_name.startswith("_")

        for _, obj in inspect.getmembers(module):
            if callable(obj) and hasattr(obj, "_command_names"):

                for name, cmd in getattr(obj, "__commands__", []):
                    COMMANDS.register(name, cmd, plugin_name)

                for name in obj._command_names:
                    if is_internal:
                        tokens = tuple(name.lower().split())
                        cmd = COMMANDS.get(tokens)

                        if cmd and cmd.role > Role.ADMIN:
                            cmd.role = Role.ADMIN

    # --------------------------------------------------
    # HELPERS
    # --------------------------------------------------

    async def get_plugin_info(self, name):
        """
        Retrieve PLUGIN_META for a plugin.

        Args:
            name (str): Plugin name.

        Returns:
            dict | None: Plugin metadata or None if not found.
        """
        if name in self.meta:
            meta = dict(self.meta[name])
            meta["source"] = "core" if self.is_core_plugin(name) else "plugins"
            return meta

        try:
            module = await self._import(self._module_path(name))
            meta = dict(getattr(module, "PLUGIN_META", {}) or {})
            meta["source"] = "core" if self.is_core_plugin(name) else "plugins"
            return meta
        except Exception:
            return None

    async def list_detailed(self):
        """
        Get plugin status grouped by source.

        Returns:
            dict: {group: {"loaded": [...], "available": [...]}}
        """
        loaded = set(self.plugins.keys())
        available = set(self.discover()) - loaded

        result = {
            "core": {"loaded": [], "available": []},
            "plugins": {"loaded": [], "available": []},
        }

        for name in loaded:
            group = "core" if self.is_core_plugin(name) else "plugins"
            result[group]["loaded"].append(name)

        for name in available:
            group = "core" if self.is_core_plugin(name) else "plugins"
            result[group]["available"].append(name)

        return result
