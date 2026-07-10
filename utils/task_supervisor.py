"""Small background task supervisor used by plugins and status output."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Awaitable, Protocol

log = logging.getLogger(__name__)


class PluginTaskCreator(Protocol):
    """Callable shape exposed by PluginManager.create_task."""

    def __call__(
        self,
        plugin: str,
        coro: Awaitable[Any],
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        """Create and return a supervised plugin task."""
        raise NotImplementedError


class BotLike(Protocol):
    """Minimal bot shape required for plugin task creation."""

    bot_plugins: Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class TaskInfo:
    """Read-only task state for status output and diagnostics."""

    plugin: str
    name: str
    status: str
    created_at: str
    done_at: str | None
    cancelled: bool
    last_error: str | None
    heartbeat_at: str | None = None
    restart_count: int = 0


def _is_test_mock(candidate: object) -> bool:
    """Return whether *candidate* looks like a unittest.mock object.

    The supervisor runs in production code, so it intentionally avoids importing
    testing utilities. Tests often use Mock/MagicMock placeholders, though, and
    those should not be treated as real PluginManager.create_task methods.
    """
    candidate_type = type(candidate)
    candidate_module = getattr(candidate_type, "__module__", "")
    candidate_name = getattr(candidate_type, "__name__", "")
    return candidate_module == "unittest.mock" and candidate_name in {
        "Mock",
        "MagicMock",
        "AsyncMock",
    }


def _is_plugin_task_creator(candidate: object) -> bool:
    """Return whether *candidate* looks like PluginManager.create_task."""
    if not callable(candidate) or _is_test_mock(candidate):
        return False
    try:
        signature = inspect.signature(candidate)
    except (TypeError, ValueError):
        return False

    params = list(signature.parameters.values())
    has_name_keyword = any(
        param.name == "name"
        and param.kind in (param.KEYWORD_ONLY, param.POSITIONAL_OR_KEYWORD)
        for param in params
    )
    if not has_name_keyword:
        return False

    positional = [
        param
        for param in params
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
    ]
    has_varargs = any(param.kind == param.VAR_POSITIONAL for param in params)
    return has_varargs or len(positional) >= 2


@lru_cache(maxsize=1)
def _asyncio_create_task_supports_name() -> bool:
    """Return whether asyncio.create_task accepts a task name keyword."""
    try:
        return "name" in inspect.signature(asyncio.create_task).parameters
    except (TypeError, ValueError):
        return True


def create_plugin_task(
    bot: BotLike,
    plugin: str,
    coro: Awaitable[Any],
    *,
    name: str | None = None,
) -> asyncio.Task[Any]:
    """Create a supervised task when available, otherwise a plain task.

    The fallback keeps unit-test doubles and small plugin tests simple while
    production bots still get supervised lifecycle handling.

    Args:
        bot: Bot-like object that may expose ``bot_plugins.create_task``.
        plugin: Plugin identifier used for task supervision.
        coro: Awaitable to schedule as an asyncio task.
        name: Optional task name forwarded to the task creator when supported.

    Returns:
        The created asyncio task.
    """
    manager = getattr(bot, "bot_plugins", None)
    creator = getattr(manager, "create_task", None)
    if _is_plugin_task_creator(creator):
        return creator(plugin, coro, name=name)
    if _asyncio_create_task_supports_name():
        try:
            return asyncio.create_task(coro, name=name)
        except TypeError as exc:
            if "name" not in str(exc):
                raise
            # Some tests monkeypatch asyncio.create_task with a reduced callable.
            # Fall back to the pre-name signature while production keeps using names.
            return asyncio.create_task(coro)
    return asyncio.create_task(coro)


class TaskSupervisor:
    """Track plugin background tasks and cancel them on unload/shutdown."""

    def __init__(self):
        self._tasks: dict[asyncio.Task[Any], dict[str, Any]] = {}
        self._by_plugin: dict[str, set[asyncio.Task[Any]]] = {}

    def create(
        self,
        plugin: str,
        coro: Awaitable[Any],
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        """Create and track a task for a plugin."""
        task_name = name or f"{plugin}-task"
        if _asyncio_create_task_supports_name():
            try:
                task = asyncio.create_task(coro, name=task_name)
            except TypeError as exc:
                if "name" not in str(exc):
                    raise
                # Some tests monkeypatch asyncio.create_task with a reduced callable.
                task = asyncio.create_task(coro)
        else:
            task = asyncio.create_task(coro)
        meta = {
            "plugin": plugin,
            "name": task_name,
            "created_at": _now(),
            "done_at": None,
            "last_error": None,
            # A heartbeat is only meaningful after the task explicitly reports one.
            # Initializing it with the creation time makes intentionally sleeping
            # workers look stale even though they are healthy and still running.
            "heartbeat_at": None,
            "restart_count": 0,
        }
        self._tasks[task] = meta
        self._by_plugin.setdefault(plugin, set()).add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        meta = self._tasks.get(task)
        if not meta:
            log.debug(
                "[TASKS] Done callback for untracked task; metadata missing: %r",
                task,
            )
            return
        meta["done_at"] = _now()
        plugin = meta["plugin"]
        self._by_plugin.get(plugin, set()).discard(task)
        if task.cancelled():
            return

        try:
            exc = task.exception()
        except asyncio.InvalidStateError:
            log.debug(
                "[TASKS] Task exception unavailable due to invalid state: %r",
                task,
            )
            return

        if exc is not None:
            meta["last_error"] = f"{type(exc).__name__}: {exc}"
            log.error(
                "[TASKS] Background task failed: %s.%s",
                plugin,
                meta["name"],
                exc_info=exc,
            )

    def _forget_task(self, task: asyncio.Task[Any]) -> None:
        """Remove a task from supervisor indexes."""
        meta = self._tasks.pop(task, None)
        if not meta:
            return
        plugin_tasks = self._by_plugin.get(meta["plugin"])
        if plugin_tasks is not None:
            plugin_tasks.discard(task)
            if not plugin_tasks:
                self._by_plugin.pop(meta["plugin"], None)

    def _prune_task_unless_failed(self, task: asyncio.Task[Any]) -> None:
        """Remove task metadata unless it should be kept for failure diagnostics."""
        meta = self._tasks.get(task, {})
        has_error = meta.get("last_error") is not None
        keep_for_diagnostics = has_error and task.done() and not task.cancelled()
        if not keep_for_diagnostics:
            self._forget_task(task)

    def heartbeat(self, plugin: str, name: str | None = None) -> bool:
        """Update heartbeat timestamp for a running task by plugin/name."""
        for task, meta in tuple(self._tasks.items()):
            if task.done():
                continue
            if meta.get("plugin") != plugin:
                continue
            if name is not None and meta.get("name") != name:
                continue
            meta["heartbeat_at"] = _now()
            return True
        return False

    def touch(self, task: asyncio.Task[Any]) -> bool:
        """Update heartbeat timestamp for a specific supervised task."""
        meta = self._tasks.get(task)
        if meta is None or task.done():
            return False
        meta["heartbeat_at"] = _now()
        return True

    def stale_tasks(self, *, max_age_seconds: float = 3600.0) -> list[TaskInfo]:
        """Return running tasks whose heartbeat is older than max_age_seconds."""
        now = datetime.now(timezone.utc)
        stale: list[TaskInfo] = []
        for info in self.snapshot(include_done=False):
            if info.status != "running" or not info.heartbeat_at:
                continue
            try:
                heartbeat = datetime.fromisoformat(info.heartbeat_at)
                if heartbeat.tzinfo is None:
                    heartbeat = heartbeat.replace(tzinfo=timezone.utc)
                age = (now - heartbeat.astimezone(timezone.utc)).total_seconds()
            except Exception:
                age = max_age_seconds + 1
            if age > max_age_seconds:
                stale.append(info)
        return stale

    async def cancel_task(
        self,
        task: asyncio.Task[Any],
        *,
        timeout: float = 5.0,
    ) -> bool:
        """Cancel one supervised task and remove normal cancellation noise.

        This is useful for plugins that restart one worker without unloading the
        whole plugin. Failed tasks remain visible for diagnostics, while
        successful or cancelled tasks are pruned from task status output.

        Returns:
            Whether a running task was requested to cancel.
        """
        was_running = not task.done()
        if was_running:
            task.cancel()
            gather_future = asyncio.gather(task, return_exceptions=True)
            try:
                results = await asyncio.wait_for(gather_future, timeout=timeout)
            except asyncio.TimeoutError:
                gather_future.cancel()
                try:
                    await gather_future
                except asyncio.CancelledError:
                    log.debug(
                        "[TASKS] Timed-out task future cancelled during cleanup"
                    )
                log.warning(
                    "[TASKS] Plugin task did not stop in time: %s",
                    task.get_name(),
                )
                return True

            for result in results:
                if isinstance(result, asyncio.CancelledError):
                    continue
                if isinstance(result, Exception):
                    log.debug(
                        "[TASKS] Task raised during cancellation",
                        exc_info=result,
                    )

        self._prune_task_unless_failed(task)
        return was_running

    async def cancel_plugin(self, plugin: str, *, timeout: float = 5.0) -> int:
        """Cancel all tasks owned by a plugin and prune finished noise.

        Plugins often cancel their own workers in ``on_unload`` before the
        manager calls into the supervisor.  Those tasks are already done by the
        time we get here, so looking only at running tasks leaves stale
        ``cancelled`` entries in ``tasks all``.  Snapshot all tasks for the
        plugin, cancel only the running ones, then prune every non-failed task.

        Returns:
            Number of running tasks that were requested to cancel.
        """
        plugin_tasks = [
            task
            for task, meta in tuple(self._tasks.items())
            if meta.get("plugin") == plugin
        ]
        running_tasks = [task for task in plugin_tasks if not task.done()]
        for task in running_tasks:
            task.cancel()
        if running_tasks:
            gather_future = asyncio.gather(*running_tasks, return_exceptions=True)
            results: list[Any] = []
            try:
                results = await asyncio.wait_for(gather_future, timeout=timeout)
            except asyncio.TimeoutError:
                gather_future.cancel()
                try:
                    await gather_future
                except asyncio.CancelledError:
                    log.debug(
                        "[TASKS] Timed-out gather future cancelled during cleanup"
                    )

                pending = {task for task in running_tasks if not task.done()}
                for task in pending:
                    log.warning(
                        "[TASKS] Plugin task did not stop in time: %s",
                        task.get_name(),
                    )

                finished = [task for task in running_tasks if task.done()]
                if finished:
                    results = await asyncio.gather(*finished, return_exceptions=True)
                else:
                    results = []

            for result in results:
                if isinstance(result, asyncio.CancelledError):
                    continue
                if isinstance(result, Exception):
                    log.debug(
                        "[TASKS] Task raised during cancellation",
                        exc_info=result,
                    )

        for task in plugin_tasks:
            self._prune_task_unless_failed(task)
        return len(running_tasks)

    async def cancel_all(self, *, timeout: float = 5.0) -> int:
        """Cancel all running supervised tasks.

        Returns:
            Total number of running tasks cancelled across all plugins.
        """
        plugins = list(self._by_plugin)
        total = 0
        for plugin in plugins:
            total += await self.cancel_plugin(plugin, timeout=timeout)
        return total

    def snapshot(self, *, include_done: bool = True) -> list[TaskInfo]:
        """Return a stable snapshot of supervised task states."""
        items = []
        for task, meta in tuple(self._tasks.items()):
            if task.done():
                cancelled = task.cancelled()
                last_error = meta.get("last_error")

                if not include_done and (cancelled or last_error is None):
                    continue

                if cancelled:
                    status = "cancelled"
                elif last_error:
                    status = "failed"
                else:
                    status = "done"
            else:
                cancelled = False
                last_error = meta.get("last_error")
                status = "running"
            items.append(
                TaskInfo(
                    plugin=meta["plugin"],
                    name=meta["name"],
                    status=status,
                    created_at=meta["created_at"],
                    done_at=meta.get("done_at"),
                    cancelled=cancelled,
                    last_error=last_error,
                    heartbeat_at=meta.get("heartbeat_at"),
                    restart_count=int(meta.get("restart_count") or 0),
                )
            )
        return sorted(items, key=lambda item: (item.plugin, item.name))

    def summary(self) -> tuple[int, int, int]:
        """Return (running, failed, done_or_cancelled) counts."""
        running = failed = finished = 0
        for info in self.snapshot(include_done=True):
            if info.status == "running":
                running += 1
            elif info.status == "failed":
                failed += 1
            else:
                finished += 1
        return running, failed, finished
