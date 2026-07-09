from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import core_plugins.tasks as tasks_plugin
from utils.task_supervisor import TaskInfo


class Supervisor:
    def __init__(self, tasks):
        self._tasks = tasks

    def snapshot(self, *, include_done=True):
        assert include_done is True
        return list(self._tasks)


@pytest.fixture
def msg():
    return MagicMock()


@pytest.fixture
def bot():
    bot = MagicMock()
    bot.reply = MagicMock()
    bot.reply_warn = MagicMock()
    bot.reply_usage = MagicMock()
    bot.tasks = Supervisor([
        TaskInfo(
            plugin="rss",
            name="feed-loop",
            status="running",
            created_at="2026-06-22T10:00:00+00:00",
            done_at=None,
            cancelled=False,
            last_error=None,
        ),
        TaskInfo(
            plugin="xkcd",
            name="index-update",
            status="done",
            created_at="2026-06-22T09:00:00+00:00",
            done_at="2026-06-22T09:00:10+00:00",
            cancelled=False,
            last_error=None,
        ),
        TaskInfo(
            plugin="birthday_notify",
            name="birthday-loop",
            status="failed",
            created_at="2026-06-22T08:00:00+00:00",
            done_at="2026-06-22T08:01:00+00:00",
            cancelled=False,
            last_error="RuntimeError: boom",
        ),
    ])
    return bot


@pytest.mark.asyncio
async def test_tasks_default_lists_summary_and_compact_lines(bot, msg):
    await tasks_plugin.tasks_command(bot, "admin@example.org", "admin", [], msg, False)

    reply = bot.reply.call_args.args[1]
    assert reply[0] == "🧵 Background tasks"
    assert "Summary: 1 running, 1 failed, 0 cancelled, 1 done" in reply
    assert any("rss/feed-loop — running" in line for line in reply)
    assert any("birthday_notify/birthday-loop — failed" in line for line in reply)


@pytest.mark.asyncio
async def test_tasks_full_includes_details(bot, msg):
    await tasks_plugin.tasks_command(bot, "admin@example.org", "admin", ["full"], msg, False)

    reply = bot.reply.call_args.args[1]
    assert any("status = running" in line for line in reply)
    assert any("created_at = 2026-06-22T10:00:00+00:00" in line for line in reply)
    assert any("last_error = RuntimeError: boom" in line for line in reply)


@pytest.mark.asyncio
async def test_tasks_filters_by_plugin_and_status(bot, msg):
    await tasks_plugin.tasks_command(
        bot,
        "admin@example.org",
        "admin",
        ["plugin", "birthday_notify", "failed"],
        msg,
        False,
    )

    reply = bot.reply.call_args.args[1]
    assert reply[0] == "🧵 Background tasks — plugin=birthday_notify — status=failed"
    assert any("birthday_notify/birthday-loop" in line for line in reply)
    assert not any("rss/feed-loop" in line for line in reply)


@pytest.mark.asyncio
async def test_tasks_missing_plugin_name_shows_usage(bot, msg):
    await tasks_plugin.tasks_command(bot, "admin@example.org", "admin", ["plugin"], msg, False)

    bot.reply_usage.assert_called_once()


@pytest.mark.asyncio
async def test_tasks_without_supervisor_warns(msg):
    bot = MagicMock()
    bot.reply_warn = MagicMock()
    bot.tasks = None

    await tasks_plugin.tasks_command(bot, "admin@example.org", "admin", [], msg, False)

    bot.reply_warn.assert_called_once()


@pytest.mark.asyncio
async def test_tasks_restart_delegates_to_plugin_manager(msg):
    bot = MagicMock()
    bot.reply = MagicMock()
    bot.reply_usage = MagicMock()
    bot.bot_plugins.restart_tasks = AsyncMock(return_value=(True, "Plugin rss tasks restarted", 2))

    await tasks_plugin.tasks_command(
        bot,
        "admin@example.org",
        "admin",
        ["restart", "rss"],
        msg,
        False,
    )

    bot.bot_plugins.restart_tasks.assert_awaited_once_with("rss")
    assert "Cancelled before restart: 2" in bot.reply.call_args.args[1]

@pytest.mark.asyncio
async def test_tasks_stale_command_lists_stale_tasks(msg):
    stale = [
        TaskInfo(
            plugin="rss",
            name="feed-loop",
            status="running",
            created_at="2026-06-22T10:00:00+00:00",
            done_at=None,
            cancelled=False,
            last_error=None,
            heartbeat_at="2026-06-22T09:00:00+00:00",
        )
    ]
    bot = MagicMock()
    bot.reply = MagicMock()
    bot.reply_warn = MagicMock()
    bot.tasks.stale_tasks = MagicMock(return_value=stale)

    await tasks_plugin.tasks_stale_command(bot, "admin@example.org", "admin", [], msg, False)

    bot.tasks.stale_tasks.assert_called_once()
    reply = bot.reply.call_args.args[1]
    assert reply[0].startswith("🧵 Stale background tasks")
    assert any("rss/feed-loop" in line for line in reply)
