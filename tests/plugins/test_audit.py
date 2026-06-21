from unittest.mock import AsyncMock, MagicMock

import pytest

import plugins.audit as audit_mod


@pytest.fixture
def bot():
    bot = MagicMock()
    bot.prefix = ","
    bot.reply = MagicMock()
    return bot


@pytest.fixture
def msg():
    return MagicMock()


@pytest.mark.asyncio
async def test_audit_last_default_uses_safe_limit(bot, msg, monkeypatch):
    list_events = AsyncMock(return_value=[])
    monkeypatch.setattr(audit_mod, "_list_events", list_events)

    await audit_mod.audit_last(bot, "admin@example.org", "admin", [], msg, False)

    list_events.assert_awaited_once_with(bot, limit=30)
    reply_lines = bot.reply.call_args.args[1]
    assert reply_lines[0] == "🧾 Audit log"
    assert "No audit events found." in reply_lines


@pytest.mark.asyncio
async def test_audit_last_all_uses_larger_limit(bot, msg, monkeypatch):
    list_events = AsyncMock(return_value=[])
    monkeypatch.setattr(audit_mod, "_list_events", list_events)

    await audit_mod.audit_last(bot, "admin@example.org", "admin", ["all"], msg, False)

    list_events.assert_awaited_once_with(bot, limit=50)
    reply_lines = bot.reply.call_args.args[1]
    assert reply_lines[0] == "🧾 Audit log"
    assert "No audit events found." in reply_lines


@pytest.mark.asyncio
async def test_audit_last_numeric_argument_is_limit(bot, msg, monkeypatch):
    list_events = AsyncMock(return_value=[])
    monkeypatch.setattr(audit_mod, "_list_events", list_events)

    await audit_mod.audit_last(bot, "admin@example.org", "admin", ["7"], msg, False)

    list_events.assert_awaited_once_with(bot, limit=7)
    reply_lines = bot.reply.call_args.args[1]
    assert reply_lines[0] == "🧾 Audit log"
    assert "No audit events found." in reply_lines
