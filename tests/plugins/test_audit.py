from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import core_plugins.audit as audit_mod


@pytest.fixture
def bot():
    bot = MagicMock()
    bot.prefix = ","
    bot.reply = MagicMock()
    bot.db = SimpleNamespace(audit=None)
    return bot


@pytest.fixture
def msg():
    return MagicMock()


@pytest.mark.asyncio
async def test_audit_last_uses_database_backed_pagination(bot, msg):
    rows = [
        (idx, f"now-{idx}", "event", "actor", "target", "{}")
        for idx in range(25, 0, -1)
    ]

    async def list_events(*, limit=20, offset=0, actor=None, target=None, event=None):
        assert actor is None
        assert target is None
        assert event is None
        return rows[offset:offset + limit]

    audit_log = SimpleNamespace(
        count=AsyncMock(return_value=len(rows)),
        list=AsyncMock(side_effect=list_events),
    )
    bot.db = SimpleNamespace(audit=audit_log)

    await audit_mod.audit_last(bot, "admin@example.org", "admin", ["2"], msg, False)

    audit_log.count.assert_awaited_once_with(actor=None, target=None, event=None)
    audit_log.list.assert_awaited_once_with(limit=10, offset=10, actor=None, target=None, event=None)
    reply_lines = bot.reply.call_args.args[1]
    assert reply_lines[0] == "🧾 Audit log (page 2/3)"
    assert "#15 now-15" in "\n".join(reply_lines)
    assert "#25 now-25" not in "\n".join(reply_lines)


@pytest.mark.asyncio
async def test_audit_last_all_fetches_all_matching_rows(bot, msg):
    rows = [(1, "now", "event", "actor", "target", "{}")]
    audit_log = SimpleNamespace(
        count=AsyncMock(return_value=len(rows)),
        list=AsyncMock(return_value=rows),
    )
    bot.db = SimpleNamespace(audit=audit_log)

    await audit_mod.audit_last(bot, "admin@example.org", "admin", ["all"], msg, False)

    audit_log.list.assert_awaited_once_with(limit=1, offset=0, actor=None, target=None, event=None)
    reply_lines = bot.reply.call_args.args[1]
    assert reply_lines[0] == "🧾 Audit log"
    assert "#1 now" in "\n".join(reply_lines)


@pytest.mark.asyncio
async def test_audit_last_limit_argument_uses_legacy_limit(bot, msg, monkeypatch):
    list_events = AsyncMock(return_value=[])
    monkeypatch.setattr(audit_mod, "_list_events", list_events)

    await audit_mod.audit_last(bot, "admin@example.org", "admin", ["limit", "7"], msg, False)

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

    audit_log = SimpleNamespace(
        count=AsyncMock(return_value=0),
        list=AsyncMock(return_value=[]),
    )
    bot.db = SimpleNamespace(audit=audit_log)
    await audit_mod.audit_user(bot, "admin@example.org", "admin", ["Admin@Example.Org/resource"], msg, False)
    audit_log.count.assert_awaited_with(actor="admin@example.org", target=None, event=None)
    audit_log.list.assert_awaited_with(limit=1, offset=0, actor="admin@example.org", target=None, event=None)
    assert "No audit events found for admin@example.org." in bot.reply.call_args.args[1]

    audit_log = SimpleNamespace(
        count=AsyncMock(return_value=1),
        list=AsyncMock(return_value=[(1, "now", "event", "Admin@example.org", "target", '{}')]),
    )
    bot.db = SimpleNamespace(audit=audit_log)
    await audit_mod.audit_user(bot, "admin@example.org", "admin", ["Admin@Example.Org"], msg, False)
    assert "#1 now | event" in "\n".join(bot.reply.call_args.args[1])


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
    audit_log = SimpleNamespace(
        count=AsyncMock(return_value=1),
        list=AsyncMock(return_value=[row]),
    )
    bot.db = SimpleNamespace(audit=audit_log)

    await audit_mod.audit_target(
        bot,
        "admin@example.org",
        "admin",
        ["room@example.org"],
        msg,
        False,
    )
    audit_log.list.assert_awaited_with(
        limit=1,
        offset=0,
        actor=None,
        target="room@example.org",
        event=None,
    )
    assert "room_added" in "\n".join(bot.reply.call_args.args[1])

    await audit_mod.audit_action(
        bot,
        "admin@example.org",
        "admin",
        ["room_added"],
        msg,
        False,
    )
    audit_log.list.assert_awaited_with(
        limit=1,
        offset=0,
        actor=None,
        target=None,
        event="room_added",
    )

