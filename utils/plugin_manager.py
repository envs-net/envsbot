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

from __future__ import annotations

import asyncio
import importlib
import pkgutil
import inspect
import logging

from utils.command import COMMANDS, Role
from utils.plugin_manager_dependencies import (
    dependency_conflict,
    get_dependents,
    topological_sort,
)
from utils.plugin_manager_diagnostics import (
    call_doctor_hook,
    call_runtime_state_hook,
)
from utils.plugin_manager_discovery import (
    discover_sources,
    source_info,
    stable_discovery_order,
)
from utils.plugin_manager_lifecycle import (
    detach_module,
    import_module_async,
    run_hook,
)
from utils.plugin_metadata import validate_plugin_metadata

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
        self._runtime_event_handlers = {}
        self._dependents = {}  # Cache: plugin -> plugins that depend on it

        self._lock = asyncio.Lock()

    # --------------------------------------------------
    # DEPENDENCY ANALYSIS
    # --------------------------------------------------

    def _get_dependents(self, name):
        """Find ALL plugins that depend on the given plugin recursively."""
        return get_dependents(self.meta, name)

    def _topological_sort(self, plugin_names):
        """Sort plugins by dependency order, dependencies first."""
        return topological_sort(self.meta, plugin_names)

    def _check_dependency_conflict(self, name: str) -> tuple[bool, str]:
        """Check if unloading a plugin would break other plugins."""
        return dependency_conflict(self.meta, name)

    # --------------------------------------------------
    # SOURCE HELPERS
    # --------------------------------------------------

    def _discover_sources(self):
        """Return plugin source metadata keyed by stable plugin name."""
        return discover_sources(
            self.sources,
            import_module=importlib.import_module,
            iter_modules=pkgutil.iter_modules,
        )

    def _source_info(self, name: str) -> dict:
        """Return source info for a plugin name."""
        return source_info(
            name,
            plugin_sources=self.plugin_sources,
            discover=self._discover_sources,
            multi_source=self._multi_source,
            core_plugins=self.core_plugins,
            core_package=self.core_package,
            package=self.package,
        )

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
        Register an XMPP event handler for a plugin.

        Args:
            plugin_name (str): Name of the plugin.
            event (str): Event name.
            handler (callable): Event handler function.
        """
        self.bot.add_event_handler(event, handler)
        self._event_handlers.setdefault(plugin_name,
                                        []).append((event, handler))

    def register_runtime_event(self, plugin_name, event, handler):
        """Register an internal runtime event handler for a plugin.

        Runtime events are emitted explicitly by envsbot internals and do not
        rely on the XMPP client's event fan-out.  They are useful when a core
        routing path already sees an event and plugins need a guaranteed
        observer hook in addition to the regular XMPP event handlers.
        """
        self._runtime_event_handlers.setdefault(plugin_name, []).append(
            (event, handler)
        )

    async def dispatch_runtime_event(self, event, *args, **kwargs):
        """Dispatch an internal runtime event to registered plugin handlers."""
        handlers = [
            handler
            for plugin_handlers in tuple(self._runtime_event_handlers.values())
            for registered_event, handler in tuple(plugin_handlers)
            if registered_event == event
        ]
        for handler in handlers:
            try:
                result = handler(*args, **kwargs)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("[PLUGIN] runtime event handler failed: %s", event)

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
        """Discover available plugins from all configured sources."""
        discovered = self._discover_sources()
        self.plugin_sources.update(discovered)
        return stable_discovery_order(discovered)

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
        """Deterministically detach a plugin module from the import system."""
        detach_module(module, name, fallback_package=self.package)

    async def _cleanup_failed_load(self, name: str) -> None:
        """Best-effort cleanup after a plugin load failed mid-flight.

        ``on_load`` hooks may already have registered event handlers or
        started supervised tasks before command registration fails. Leaving
        those behind makes the next retry behave differently and can duplicate
        handlers after a failed update/reload.
        """
        for event, handler in self._event_handlers.pop(name, []):
            try:
                self.bot.del_event_handler(event, handler)
            except Exception:
                log.debug(
                    "[PLUGIN] failed to remove event handler after load "
                    "failure: %s.%s",
                    name,
                    event,
                    exc_info=True,
                )

        self._runtime_event_handlers.pop(name, None)

        try:
            await self._cancel_plugin_tasks(name)
        except Exception:
            log.debug(
                "[PLUGIN] failed to cancel plugin tasks after load failure: %s",
                name,
                exc_info=True,
            )

    async def _run_hook(self, hook):
        """Execute a plugin hook safely."""
        await run_hook(self.bot, hook)

    async def _import(self, module_path):
        """Import a module asynchronously."""
        return await import_module_async(
            module_path,
            import_module=importlib.import_module,
        )

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
            for issue in validate_plugin_metadata(name, meta, core=self.is_core_plugin(name)):
                log.warning("[PLUGIN] metadata %s", issue.format())

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
                    # Remove any commands, event handlers, and tasks that
                    # might have been registered by a partially-loaded plugin.
                    COMMANDS.remove_by_plugin(name)
                    await self._cleanup_failed_load(name)
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

                self._runtime_event_handlers.pop(name, None)

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
        """Return plugin-provided runtime state for diagnostics."""
        module = self.plugins.get(name)
        if module is None:
            return {"loaded": False}
        return await call_runtime_state_hook(
            self.bot,
            name,
            getattr(module, "get_runtime_state", None),
            room_jid=room_jid,
        )

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

    async def metadata_issues(self, name: str) -> list:
        """Return metadata validation issues for one plugin."""
        try:
            module = self.plugins.get(name) or await self._import(self._module_path(name))
            meta = getattr(module, "PLUGIN_META", {})
        except Exception as exc:
            from utils.plugin_metadata import PluginMetadataIssue
            return [PluginMetadataIssue(name, "error", f"cannot import metadata: {exc}")]
        return validate_plugin_metadata(name, meta, core=self.is_core_plugin(name))

    async def all_metadata_issues(self) -> list:
        """Return metadata validation issues for all discoverable plugins."""
        issues = []
        for name in self.discover():
            issues.extend(await self.metadata_issues(name))
        return issues

    async def plugin_doctor(self, name: str, room_jid: str | None = None) -> list[str]:
        """Return plugin-provided doctor lines for diagnostics."""
        module = self.plugins.get(name)
        if module is None:
            return [f"🔴 {name}: not loaded"]

        async def _state_getter(plugin_name: str, state_room: str | None):
            return await self.plugin_state(plugin_name, room_jid=state_room)

        return await call_doctor_hook(
            self.bot,
            name,
            getattr(module, "doctor", None),
            room_jid=room_jid,
            state_getter=_state_getter,
        )

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
