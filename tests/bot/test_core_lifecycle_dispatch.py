from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import envsbot
import bot.lifecycle as lifecycle
from utils.command import Role
from utils.permissions import can_manage_room_role


def test_can_manage_room_role_threshold():
    assert can_manage_room_role(Role.OWNER) is True
    assert can_manage_room_role(Role.ADMIN) is True
    assert can_manage_room_role(Role.MODERATOR) is True
    assert can_manage_room_role(Role.USER) is False


class DummyLifecycle(lifecycle.LifecycleMixin):
    def __init__(
        self,
        *,
        unload=None,
        cancel_all=None,
        close_cache=None,
        close=None,
        config=None,
        drain_replies=None,
    ):
        self.accepting_commands = True
        self.runtime_ready = asyncio.Event()
        self.runtime_ready.set()
        self.config = config or {}
        self.bot_plugins = SimpleNamespace(unload_all=unload) if unload is not None else SimpleNamespace()
        self.tasks = SimpleNamespace(cancel_all=cancel_all) if cancel_all is not None else SimpleNamespace()
        self.message_cache = (
            SimpleNamespace(close=close_cache)
            if close_cache is not None
            else SimpleNamespace()
        )
        self.db = SimpleNamespace(close=close or AsyncMock())
        if drain_replies is not None:
            self._drain_reply_tasks = drain_replies


@pytest.mark.asyncio
async def test_shutdown_runtime_orders_plugins_tasks_and_db():
    events: list[str] = []

    async def unload_all():
        events.append("plugins")

    async def cancel_all(timeout):
        events.append(f"tasks:{timeout}")
        return 3

    async def close_cache():
        events.append("cache")

    async def close():
        events.append("db")

    bot = DummyLifecycle(
        unload=unload_all,
        cancel_all=cancel_all,
        close_cache=close_cache,
        close=close,
    )

    assert await bot.shutdown_runtime() is True
    assert await bot.shutdown_runtime() is True

    assert bot.accepting_commands is False
    assert bot.runtime_ready.is_set() is False
    # Supervised cache/DB workers must drain themselves before the global
    # supervisor cancellation so queued persistence is not discarded.
    assert events == ["plugins", "cache", "tasks:10.0", "db"]
    assert [phase.name for phase in bot._last_shutdown_phases] == [
        "alerts",
        "watchdog",
        "replies",
        "plugins",
        "outbox",
        "message_cache",
        "db_workers",
        "tasks",
        "db",
    ]
    assert all(phase.duration_seconds >= 0 for phase in bot._last_shutdown_phases)
    assert all(phase.healthy for phase in bot._last_shutdown_phases)


@pytest.mark.asyncio
async def test_shutdown_runtime_drains_reply_tasks_before_plugins():
    events: list[str] = []

    async def drain_replies(*, timeout):
        events.append(f"replies:{timeout}")
        return 2, 1

    async def unload_all():
        events.append("plugins")

    async def cancel_all(timeout):
        events.append(f"tasks:{timeout}")
        return 0

    async def close_cache():
        events.append("cache")

    async def close():
        events.append("db")

    bot = DummyLifecycle(
        drain_replies=drain_replies,
        unload=unload_all,
        cancel_all=cancel_all,
        close_cache=close_cache,
        close=close,
    )

    assert await bot.shutdown_runtime() is True

    assert events == ["replies:3.0", "plugins", "cache", "tasks:10.0", "db"]


@pytest.mark.asyncio
async def test_shutdown_runtime_handles_skipped_and_failed_components():
    events: list[str] = []

    async def unload_all():
        events.append("plugins")
        raise RuntimeError("plugin failed")

    async def cancel_all(timeout):
        events.append("tasks")
        raise RuntimeError("tasks failed")

    async def close():
        events.append("db")
        raise RuntimeError("db failed")

    bot = DummyLifecycle(unload=unload_all, cancel_all=cancel_all, close=close)
    assert await bot.shutdown_runtime() is False

    assert bot.accepting_commands is False
    assert events == ["plugins", "tasks", "db"]
    failed = {phase.name for phase in bot._last_shutdown_phases if not phase.healthy}
    assert failed == {"plugins", "tasks", "db"}

    skipped = DummyLifecycle(close=AsyncMock())
    assert await skipped.shutdown_runtime() is True
    assert skipped.accepting_commands is False


