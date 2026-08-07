"""Small background task supervisor used by plugins and status output."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol, cast

log = logging.getLogger(__name__)

_COMPLETED_ONE_SHOT_HISTORY_LIMIT = 50


class ExpectedTaskExit(Exception):
    """Signal an intentional service-task exit outside process shutdown."""


class BotLike(Protocol):
    """Minimal bot shape required for plugin task creation."""

    bot_plugins: Any


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def sleep_with_heartbeat(
    bot: Any,
    plugin: str,
    name: str,
    delay: float,
    *,
    interval: float = 300.0,
) -> None:
    """Sleep while keeping a supervised service task heartbeat fresh.

    Long, intentional waits (for example a daily report schedule or RSS
    backoff) must not look like a hung worker to `tasks stale`.  The remaining
    delay is decremented explicitly so tests can replace ``asyncio.sleep``
    without requiring a real monotonic clock advance.
    """
    remaining = max(0.0, float(delay))
    heartbeat_interval = max(1.0, float(interval))
    while remaining > 0:
        supervisor = getattr(bot, "tasks", None)
        heartbeat = getattr(supervisor, "heartbeat", None)
        if callable(heartbeat):
            heartbeat(plugin, name)
        step = min(remaining, heartbeat_interval)
        await asyncio.sleep(step)
        remaining -= step


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
    circuit_state: str = "closed"
    next_restart_at: str | None = None
    kind: str = "one-shot"


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


def _close_unscheduled_awaitable(awaitable: Awaitable[Any]) -> None:
    """Close a coroutine that no task creator accepted.

    Creating the coroutine happens before the task-creation call. If a task
    creator fails synchronously, ownership never transfers and the coroutine
    must be closed explicitly to avoid ``coroutine was never awaited``
    warnings. Other awaitable types do not necessarily expose ``close``.
    """
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()


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
    try:
        manager = getattr(bot, "bot_plugins", None)
        creator = getattr(manager, "create_task", None)
        if _is_plugin_task_creator(creator):
            task_creator = cast(Callable[..., asyncio.Task[Any]], creator)
            return task_creator(plugin, coro, name=name)
        task_coro = cast(Coroutine[Any, Any, Any], coro)
        if _asyncio_create_task_supports_name():
            try:
                return asyncio.create_task(task_coro, name=name)
            except TypeError as exc:
                if "name" not in str(exc):
                    raise
                # Some tests monkeypatch asyncio.create_task with a reduced callable.
                # Fall back to the pre-name signature while production keeps using names.
                return asyncio.create_task(task_coro)
        return asyncio.create_task(task_coro)
    except BaseException:
        _close_unscheduled_awaitable(coro)
        raise


def create_resilient_plugin_task(
    bot: BotLike,
    plugin: str,
    factory: Callable[[], Awaitable[Any]],
    *,
    name: str | None = None,
    max_restarts: int | None = None,
    fallback_creator: Callable[..., asyncio.Task[Any]] | None = None,
    service: bool = True,
) -> asyncio.Task[Any]:
    """Create a restartable supervised task when the runtime supports it."""
    manager = getattr(bot, "bot_plugins", None)
    creator = getattr(manager, "create_resilient_task", None)
    if callable(creator) and not _is_test_mock(creator):
        return creator(
            plugin,
            factory,
            name=name,
            max_restarts=max_restarts,
            service=service,
        )
    supervisor = getattr(bot, "tasks", None)
    resilient = getattr(supervisor, "create_resilient", None)
    if callable(resilient) and not _is_test_mock(resilient):
        return resilient(
            plugin,
            factory,
            name=name,
            max_restarts=max_restarts,
            service=service,
        )
    creator = fallback_creator or create_plugin_task
    return creator(bot, plugin, factory(), name=name)


class TaskSupervisor:
    """Track plugin background tasks and cancel them on unload/shutdown."""

    def __init__(self, bot: Any | None = None):
        self.bot = bot
        self._tasks: dict[asyncio.Task[Any], dict[str, Any]] = {}
        self._by_plugin: dict[str, set[asyncio.Task[Any]]] = {}

    def create(
        self,
        plugin: str,
        coro: Awaitable[Any],
        *,
        name: str | None = None,
        kind: str = "one-shot",
    ) -> asyncio.Task[Any]:
        """Create and track a task for a plugin."""
        task_name = name or f"{plugin}-task"
        task_coro = cast(Coroutine[Any, Any, Any], coro)
        task: asyncio.Task[Any]
        if _asyncio_create_task_supports_name():
            try:
                task = asyncio.create_task(task_coro, name=task_name)
            except TypeError as exc:
                if "name" not in str(exc):
                    raise
                # Some tests monkeypatch asyncio.create_task with a reduced callable.
                task = asyncio.create_task(task_coro)
        else:
            task = asyncio.create_task(task_coro)
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
            "circuit_state": "closed",
            "next_restart_at": None,
            "kind": kind,
        }
        self._tasks[task] = meta
        self._by_plugin.setdefault(plugin, set()).add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def create_resilient(
        self,
        plugin: str,
        factory: Callable[[], Awaitable[Any]],
        *,
        name: str | None = None,
        max_restarts: int | None = None,
        initial_backoff: float | None = None,
        max_backoff: float | None = None,
        reset_after: float | None = None,
        service: bool = True,
    ) -> asyncio.Task[Any]:
        """Create a worker protected by restart backoff and a circuit breaker."""
        config = getattr(self.bot, "config", {}) if self.bot is not None else {}
        config = config or {}
        restart_limit = max(0, int(
            config.get("task_restart_max_attempts", 5)
            if max_restarts is None else max_restarts
        ))
        initial = max(0.0, float(
            config.get("task_restart_initial_seconds", 5.0)
            if initial_backoff is None else initial_backoff
        ))
        maximum = max(initial, float(
            config.get("task_restart_max_seconds", 300.0)
            if max_backoff is None else max_backoff
        ))
        reset = max(0.0, float(
            config.get("task_restart_reset_seconds", 900.0)
            if reset_after is None else reset_after
        ))
        task_name = name or f"{plugin}-task"
        return self.create(
            plugin,
            self._resilient_runner(
                plugin,
                task_name,
                factory,
                restart_limit=restart_limit,
                initial_backoff=initial,
                max_backoff=maximum,
                reset_after=reset,
                service=service,
            ),
            name=task_name,
            kind="service" if service else "one-shot",
        )

    async def _notify_circuit_open(self, plugin: str, name: str, error: str) -> None:
        if self.bot is None:
            return
        try:
            alerts = getattr(self.bot, "alerts", None)
            report = getattr(alerts, "report_task_circuit", None)
            if callable(report):
                await report(plugin, name, error)
                return

            from utils.admin_notify import notify_admin

            await notify_admin(
                self.bot,
                "🔴 Background task circuit opened\n"
                f"Plugin: {plugin}\nTask: {name}\nError: {error}",
                category="task_failure",
                dedupe_key=f"task-circuit:{plugin}:{name}:{error}",
            )
        except Exception:
            log.exception("[TASKS] Failed to notify admin about open circuit")

    async def _resilient_runner(
        self,
        plugin: str,
        name: str,
        factory: Callable[[], Awaitable[Any]],
        *,
        restart_limit: int,
        initial_backoff: float,
        max_backoff: float,
        reset_after: float,
        service: bool,
    ) -> Any:
        await asyncio.sleep(0)
        consecutive = 0
        while True:
            started = asyncio.get_running_loop().time()
            try:
                result = await factory()
                if service:
                    raise RuntimeError("service task exited unexpectedly")
            except asyncio.CancelledError:
                raise
            except ExpectedTaskExit:
                return None
            except Exception as exc:
                run_seconds = asyncio.get_running_loop().time() - started
                if reset_after and run_seconds >= reset_after:
                    consecutive = 0
                consecutive += 1
                task = asyncio.current_task()
                meta = self._tasks.get(task, {}) if task is not None else {}
                meta["restart_count"] = int(meta.get("restart_count") or 0) + 1
                meta["last_error"] = f"{type(exc).__name__}: {exc}"
                if consecutive > restart_limit:
                    meta["circuit_state"] = "open"
                    meta["next_restart_at"] = None
                    error = str(meta["last_error"] or "unknown error")
                    await self._notify_circuit_open(plugin, name, error)
                    raise RuntimeError(
                        f"task circuit open after {restart_limit} restart(s): {error}"
                    ) from exc
                delay = min(
                    max_backoff,
                    initial_backoff * (2 ** max(0, consecutive - 1)),
                )
                next_at = datetime.now(UTC).timestamp() + delay
                meta["circuit_state"] = "half-open"
                meta["next_restart_at"] = datetime.fromtimestamp(
                    next_at, UTC
                ).isoformat(timespec="seconds")
                log.warning(
                    "[TASKS] Restarting %s/%s in %.1fs after failure %d/%d: %s",
                    plugin,
                    name,
                    delay,
                    consecutive,
                    restart_limit,
                    exc,
                )
                await asyncio.sleep(delay)
                meta["circuit_state"] = "closed"
                meta["next_restart_at"] = None
                continue
            else:
                task = asyncio.current_task()
                meta = self._tasks.get(task, {}) if task is not None else {}
                meta["circuit_state"] = "closed"
                meta["next_restart_at"] = None
                meta["last_error"] = None
                return result

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
        elif meta.get("kind") != "service":
            self._prune_completed_one_shot_history()

    def _prune_completed_one_shot_history(self) -> None:
        """Keep recent successful one-shots for UX without leaking task metadata."""
        completed = [
            task
            for task, meta in self._tasks.items()
            if task.done()
            and not task.cancelled()
            and meta.get("kind") != "service"
            and meta.get("last_error") is None
        ]
        excess = len(completed) - _COMPLETED_ONE_SHOT_HISTORY_LIMIT
        for task in completed[: max(0, excess)]:
            self._forget_task(task)

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
        now = datetime.now(UTC)
        stale: list[TaskInfo] = []
        for info in self.snapshot(include_done=False):
            if info.status != "running" or not info.heartbeat_at:
                continue
            try:
                heartbeat = datetime.fromisoformat(info.heartbeat_at)
                if heartbeat.tzinfo is None:
                    heartbeat = heartbeat.replace(tzinfo=UTC)
                age = (now - heartbeat.astimezone(UTC)).total_seconds()
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
            done, pending = await asyncio.wait({task}, timeout=timeout)
            if pending:
                log.warning(
                    "[TASKS] Plugin task did not stop in time: %s",
                    task.get_name(),
                )
                return True

            for done_task in done:
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    continue
                except Exception as exc:
                    log.debug(
                        "[TASKS] Task raised during cancellation",
                        exc_info=exc,
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
        pending: set[asyncio.Task[Any]] = set()
        if running_tasks:
            done, pending = await asyncio.wait(running_tasks, timeout=timeout)
            for task in pending:
                log.warning(
                    "[TASKS] Plugin task did not stop in time: %s",
                    task.get_name(),
                )

            for done_task in done:
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    continue
                except Exception as exc:
                    log.debug(
                        "[TASKS] Task raised during cancellation",
                        exc_info=exc,
                    )

        for task in plugin_tasks:
            if task not in pending:
                self._prune_task_unless_failed(task)
        return len(running_tasks)

    def clear_plugin_failures(self, plugin: str) -> int:
        """Forget completed failure and open-circuit diagnostics for a plugin.

        A successful manual task restart is an explicit circuit reset. Keeping
        the old failed runner afterward would make ``tasks`` and ``doctor``
        continue to report an open circuit even though a replacement worker is
        running.
        """
        failed_tasks = [
            task
            for task, meta in tuple(self._tasks.items())
            if meta.get("plugin") == plugin
            and task.done()
            and meta.get("last_error") is not None
        ]
        for task in failed_tasks:
            self._forget_task(task)
        return len(failed_tasks)

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
                    circuit_state=str(meta.get("circuit_state") or "closed"),
                    next_restart_at=meta.get("next_restart_at"),
                    kind=str(meta.get("kind") or "one-shot"),
                )
            )
        return sorted(items, key=lambda item: (item.plugin, item.name))

    def summary_by_kind(self) -> dict[str, int]:
        """Return operator-friendly task counts split by lifecycle kind."""
        counts = {
            "services_running": 0,
            "one_shots_running": 0,
            "one_shots_completed": 0,
            "services_finished": 0,
            "failed": 0,
            "cancelled": 0,
        }
        for info in self.snapshot(include_done=True):
            if info.status == "failed":
                counts["failed"] += 1
            elif info.status == "cancelled":
                counts["cancelled"] += 1
            elif info.status == "running":
                key = (
                    "services_running"
                    if info.kind == "service"
                    else "one_shots_running"
                )
                counts[key] += 1
            elif info.kind == "service":
                counts["services_finished"] += 1
            else:
                counts["one_shots_completed"] += 1
        return counts

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