@pytest.mark.asyncio
async def test_audit_export_accepts_filters(bot, msg):
    exporter = AsyncMock(return_value='{"event":"backup_created"}')
    bot.db = MagicMock()
    bot.db.audit.export_jsonl = exporter

    await audit_mod.audit_export(
        bot,
        "admin@example.org",
        "admin",
        ["25", "action", "backup_created", "target", "managed_backups"],
        msg,
        False,
    )

    exporter.assert_awaited_once_with(
        limit=25,
        event="backup_created",
        target="managed_backups",
    )
    assert "action" not in bot.reply.call_args.args[1]
    assert "event=backup_created" in bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_audit_errors_filters_error_like_rows(bot, msg):
    rows = [
        (4, "now-4", "command_executed", "actor", "target", '{"status": "ok"}'),
        (3, "now-3", "plugin_failed", "actor", "rss", "{}"),
        (2, "now-2", "command_executed", "actor", "target", '{"status": "error"}'),
        (1, "now-1", "backup_created", "actor", "backup", "{}"),
    ]
    audit_log = SimpleNamespace(list=AsyncMock(return_value=rows))
    bot.db = SimpleNamespace(audit=audit_log)

    await audit_mod.audit_errors(bot, "admin@example.org", "admin", [], msg, False)

    reply = "\n".join(bot.reply.call_args.args[1])
    assert "Audit errors" in reply
    assert "plugin_failed" in reply
    assert "status=error" in reply
    assert "status=ok" not in reply


def test_is_error_event_handles_mapping_and_tuple_rows():
    assert audit_mod._is_error_event({
        "event": "command_executed",
        "details": '{"error": "boom"}',
    }) is True
    assert audit_mod._is_error_event((1, "now", "event", "actor", "target", '{"result": "failed"}')) is True
    assert audit_mod._is_error_event((1, "now", "event", "actor", "target", '{"status": "ok"}')) is False


@pytest.mark.asyncio
async def test_audit_summary_uses_store_summary(bot, msg):
    summary = {
        "total": 4,
        "errors": 1,
        "unique_actors": 2,
        "unique_targets": 3,
        "events": [{"name": "room_added", "count": 2}],
        "actors": [{"name": "admin@example.org", "count": 3}],
        "targets": [{"name": "room@example.org", "count": 2}],
    }
    summarizer = AsyncMock(return_value=summary)
    bot.db = SimpleNamespace(audit=SimpleNamespace(summary_since=summarizer))

    await audit_mod.audit_summary(bot, "admin@example.org", "admin", ["7d"], msg, False)

    summarizer.assert_awaited_once_with(hours=24 * 7, limit=8)
    reply = "\n".join(bot.reply.call_args.args[1])
    assert "Audit summary — last 7d" in reply
    assert "Events: 4" in reply
    assert "Error-like events: 1" in reply
    assert "• room_added: 2" in reply
    assert "• admin@example.org: 3" in reply


def test_parse_summary_window_accepts_expected_windows():
    assert audit_mod._parse_summary_window([]) == (24, "24h", None)
    assert audit_mod._parse_summary_window(["24h"]) == (24, "24h", None)
    assert audit_mod._parse_summary_window(["7d"]) == (24 * 7, "7d", None)
    assert audit_mod._parse_summary_window(["12h"]) == (12, "12h", None)
    assert audit_mod._parse_summary_window(["2d"]) == (48, "2d", None)
    assert audit_mod._parse_summary_window(["0h"])[2] is not None
