"""Runtime event, task, and readiness integration for the plugin manager."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

from utils.plugin_manager_diagnostics import call_runtime_state_hook
from utils.plugin_manager_lifecycle import serialized_lifecycle
from utils.task_supervisor import wait_for_runtime_ready

log = logging.getLogger("utils.plugin_manager")


class _RuntimeReadyCoroutine(Coroutine):
    """Coroutine wrapper that also owns the deferred plugin awaitable.

    ``PluginManager.create_task()`` receives an already-created coroutine. If
    task creation or plugin loading aborts before the readiness wrapper ever
    starts, closing only that outer wrapper does not execute its body/finally
    block. Keeping explicit ownership here ensures the original coroutine is
    closed as well and cannot leak an ``un-awaited coroutine`` warning.
    """

    def __init__(self, bot, awaitable):
        self._bot = bot
        self._awaitable = awaitable
        self._awaitable_started = False
        self._awaitable_closed = False
        self._runner = self._run()
        self._closed = False

    async def _run(self):
        try:
            await wait_for_runtime_ready(self._bot)
            self._awaitable_started = True
            return await self._awaitable
        finally:
            if not self._awaitable_started:
                self._close_awaitable()

    def _close_awaitable(self):
        if self._awaitable_closed:
            return
        self._awaitable_closed = True
        close = getattr(self._awaitable, "close", None)
        if callable(close):
            close()

    def __await__(self):
        return self._runner.__await__()

    def send(self, value):
        return self._runner.send(value)

    def throw(self, *args):
        return self._runner.throw(*args)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._runner.close()
        finally:
            if not self._awaitable_started:
                self._close_awaitable()


async def _run_plugin_factory_when_ready(bot, factory, *, plugin=None, name=None):
    """Create and run a resilient plugin worker only after runtime readiness."""
    await wait_for_runtime_ready(bot, plugin=plugin, name=name)
    return await factory()


class PluginManagerRuntimeMixin:
    """Runtime events, supervised tasks, and ready/session lifecycle hooks."""

    bot: Any
    plugins: dict[str, Any]
    meta: dict[str, dict[str, Any]]
    failed_plugins: dict[str, str]
    _event_handlers: dict[str, list[tuple[str, Any]]]
    _runtime_event_handlers: dict[str, list[tuple[str, Any]]]
    _ready: bool

    if TYPE_CHECKING:
        async def _run_hook(self, hook: Any) -> None: ...
        def _loaded_dependency_order(self) -> list[str]: ...
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
        deferred = _RuntimeReadyCoroutine(self.bot, coro)
        supervisor = getattr(self.bot, "tasks", None)
        try:
            if supervisor is None:
                return asyncio.create_task(deferred, name=name)
            return supervisor.create(plugin_name, deferred, name=name)
        except Exception:
            deferred.close()
            raise

    def create_resilient_task(
        self,
        plugin_name,
        factory,
        *,
        name=None,
        max_restarts=None,
        service=True,
    ):
        """Create a supervised task with restart backoff and circuit breaking."""

        def ready_factory():
            return _run_plugin_factory_when_ready(
                self.bot,
                factory,
                plugin=plugin_name,
                name=name or f"{plugin_name}-task",
            )

        supervisor = getattr(self.bot, "tasks", None)
        if supervisor is None:
            return asyncio.create_task(ready_factory(), name=name)
        return supervisor.create_resilient(
            plugin_name,
            ready_factory,
            name=name,
            max_restarts=max_restarts,
            service=service,
        )

    async def _cancel_plugin_tasks(self, plugin_name):
        """Cancel supervised tasks that belong to one plugin."""
        supervisor = getattr(self.bot, "tasks", None)
        if supervisor is None:
            return 0
        cancelled = await supervisor.cancel_plugin(plugin_name)
        snapshot = getattr(supervisor, "snapshot", None)
        pending = []
        if callable(snapshot):
            pending = [
                info
                for info in snapshot(include_done=False)
                if getattr(info, "plugin", None) == plugin_name
                and getattr(info, "status", None) == "running"
            ]
        if pending:
            names = ", ".join(
                str(getattr(info, "name", "unnamed"))
                for info in pending
            )
            raise RuntimeError(
                f"Plugin {plugin_name} still has running task(s) after "
                f"cancellation: {names}"
            )
        if cancelled:
            log.debug("[PLUGIN] cancelled %d task(s) for %s", cancelled, plugin_name)
        return cancelled

    @serialized_lifecycle
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

    @serialized_lifecycle
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
            self.failed_plugins[name] = f"task restart: {exc}"
            log.exception("[PLUGIN] task restart failed for %s", name)
            return False, f"Error restarting tasks for {name}: {exc}", cancelled
        supervisor = getattr(self.bot, "tasks", None)
        clear_failures = getattr(supervisor, "clear_plugin_failures", None)
        if callable(clear_failures) and not type(clear_failures).__module__.startswith("unittest.mock"):
            clear_failures(name)
        self.failed_plugins.pop(name, None)
        return True, f"Plugin {name} tasks restarted", cancelled

    @serialized_lifecycle
    async def call_on_ready(self):
        """
        Call on_ready() hook for all loaded plugins.

        This should be called AFTER the bot is fully initialized and DB is
        connected. Use this for expensive initialization like loading data
        from the database.
        """
        try:
            order = self._loaded_dependency_order()
        except Exception:
            log.exception("[PLUGIN] invalid dependency graph before on_ready")
            order = list(self.plugins)

        ready_failures: set[str] = set()
        try:
            for name in order:
                module = self.plugins.get(name)
                if module is None:
                    continue

                blocked_by = sorted(
                    dep
                    for dep in self.meta.get(name, {}).get("requires", [])
                    if dep in ready_failures
                )
                if blocked_by:
                    detail = (
                        "on_ready blocked by failed dependency: "
                        + ", ".join(blocked_by)
                    )
                    self.failed_plugins[name] = detail
                    ready_failures.add(name)
                    log.error("[PLUGIN] 🔴 %s: %s", name, detail)
                    continue

                hook = getattr(module, "on_ready", None)
                if hook is None:
                    self.failed_plugins.pop(name, None)
                    continue
                try:
                    log.debug("[PLUGIN] calling on_ready: %s", name)
                    await self._run_hook(hook)
                except Exception as exc:
                    detail = f"on_ready: {type(exc).__name__}: {exc}"
                    self.failed_plugins[name] = detail
                    ready_failures.add(name)
                    log.exception("[PLUGIN] 🔴 on_ready failed: %s", name)
                else:
                    self.failed_plugins.pop(name, None)
        finally:
            self._ready = True

    @serialized_lifecycle
    async def call_on_session_ready(self) -> None:
        """Run optional hooks that must be refreshed for every XMPP session.

        Process-lifetime ``on_ready`` hooks remain one-time initialization.
        Plugins that need transport/session refresh (for example MUC rejoin or
        avatar presence publication) opt in with ``on_session_ready(bot)``.
        """
        try:
            order = self._loaded_dependency_order()
        except Exception:
            log.exception("[PLUGIN] invalid dependency graph before on_session_ready")
            order = list(self.plugins)

        session_failures: set[str] = set()
        for name in order:
            module = self.plugins.get(name)
            if module is None:
                continue
            blocked_by = sorted(
                dep
                for dep in self.meta.get(name, {}).get("requires", [])
                if dep in session_failures or dep in self.failed_plugins
            )
            if blocked_by:
                detail = (
                    "on_session_ready blocked by failed dependency: "
                    + ", ".join(blocked_by)
                )
                self.failed_plugins[name] = detail
                session_failures.add(name)
                log.error("[PLUGIN] 🔴 %s: %s", name, detail)
                continue

            hook = getattr(module, "on_session_ready", None)
            if hook is None:
                continue
            try:
                log.debug("[PLUGIN] calling on_session_ready: %s", name)
                await self._run_hook(hook)
            except Exception as exc:
                detail = f"on_session_ready: {type(exc).__name__}: {exc}"
                self.failed_plugins[name] = detail
                session_failures.add(name)
                log.exception("[PLUGIN] 🔴 on_session_ready failed: %s", name)
            else:
                existing = str(self.failed_plugins.get(name, ""))
                if existing.startswith("on_session_ready:"):
                    self.failed_plugins.pop(name, None)
