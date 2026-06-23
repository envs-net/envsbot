"""Managed backup and restore commands."""

from __future__ import annotations

import logging

from utils.audit import audit_event
from utils.backups import (
    BackupError,
    backup_details,
    create_backup,
    list_backups,
    resolve_backup,
    restore_backup,
)
from utils.command import Role, command
from utils.formatting import format_page, parse_page_args

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "backups",
    "version": "0.1.0",
    "description": "Managed ZIP backups and restore helpers.",
    "category": "core",
}


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def _backup_list_line(index: int, backup) -> str:
    files = ", ".join(backup.files) if backup.files else "no file list"
    return (
        f"{index}. {backup.name} · {backup.created_at} · "
        f"{backup.reason} · {_format_bytes(backup.size)} · {files}"
    )


@command("backup create", role=Role.ADMIN, aliases=["backup"])
async def backup_create(bot, sender, nick, args, msg, is_room):
    """Create a managed ZIP backup."""
    reason = " ".join(args).strip() or "manual"
    try:
        archive = await create_backup(bot, reason=reason)
    except Exception as exc:
        log.exception("[BACKUP] Backup creation failed")
        bot.reply_error(msg, f"Backup failed: {exc}")
        return

    await audit_event(
        bot,
        "backup_created",
        actor=sender,
        target=archive.name,
        details={"reason": reason},
    )
    bot.reply_ok(msg, f"Backup created: {archive.name}")


@command("backup list", role=Role.ADMIN, aliases=["backups", "backup ls"])
async def backup_list(bot, sender, nick, args, msg, is_room):
    """List managed ZIP backups."""
    page_request = parse_page_args(args)
    backups = list_backups()
    lines = [_backup_list_line(idx, backup) for idx, backup in enumerate(backups, start=1)]
    if not lines:
        lines = ["No backups found."]
    bot.reply(
        msg,
        format_page(
            "📦 Managed backups",
            lines,
            page_request=page_request,
            page_size=10,
            command_hint=f"{bot.prefix}backup list",
        ),
    )


@command("backup show", role=Role.ADMIN)
async def backup_show(bot, sender, nick, args, msg, is_room):
    """Show details for one managed backup archive."""
    if len(args) != 1:
        bot.reply_usage(msg, f"{bot.prefix}backup show <archive|last>")
        return
    try:
        path = resolve_backup(args[0])
        details = backup_details(path)
    except BackupError as exc:
        bot.reply_error(msg, str(exc))
        return

    manifest = details["manifest"]
    files = manifest.get("files", [])
    missing = manifest.get("missing", [])
    lines = [
        "📦 Backup details",
        f"Name: {details['name']}",
        f"Created: {manifest.get('created_at', 'unknown')}",
        f"Reason: {manifest.get('reason', 'unknown')}",
        f"Version: {manifest.get('version', 'unknown')}",
        f"Size: {_format_bytes(details['size'])}",
        "Files:",
    ]
    if files:
        for item in files:
            lines.append(f"• {item.get('name', '?')} ({_format_bytes(int(item.get('size', 0)))})")
    else:
        lines.append("• none")
    if missing:
        lines.append("Missing at backup time:")
        for item in missing:
            lines.append(f"• {item.get('name', '?')} from {item.get('source', '?')}")
    bot.reply(msg, lines)


@command("restore", role=Role.OWNER, aliases=["backup restore"])
async def backup_restore(bot, sender, nick, args, msg, is_room):
    """Restore a managed ZIP backup after explicit confirmation."""
    if len(args) != 2 or args[1].lower() != "confirm":
        bot.reply_warn(
            msg,
            f"Usage: {bot.prefix}restore <archive|last> confirm\n"
            "Restore overwrites bot.db, config.py, vcard.py and chat_slang.csv "
            "when those files are present in the archive. A safety backup is "
            "created first.",
        )
        return

    try:
        archive = resolve_backup(args[0])
        result = await restore_backup(bot, archive)
    except BackupError as exc:
        bot.reply_error(msg, str(exc))
        return
    except Exception as exc:
        log.exception("[BACKUP] Restore failed")
        bot.reply_error(msg, f"Restore failed: {exc}")
        return

    await audit_event(
        bot,
        "backup_restored",
        actor=sender,
        target=result["archive"],
        details={"restored": result["restored"], "safety_backup": result["safety_backup"]},
    )
    restored = ", ".join(result["restored"]) or "nothing"
    bot.reply_ok(
        msg,
        "Backup restored.\n"
        f"Archive: {result['archive']}\n"
        f"Restored: {restored}\n"
        f"Safety backup: {result['safety_backup']}\n"
        "Restart the bot after restoring config.py or vcard.py changes.",
    )
