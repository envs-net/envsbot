from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import core_plugins.usage as plugin


@pytest.mark.asyncio
async def test_commandstats_top_formats_aggregate_rows():
    store = SimpleNamespace(summary=AsyncMock(return_value=[{
        "command_name": "help",
        "uses": 4,
        "failures": 1,
        "total_duration_ms": 40,
        "last_used_at": 1,
    }]))
    bot = SimpleNamespace(
        db=SimpleNamespace(command_usage=store),
        prefix=",",
        reply=MagicMock(),
        reply_error=MagicMock(),
        reply_usage=MagicMock(),
    )
    await plugin.commandstats(bot, "a", "a", ["top", "7"], MagicMock(), False)
    text = "\n".join(bot.reply.call_args.args[1])
    assert "help — 4 use(s), 1 failed" in text
    store.summary.assert_awaited_once_with(days=7, limit=200)


@pytest.mark.asyncio
async def test_commandstats_unused_compares_registry(monkeypatch):
    store = SimpleNamespace(all_time_commands=AsyncMock(return_value={"help"}))
    monkeypatch.setattr(plugin, "_registered_command_names", lambda: {"help", "never"})
    bot = SimpleNamespace(
        db=SimpleNamespace(command_usage=store),
        prefix=",",
        reply=MagicMock(),
        reply_error=MagicMock(),
        reply_usage=MagicMock(),
    )
    await plugin.commandstats(bot, "a", "a", ["unused"], MagicMock(), False)
    assert "• never" in bot.reply.call_args.args[1]
