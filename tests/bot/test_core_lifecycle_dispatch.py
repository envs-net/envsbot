from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import envsbot
import bot.lifecycle as lifecycle
from bot.dispatch import CommandDispatchMixin
from utils.command import Role
from utils.permissions import can_manage_room_role


@pytest.mark.asyncio
async def test_call_with_timeout_success_no_timeout_and_failure():
    async def ok():
        return "done"

    async def boom():
        raise RuntimeError("broken")

    assert await lifecycle.call_with_timeout("ok", ok, timeout=1.0) == "done"
    assert await lifecycle.call_with_timeout("no-timeout", ok, timeout=0) == "done"
    with pytest.raises(RuntimeError, match="broken"):
        await lifecycle.call_with_timeout("boom", boom, timeout=1.0)


class DispatchOnly(CommandDispatchMixin):
    pass


def test_can_execute_command_in_room_edges(monkeypatch):
    bot = DispatchOnly()

    public_cmd = SimpleNamespace(name="dice", role=Role.USER)
    admin_cmd = SimpleNamespace(name="users role", role=Role.ADMIN)
    invite_cmd = SimpleNamespace(name="rooms invite", role=Role.ADMIN)

    assert bot._can_execute_command_in_room(admin_cmd, is_room=False) is True
    assert bot._can_execute_command_in_room(public_cmd, is_room=True, room="room@example.org") is True
    assert bot._can_execute_command_in_room(admin_cmd, is_room=True, room="room@example.org") is False

    import core_plugins.rooms as rooms_plugin

    monkeypatch.setattr(rooms_plugin, "room_invite_admin_rooms", lambda: {"admin@example.org"})
    assert bot._can_execute_command_in_room(invite_cmd, is_room=True, room="ADMIN@example.org") is True
    assert bot._can_execute_command_in_room(invite_cmd, is_room=True, room="other@example.org") is False


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
