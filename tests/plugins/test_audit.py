from unittest.mock import AsyncMock, MagicMock

import pytest

import core_plugins.audit as audit_mod


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


def test_format_details_and_row_variants():
    assert audit_mod._format_details('{"b": 2, "a": 1}') == "a=1, b=2"
    assert audit_mod._format_details("") == "{}"
    assert audit_mod._format_details("not json") == "{}"

    mapping_row = {
        "id": 7,
        "created_at": "2026-06-24 12:00:00",
        "event": "config_reloaded",
        "actor": None,
        "target": "config",
        "details": '{"prefix": ","}',
    }
    assert audit_mod._format_row(mapping_row) == (
        "#7 2026-06-24 12:00:00 | config_reloaded | actor=— | "
        "target=config | prefix=,"
    )

    tuple_row = (8, "now", "backup_created", "admin@example.org", None, "{}")
    assert audit_mod._format_row(tuple_row) == (
        "#8 now | backup_created | actor=admin@example.org | target=None"
    )


@pytest.mark.asyncio
async def test_list_events_handles_missing_audit_log(bot):
    bot.db = MagicMock()
    bot.db.audit = None

    assert await audit_mod._list_events(bot, limit=5) == []


@pytest.mark.asyncio
async def test_audit_user_usage_invalid_jid_empty_and_rows(bot, msg, monkeypatch):
    bot.reply_usage = MagicMock()
    bot.reply_error = MagicMock()

    await audit_mod.audit_user(bot, "admin@example.org", "admin", [], msg, False)
    bot.reply_usage.assert_called_once()

    await audit_mod.audit_user(bot, "admin@example.org", "admin", ["not a jid"], msg, False)
    bot.reply_error.assert_called_once_with(msg, "Invalid JID.")

    list_events = AsyncMock(return_value=[])
    monkeypatch.setattr(audit_mod, "_list_events", list_events)
    await audit_mod.audit_user(bot, "admin@example.org", "admin", ["Admin@Example.Org/resource"], msg, False)
    list_events.assert_awaited_once_with(bot, limit=50, actor="admin@example.org")
    assert "No audit events found for admin@example.org." in bot.reply.call_args.args[1]

    list_events = AsyncMock(return_value=[(1, "now", "event", "Admin@example.org", "target", '{}')])
    monkeypatch.setattr(audit_mod, "_list_events", list_events)
    await audit_mod.audit_user(bot, "admin@example.org", "admin", ["Admin@Example.Org"], msg, False)
    assert "#1 now | event" in bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_audit_target_and_action_filters(msg):
    bot = MagicMock()
    bot.reply = MagicMock()
    row = {
        "id": 1,
        "created_at": "now",
        "event": "room_added",
        "actor": "admin@example.org",
        "target": "room@example.org",
        "details": "{}",
    }
    audit_log = MagicMock()
    audit_log.list = AsyncMock(return_value=[row])
    bot.db = MagicMock(audit=audit_log)

    await audit_mod.audit_target(
        bot,
        "admin@example.org",
        "admin",
        ["room@example.org"],
        msg,
        False,
    )
    audit_log.list.assert_awaited_with(
        limit=50,
        actor=None,
        target="room@example.org",
        event=None,
    )
    assert "room_added" in bot.reply.call_args.args[1]

    await audit_mod.audit_action(
        bot,
        "admin@example.org",
        "admin",
        ["room_added"],
        msg,
        False,
    )
    audit_log.list.assert_awaited_with(
        limit=50,
        actor=None,
        target=None,
        event="room_added",
    )