@pytest.mark.asyncio
async def test_shutdown_runtime_reports_degraded_message_cache(caplog):
    async def close_cache():
        return False

    bot = DummyLifecycle(close_cache=close_cache, close=AsyncMock())

    with caplog.at_level("INFO", logger="bot.lifecycle"):
        assert await bot.shutdown_runtime() is False

    assert "phase=message_cache status=degraded" in caplog.text
    assert "message_cache=degraded" in caplog.text


@pytest.mark.asyncio
async def test_shutdown_runtime_reports_partial_plugin_cleanup(caplog):
    async def unload_all():
        return False, "idlerpg checkpoint failed"

    async def close():
        return None

    bot = DummyLifecycle(unload=unload_all, close=close)

    with caplog.at_level("INFO", logger="bot.lifecycle"):
        assert await bot.shutdown_runtime() is False

    assert "phase=plugins status=partial" in caplog.text
    assert "phase=done" in caplog.text
    assert "status=partial" in caplog.text


@pytest.mark.asyncio
async def test_shutdown_runtime_uses_configured_db_timeout(monkeypatch):
    calls: list[object] = []

    async def close():
        calls.append("db.close")

    async def fake_wait_for(awaitable, timeout):
        calls.append(("wait_for", timeout))
        return await awaitable

    monkeypatch.setattr(lifecycle.asyncio, "wait_for", fake_wait_for)

    bot = DummyLifecycle(
        close=close,
        config={"database_shutdown_timeout_seconds": 17},
    )

    await bot.shutdown_runtime()

    assert ("wait_for", 17.0) in calls
    assert "db.close" in calls


def test_database_shutdown_timeout_has_sane_lower_bound():
    # The configured timeout is clamped to a minimum of 6.0 seconds to avoid
    # unrealistically small values; e.g. 1 second is raised to 6.0.
    assert lifecycle._database_shutdown_timeout({}) == 15.0
    assert lifecycle._database_shutdown_timeout({"database_shutdown_timeout_seconds": 1}) == 6.0
    assert lifecycle._database_shutdown_timeout({"database_shutdown_timeout_seconds": "bad"}) == 15.0


def test_lifecycle_phase_result_health_semantics():
    ok = lifecycle.LifecyclePhaseResult("storage", "ok", 0.01)
    skipped = lifecycle.LifecyclePhaseResult("alerts", "skipped", 0.0)
    degraded = lifecycle.LifecyclePhaseResult("cache", "degraded", 0.02)

    assert ok.healthy is True
    assert skipped.healthy is True
    assert degraded.healthy is False


@pytest.mark.asyncio
async def test_envsbot_wrappers_resolve_permission_and_preflight(monkeypatch):
    from utils.command import COMMANDS, Command

    async def handler():
        return None

    cmd = Command(name="wrapper test", handler=handler, role=Role.ADMIN)
    COMMANDS.register("wrapper test", cmd, plugin="_test")
    try:
        cmd_obj, args = envsbot.resolve_command("wrapper test arg")
        assert cmd_obj is cmd
        assert args == ["arg"]
        assert envsbot.check_permission(Role.OWNER, cmd_obj) is True
        assert envsbot.check_permission(Role.USER, cmd_obj) is False
    finally:
        COMMANDS.remove("wrapper test")

    async def fake_run_preflight(config):
        assert config is envsbot.config
        return 17

    import utils.preflight as preflight

    monkeypatch.setattr(preflight, "run_preflight", fake_run_preflight)
    assert await envsbot.preflight_check() == 17
