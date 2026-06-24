"""Small background task supervisor used by plugins and status output."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
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
        ...


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
    try:
        return asyncio.create_task(coro, name=name)
    except TypeError:
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
        task = asyncio.create_task(coro, name=task_name)
        meta = {
            "plugin": plugin,
            "name": task_name,
            "created_at": _now(),
            "done_at": None,
            "last_error": None,
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

        exc = task.exception()
        if exc is not None:
            meta["last_error"] = f"{type(exc).__name__}: {exc}"
            log.error(
                "[TASKS] Background task failed: %s.%s",
                plugin,
                meta["name"],
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    async def cancel_plugin(self, plugin: str, *, timeout: float = 5.0) -> int:
        """Cancel all running tasks owned by a plugin.

        Returns:
            Number of running tasks that were requested to cancel.
        """
        tasks = [
            task for task in self._by_plugin.get(plugin, set()) if not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            pending: set[asyncio.Task[Any]] = set()
            results: list[object] = []
            gather_future = asyncio.gather(*tasks, return_exceptions=True)
            try:
                results = await asyncio.wait_for(gather_future, timeout=timeout)
            except asyncio.TimeoutError:
                pending = {task for task in tasks if not task.done()}
                for task in pending:
                    log.warning(
                        "[TASKS] Plugin task did not stop in time: %s",
                        task.get_name(),
                    )

                finished = [task for task in tasks if task.done()]
                if finished:
                    results = await asyncio.gather(*finished, return_exceptions=True)

            for result in results:
                if isinstance(result, asyncio.CancelledError):
                    continue
                if isinstance(result, Exception):
                    log.debug(
                        "[TASKS] Task raised during cancellation",
                        exc_info=(type(result), result, result.__traceback__),
                    )

            plugin_tasks = self._by_plugin.get(plugin)
            if plugin_tasks is not None:
                for task in tasks:
                    plugin_tasks.discard(task)
                    meta = self._tasks.get(task, {})
                    has_error = meta.get("last_error") is not None
                    keep_for_diagnostics = (
                        has_error and task.done() and not task.cancelled()
                    )
                    if not keep_for_diagnostics:
                        self._tasks.pop(task, None)
                if not plugin_tasks:
                    self._by_plugin.pop(plugin, None)
        return len(tasks)

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

                if not include_done and not cancelled and last_error is None:
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
