from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
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


def test_backup_formatting_helpers():
    backup = MagicMock()
    backup.name = "envsbot-backup.zip"
    backup.created_at = "2026-06-24T12:00:00Z"
    backup.reason = "manual"
    backup.size = 2048
    backup.files = ["bot.db", "config.py"]

    assert backups_plugin._format_bytes(1024) == "1.0 KiB"
    assert backups_plugin._format_bytes(1024 * 1024) == "1.0 MiB"
    assert backups_plugin._backup_list_line(3, backup) == (
        "3. envsbot-backup.zip · 2026-06-24T12:00:00Z · manual · "
        "2.0 KiB · bot.db, config.py"
    )

    backup.files = []
    assert "no file list" in backups_plugin._backup_list_line(1, backup)


@pytest.mark.asyncio
async def test_backup_create_handles_failures(bot, msg, monkeypatch):
    create = AsyncMock(side_effect=RuntimeError("disk full"))
    monkeypatch.setattr(backups_plugin, "create_backup", create)

    await backups_plugin.backup_create(bot, "admin@example.org", "admin", [], msg, False)

    bot.reply_error.assert_called_once()
    assert "Backup failed: disk full" in bot.reply_error.call_args.args[1]


@pytest.mark.asyncio
async def test_backup_list_uses_pagination(bot, msg, monkeypatch):
    backup = MagicMock()
    backup.name = "backup.zip"
    backup.created_at = "now"
    backup.reason = "manual"
    backup.size = 1024
    backup.files = []
    monkeypatch.setattr(backups_plugin, "list_backups", lambda: [backup])

    await backups_plugin.backup_list(bot, "admin@example.org", "admin", ["all"], msg, False)

    lines = bot.reply.call_args.args[1]
    assert lines[0] == "📦 Managed backups"
    assert any("backup.zip" in line for line in lines)


@pytest.mark.asyncio
async def test_backup_show_usage_error_and_details(bot, msg, monkeypatch):
    await backups_plugin.backup_show(bot, "admin@example.org", "admin", [], msg, False)
    bot.reply_usage.assert_called_once_with(msg, ",backup show <archive|last>")

    monkeypatch.setattr(backups_plugin, "resolve_backup", MagicMock(side_effect=backups_plugin.BackupError("missing")))
    await backups_plugin.backup_show(bot, "admin@example.org", "admin", ["missing.zip"], msg, False)
    bot.reply_error.assert_called_once_with(msg, "missing")

    details = {
        "name": "backup.zip",
        "size": 2048,
        "manifest": {
            "created_at": "2026-06-24T12:00:00Z",
            "reason": "manual",
            "version": "1",
            "files": [{"name": "bot.db", "size": 1024}],
            "missing": [{"name": "vcard.py", "source": "root"}],
        },
    }
    monkeypatch.setattr(backups_plugin, "resolve_backup", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(backups_plugin, "backup_details", MagicMock(return_value=details))

    await backups_plugin.backup_show(bot, "admin@example.org", "admin", ["last"], msg, False)

    lines = bot.reply.call_args.args[1]
    assert lines[:7] == [
        "📦 Backup details",
        "Name: backup.zip",
        "Created: 2026-06-24T12:00:00Z",
        "Reason: manual",
        "Version: 1",
        "Size: 2.0 KiB",
        "Files:",
    ]
    assert "• bot.db (1.0 KiB)" in lines
    assert "Missing at backup time:" in lines
    assert "• vcard.py from root" in lines


@pytest.mark.asyncio
async def test_backup_show_handles_empty_manifest_lists(bot, msg, monkeypatch):
    details = {
        "name": "backup.zip",
        "size": 0,
        "manifest": {},
    }
    monkeypatch.setattr(backups_plugin, "resolve_backup", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(backups_plugin, "backup_details", MagicMock(return_value=details))

    await backups_plugin.backup_show(bot, "admin@example.org", "admin", ["last"], msg, False)

    lines = bot.reply.call_args.args[1]
    assert "Created: unknown" in lines
    assert "Reason: unknown" in lines
    assert "Version: unknown" in lines
    assert "• none" in lines


@pytest.mark.asyncio
async def test_backup_restore_handles_backup_and_generic_errors(bot, msg, monkeypatch):
    monkeypatch.setattr(backups_plugin, "resolve_backup", MagicMock(side_effect=backups_plugin.BackupError("bad archive")))
    await backups_plugin.backup_restore(bot, "owner@example.org", "owner", ["bad.zip", "confirm"], msg, False)
    bot.reply_error.assert_called_with(msg, "bad archive")

    monkeypatch.setattr(backups_plugin, "resolve_backup", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(backups_plugin, "restore_backup", AsyncMock(side_effect=RuntimeError("boom")))
    await backups_plugin.backup_restore(bot, "owner@example.org", "owner", ["last", "confirm"], msg, False)
    assert "Restore failed: boom" in bot.reply_error.call_args.args[1]


def test_parse_prune_args():
    assert backups_plugin._parse_prune_args(["dry-run", "keep", "20", "days", "30"]) == (
        True,
        20,
        30,
        None,
    )
    assert backups_plugin._parse_prune_args(["keep", "nope"])[3] == "keep must be a number"


@pytest.mark.asyncio
async def test_backup_prune_dry_run_and_delete(bot, msg, monkeypatch):
    archive = MagicMock()
    archive.name = "envsbot-backup-old.zip"
    path = Path("envsbot-backup-old.zip")
    plan = MagicMock(return_value=[archive])
    prune = MagicMock(return_value=[path])
    audit = AsyncMock()
    monkeypatch.setattr(backups_plugin, "plan_backup_prune", plan)
    monkeypatch.setattr(backups_plugin, "prune_old_backups", prune)
    monkeypatch.setattr(backups_plugin, "audit_event", audit)

    await backups_plugin.backup_prune(
        bot,
        "admin@example.org",
        "admin",
        ["dry-run", "keep", "2"],
        msg,
        False,
    )

    plan.assert_called_once_with(keep=2, days=None)
    assert "Would delete: 1" in "\n".join(bot.reply.call_args.args[1])
    prune.assert_not_called()

    await backups_plugin.backup_prune(
        bot,
        "admin@example.org",
        "admin",
        ["days", "30"],
        msg,
        False,
    )

    prune.assert_called_once_with(keep=None, days=30)
    audit.assert_awaited_once()
    bot.reply_ok.assert_called()

@pytest.mark.asyncio
async def test_backup_restore_supports_dry_run(bot, msg, monkeypatch):
    monkeypatch.setattr(backups_plugin, "resolve_backup", MagicMock(return_value=Path("backup.zip")))
    monkeypatch.setattr(backups_plugin, "restore_plan", MagicMock(return_value={
        "archive": "backup.zip",
        "manifest": {"created_at": "2026-06-24T12:00:00Z"},
        "entries": ["bot.db"],
        "targets": {"bot.db": "/srv/envsbot/bot.db"},
    }))

    await backups_plugin.backup_restore(bot, "owner@example.org", "owner", ["last", "dry-run"], msg, False)

    lines = bot.reply.call_args.args[1]
    assert lines[0] == "📦 Backup restore dry-run"
    assert "• bot.db -> /srv/envsbot/bot.db" in lines
