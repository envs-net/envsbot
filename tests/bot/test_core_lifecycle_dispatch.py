from __future__ import annotations

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

    await bot.shutdown_runtime()
    await bot.shutdown_runtime()

    assert bot.accepting_commands is False
    assert events == ["plugins", "tasks:10.0", "cache", "db"]




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

    await bot.shutdown_runtime()

    assert events == ["replies:3.0", "plugins", "tasks:10.0", "cache", "db"]


@pytest.mark.asyncio
async def test_shutdown_runtime_handles_skipped_and_failed_components():
    async def unload_all():
        raise RuntimeError("plugin failed")

    async def cancel_all(timeout):
        raise RuntimeError("tasks failed")

    async def close():
        raise RuntimeError("db failed")

    bot = DummyLifecycle(unload=unload_all, cancel_all=cancel_all, close=close)
    await bot.shutdown_runtime()

    assert bot.accepting_commands is False

    skipped = DummyLifecycle(close=AsyncMock())
    await skipped.shutdown_runtime()
    assert skipped.accepting_commands is False


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
