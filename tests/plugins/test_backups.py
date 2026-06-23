from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import core_plugins.backups as backups_plugin


@pytest.fixture
def bot():
    bot = MagicMock()
    bot.prefix = ","
    bot.reply = MagicMock()
    bot.reply_ok = MagicMock()
    bot.reply_error = MagicMock()
    bot.reply_warn = MagicMock()
    bot.reply_usage = MagicMock()
    return bot


@pytest.fixture
def msg():
    return MagicMock()


@pytest.mark.asyncio
async def test_backup_create_reports_archive(bot, msg, monkeypatch):
    create = AsyncMock(return_value=Path("envsbot-backup-test.zip"))
    audit = AsyncMock()
    monkeypatch.setattr(backups_plugin, "create_backup", create)
    monkeypatch.setattr(backups_plugin, "audit_event", audit)

    await backups_plugin.backup_create(bot, "admin@example.org", "admin", ["before", "change"], msg, False)

    create.assert_awaited_once_with(bot, reason="before change")
    audit.assert_awaited_once()
    bot.reply_ok.assert_called_once()
    assert "envsbot-backup-test.zip" in bot.reply_ok.call_args.args[1]


@pytest.mark.asyncio
async def test_backup_list_formats_empty_result(bot, msg, monkeypatch):
    monkeypatch.setattr(backups_plugin, "list_backups", lambda: [])

    await backups_plugin.backup_list(bot, "admin@example.org", "admin", [], msg, False)

    reply_lines = bot.reply.call_args.args[1]
    assert reply_lines[0] == "📦 Managed backups"
    assert "No backups found." in reply_lines


@pytest.mark.asyncio
async def test_restore_requires_explicit_confirmation(bot, msg):
    await backups_plugin.backup_restore(bot, "owner@example.org", "owner", ["last"], msg, False)

    bot.reply_warn.assert_called_once()
    assert "confirm" in bot.reply_warn.call_args.args[1]


@pytest.mark.asyncio
async def test_restore_runs_with_confirmation(bot, msg, monkeypatch):
    resolve = MagicMock(return_value=Path("backup.zip"))
    restore = AsyncMock(return_value={
        "archive": "backup.zip",
        "restored": ["bot.db", "config.py"],
        "safety_backup": "safety.zip",
    })
    audit = AsyncMock()
    monkeypatch.setattr(backups_plugin, "resolve_backup", resolve)
    monkeypatch.setattr(backups_plugin, "restore_backup", restore)
    monkeypatch.setattr(backups_plugin, "audit_event", audit)

    await backups_plugin.backup_restore(bot, "owner@example.org", "owner", ["last", "confirm"], msg, False)

    resolve.assert_called_once_with("last")
    restore.assert_awaited_once_with(bot, Path("backup.zip"))
    audit.assert_awaited_once()
    bot.reply_ok.assert_called_once()
    assert "Backup restored" in bot.reply_ok.call_args.args[1]
