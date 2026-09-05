"""Small background task supervisor used by plugins and status output."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, cast

from utils.time_utils import utc_now

log = logging.getLogger(__name__)

from envs_xmpp_core.runtime.tasks import (
    ExpectedTaskExit as CoreExpectedTaskExit,
)
from envs_xmpp_core.runtime.tasks import (
    SupervisorOptions,
)
from envs_xmpp_core.runtime.tasks import (
    TaskSupervisor as CoreTaskSupervisor,
)

_COMPLETED_ONE_SHOT_HISTORY_LIMIT = 50


ExpectedTaskExit = CoreExpectedTaskExit

class BotLike(Protocol):
    """Minimal bot shape required for plugin task creation."""

    bot_plugins: Any


def _now() -> str:
    return utc_now().isoformat(timespec="seconds")


def runtime_is_ready(bot: Any) -> bool:
    """Return whether autonomous runtime work may proceed.

    Bots created before the readiness gate (and lightweight test doubles) keep
    the historical immediate behavior by omitting ``runtime_ready``.
    """
    runtime_ready = getattr(bot, "runtime_ready", None)
    if runtime_ready is None:
        return True
    is_set = getattr(runtime_ready, "is_set", None)
    return bool(is_set()) if callable(is_set) else True


async def wait_for_runtime_ready(
    bot: Any,
    *,
    plugin: str | None = None,
    name: str | None = None,
) -> None:
    """Wait until startup releases background work and mark service progress."""
    if not runtime_is_ready(bot):
        runtime_ready = getattr(bot, "runtime_ready", None)
        wait = getattr(runtime_ready, "wait", None)
        if callable(wait):
            await wait()
    if plugin is not None and name is not None:
        _touch_heartbeat(bot, plugin, name)


def task_heartbeat_interval(bot: Any, *, maximum: float = 30.0) -> float:
    """Return a heartbeat cadence that stays safely below the stale threshold.

    Operators may tune ``TASK_STALE_AFTER_SECONDS`` below the historical
    five-minute heartbeat cadence.  A 30-second absolute ceiling also keeps an
    in-progress wait safe when the threshold is lowered by runtime reload.
    """
    config = getattr(bot, "config", {}) or {}
    try:
        stale_after = float(config.get("task_stale_after_seconds", 3600.0) or 3600.0)
    except (TypeError, ValueError):
        stale_after = 3600.0
    safe_maximum = max(0.05, float(maximum))
    return max(0.05, min(safe_maximum, max(0.05, stale_after / 2.0)))


def _touch_heartbeat(bot: Any, plugin: str, name: str) -> None:
    supervisor = getattr(bot, "tasks", None)
    heartbeat = getattr(supervisor, "heartbeat", None)
    if callable(heartbeat):
        heartbeat(plugin, name)


async def sleep_with_heartbeat(
    bot: Any,
    plugin: str,
    name: str,
    delay: float,
    *,
    interval: float = 30.0,
) -> None:
    """Sleep while keeping a supervised service task heartbeat fresh.

    Long, intentional waits (for example a daily report schedule or RSS
    backoff) must not look like a hung worker to `tasks stale`.  The cadence is
    capped by half of the configured stale threshold so custom operator values
    remain safe.  The remaining delay is decremented explicitly so tests can
    replace ``asyncio.sleep`` without requiring a real monotonic clock advance.
    """
    remaining = max(0.0, float(delay))
    heartbeat_interval = task_heartbeat_interval(bot, maximum=interval)
    while remaining > 0:
        _touch_heartbeat(bot, plugin, name)
        step = min(remaining, heartbeat_interval)
        await asyncio.sleep(step)
        remaining -= step


async def wait_for_event_with_heartbeat(
    bot: Any,
    plugin: str,
    name: str,
    event: asyncio.Event,
    delay: float,
    *,
    interval: float = 30.0,
) -> bool:
    """Wait up to ``delay`` seconds for an event while refreshing heartbeat.

    Returns ``True`` when the event became set and ``False`` when the complete
    delay elapsed.  This is the event-aware counterpart to
    :func:`sleep_with_heartbeat` for stoppable/wakeable service loops.
    """
    remaining = max(0.0, float(delay))
    heartbeat_interval = task_heartbeat_interval(bot, maximum=interval)
    while remaining > 0 and not event.is_set():
        _touch_heartbeat(bot, plugin, name)
        step = min(remaining, heartbeat_interval)
        try:
            await asyncio.wait_for(event.wait(), timeout=step)
            return True
        except TimeoutError:
            remaining -= step
    return event.is_set()


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



class TaskSupervisor(CoreTaskSupervisor):
    """Compatibility facade preserving envsbot's plugin-facing API."""

    def __init__(self, bot: Any | None = None):
        self.bot = bot
        config = getattr(bot, "config", {}) if bot is not None else {}
        config = config or {}
        options = SupervisorOptions(
            max_restarts=max(0, int(config.get("task_restart_max_attempts", 5) or 0)),
            initial_backoff=max(0.0, float(config.get("task_restart_initial_seconds", 5.0) or 0.0)),
            max_backoff=max(0.0, float(config.get("task_restart_max_seconds", 300.0) or 0.0)),
            reset_after=max(0.0, float(config.get("task_restart_reset_seconds", 900.0) or 0.0)),
            stale_after=max(0.05, float(config.get("task_stale_after_seconds", 3600.0) or 3600.0)),
        )
        super().__init__(options, on_circuit_open=self._envs_circuit_open)
        self._by_plugin = self._by_scope

    def create(
        self,
        plugin: str,
        coro: Awaitable[Any],
        *,
        name: str | None = None,
        kind: str = "one-shot",
    ) -> asyncio.Task[Any]:
        """Create a core task while preserving envsbot's private metadata key."""
        task = super().create(plugin, coro, name=name, kind=kind)
        meta = self._tasks.get(task)
        if meta is not None:
            meta["plugin"] = plugin
        return task

    async def _envs_circuit_open(self, plugin: str, name: str, error: str) -> None:
        if self.bot is None:
            return
        alerts = getattr(self.bot, "alerts", None)
        report = getattr(alerts, "report_task_circuit", None)
        if callable(report):
            await report(plugin, name, error)
            return
        try:
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

    async def _sleep_with_heartbeat(self, plugin: str, name: str, delay: float) -> None:
        await sleep_with_heartbeat(self.bot, plugin, name, delay)


    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        if task not in self._tasks:
            log.debug("[TASKS] Done callback for untracked task; metadata missing: %r", task)
            return
        super()._on_task_done(task)

    def _prune_completed_one_shot_history(self) -> None:
        completed = [
            task for task, meta in self._tasks.items()
            if task.done()
            and not task.cancelled()
            and meta.get("kind") != "service"
            and meta.get("last_error") is None
        ]
        excess = len(completed) - _COMPLETED_ONE_SHOT_HISTORY_LIMIT
        for task in completed[: max(0, excess)]:
            self._forget_task(task)

    async def cancel_task(
        self,
        task: asyncio.Task[Any],
        *,
        timeout: float = 5.0,
    ) -> bool:
        was_running = not task.done()
        if was_running:
            task.cancel()
            done, pending = await asyncio.wait({task}, timeout=timeout)
            if pending:
                log.warning("[TASKS] Plugin task did not stop in time: %s", task.get_name())
                return True
            for done_task in done:
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    continue
                except Exception as exc:
                    log.debug("[TASKS] Task raised during cancellation", exc_info=exc)
        self._prune_task_unless_failed(task)
        return was_running

    async def cancel_plugin(self, plugin: str, *, timeout: float = 5.0) -> int:
        plugin_tasks = [
            task for task, meta in tuple(self._tasks.items())
            if meta.get("scope") == plugin
        ]
        running_tasks = [task for task in plugin_tasks if not task.done()]
        for task in running_tasks:
            task.cancel()
        pending: set[asyncio.Task[Any]] = set()
        if running_tasks:
            done, pending = await asyncio.wait(running_tasks, timeout=timeout)
            for task in pending:
                log.warning("[TASKS] Plugin task did not stop in time: %s", task.get_name())
            for done_task in done:
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    continue
                except Exception as exc:
                    log.debug("[TASKS] Task raised during cancellation", exc_info=exc)
        for task in plugin_tasks:
            if task not in pending:
                self._prune_task_unless_failed(task)
        return len(running_tasks)

    def clear_plugin_failures(self, plugin: str) -> int:
        return super().clear_scope_failures(plugin)

    def snapshot(self, *, include_done: bool = True) -> list[TaskInfo]:
        return [
            TaskInfo(
                plugin=item.scope,
                name=item.name,
                status=item.status,
                created_at=item.created_at,
                done_at=item.done_at,
                cancelled=item.cancelled,
                last_error=item.last_error,
                heartbeat_at=item.heartbeat_at,
                restart_count=item.restart_count,
                circuit_state=item.circuit_state,
                next_restart_at=item.next_restart_at,
                kind=item.kind,
            )
            for item in super().snapshot(include_done=include_done)
        ]
