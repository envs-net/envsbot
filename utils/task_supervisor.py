"""Small background task supervisor used by plugins and status output."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable

log = logging.getLogger(__name__)


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


def create_plugin_task(bot, plugin: str, coro: Awaitable, *, name: str | None = None) -> asyncio.Task:
    """Create a supervised task when available, otherwise a plain task.

    The fallback keeps unit-test doubles and small plugin tests simple while
    production bots still get supervised lifecycle handling.
    """
    try:
        from unittest.mock import Mock
    except Exception:  # pragma: no cover - defensive for unusual runtimes
        Mock = ()

    manager = getattr(bot, "bot_plugins", None)
    creator = getattr(manager, "create_task", None)
    if callable(creator) and not isinstance(creator, Mock):
        return creator(plugin, coro, name=name)
    try:
        return asyncio.create_task(coro, name=name)
    except TypeError:
        return asyncio.create_task(coro)


class TaskSupervisor:
    """Track plugin background tasks and cancel them on unload/shutdown."""

    def __init__(self):
        self._tasks: dict[asyncio.Task, dict] = {}
        self._by_plugin: dict[str, set[asyncio.Task]] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def create(
        self,
        plugin: str,
        coro: Awaitable,
        *,
        name: str | None = None,
    ) -> asyncio.Task:
        """Create and track a task for a plugin."""
        task_name = name or f"{plugin}-task"
        task = asyncio.create_task(coro, name=task_name)
        meta = {
            "plugin": plugin,
            "name": task_name,
            "created_at": self._now(),
            "done_at": None,
            "last_error": None,
        }
        self._tasks[task] = meta
        self._by_plugin.setdefault(plugin, set()).add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task) -> None:
        meta = self._tasks.get(task)
        if not meta:
            return
        meta["done_at"] = self._now()
        plugin = meta["plugin"]
        self._by_plugin.get(plugin, set()).discard(task)
        try:
            if not task.cancelled():
                exc = task.exception()
                if exc is not None:
                    meta["last_error"] = f"{type(exc).__name__}: {exc}"
                    log.exception(
                        "[TASKS] Background task failed: %s.%s",
                        plugin,
                        meta["name"],
                        exc_info=exc,
                    )
        except asyncio.CancelledError:
            pass

    async def cancel_plugin(self, plugin: str, *, timeout: float = 5.0) -> int:
        """Cancel all running tasks owned by a plugin."""
        tasks = [task for task in self._by_plugin.get(plugin, set()) if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=timeout)
            for task in pending:
                log.warning("[TASKS] Plugin task did not stop in time: %s", task.get_name())
            for task in done:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    log.debug("[TASKS] Task raised during cancellation", exc_info=True)
        return len(tasks)

    async def cancel_all(self, *, timeout: float = 5.0) -> int:
        """Cancel all running supervised tasks."""
        plugins = list(self._by_plugin)
        total = 0
        for plugin in plugins:
            total += await self.cancel_plugin(plugin, timeout=timeout)
        return total

    def snapshot(self, *, include_done: bool = False) -> list[TaskInfo]:
        """Return a stable snapshot of supervised task states."""
        items = []
        for task, meta in tuple(self._tasks.items()):
            if task.done():
                if not include_done and meta.get("last_error") is None:
                    continue
                status = "cancelled" if task.cancelled() else "failed" if meta.get("last_error") else "done"
            else:
                status = "running"
            items.append(
                TaskInfo(
                    plugin=meta["plugin"],
                    name=meta["name"],
                    status=status,
                    created_at=meta["created_at"],
                    done_at=meta.get("done_at"),
                    cancelled=task.cancelled(),
                    last_error=meta.get("last_error"),
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
