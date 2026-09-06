"""Managed backup and restore commands."""

from __future__ import annotations

import asyncio
import inspect
import logging

from envs_xmpp_core.formatting import format_bytes

from utils.audit import audit_event
from utils.backups import (
    BackupError,
    RestoreRuntimeQuiescedError,
    backup_details,
    create_backup,
    list_backups,
    plan_backup_prune,
    prune_old_backups,
    resolve_backup,
    restore_backup,
    restore_plan,
    verify_backup,
)
from utils.command import Role, command
from utils.formatting import format_page, parse_page_args, status_icon

log = logging.getLogger(__name__)

_RESTART_EXIT_CODE = 75


async def _await_reply_delivery(task) -> None:
    """Wait for the pre-restore acknowledgement when reply() returned a task."""
    if inspect.isawaitable(task):
        await asyncio.shield(task)


def _request_restore_restart(bot) -> None:
    """Exit non-zero after a quiesced restore so systemd starts a fresh process."""
    bot._requested_exit_code = _RESTART_EXIT_CODE
    disconnect = getattr(bot, "disconnect", None)
    if callable(disconnect):
        disconnect()


PLUGIN_META = {
    "name": "backups",
    "version": "0.1.0",
    "description": "Managed ZIP backups and restore helpers.",
    "category": "core",
}


def _format_bytes(value: int) -> str:
    if value < 0:
        return f"{float(value):.1f} B"
    return format_bytes(value, negative_label=None, max_unit="GiB", bytes_decimals=1)


def _backup_list_line(index: int, backup) -> str:
    files = ", ".join(backup.files) if backup.files else "no file list"
    return (
        f"{index}. {backup.name} · {backup.created_at} · "
        f"{backup.reason} · {_format_bytes(backup.size)} · {files}"
    )


def _parse_prune_args(args: list[str]) -> tuple[bool, int | None, int | None, str | None]:
    """Parse backup prune arguments.

    Returns ``(dry_run, keep, days, error)``.
    """
    dry_run = False
    keep = None
    days = None
    remaining = list(args)

    if remaining and remaining[0].lower() in {"dry-run", "dryrun", "check"}:
        dry_run = True
        remaining.pop(0)

    while remaining:
        key = remaining.pop(0).lower()
        if key not in {"keep", "days"} or not remaining:
            return dry_run, keep, days, f"invalid argument: {key}"
        try:
            value = int(remaining.pop(0))
        except ValueError:
            return dry_run, keep, days, f"{key} must be a number"
        if key == "keep":
            keep = value
        else:
            days = value

    return dry_run, keep, days, None


@command(
    "backup create",
    role=Role.ADMIN,
    aliases=["backup"],
    short="Create a managed ZIP backup archive.",
    usage="{prefix}backup create [reason]",
    examples=[
        "{prefix}backup create",
        "{prefix}backup create before config change",
        "{prefix}backup",
    ],
    category="admin",
    context="private chat / MUC PM",
)
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


@command(
    "backup list",
    role=Role.ADMIN,
    aliases=["backups", "backup ls"],
    short="List managed backup archives.",
    usage="{prefix}backup list [all|page|last]",
    examples=[
        "{prefix}backup list",
        "{prefix}backup list all",
    ],
    category="admin",
    context="private chat / MUC PM",
)
async def backup_list(bot, sender, nick, args, msg, is_room):
    """List managed ZIP backups."""
    page_request = parse_page_args(args)
    backups = await asyncio.to_thread(list_backups)
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


@command(
    "backup show",
    role=Role.ADMIN,
    short="Show manifest details for one managed backup archive.",
    usage="{prefix}backup show <archive|last>",
    examples=["{prefix}backup show last"],
    category="admin",
    context="private chat / MUC PM",
)
async def backup_show(bot, sender, nick, args, msg, is_room):
    """Show details for one managed backup archive."""
    if len(args) != 1:
        bot.reply_usage(msg, f"{bot.prefix}backup show <archive|last>")
        return
    try:
        path = resolve_backup(args[0])
        details = await asyncio.to_thread(backup_details, path)
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


@command(
    "backup prune",
    role=Role.ADMIN,
    short="Prune managed backup archives, with optional dry-run.",
    usage="{prefix}backup prune [dry-run] [keep <n>] [days <n>]",
    examples=[
        "{prefix}backup prune dry-run",
        "{prefix}backup prune keep 20 days 30",
    ],
    category="admin",
    context="private chat / MUC PM",
)
async def backup_prune(bot, sender, nick, args, msg, is_room):
    """Prune managed backup archives according to retention settings."""
    dry_run, keep, days, error = _parse_prune_args(args)
    if error:
        bot.reply_usage(
            msg,
            f"{bot.prefix}backup prune [dry-run] [keep <n>] [days <n>]",
        )
        return

    planned = await asyncio.to_thread(plan_backup_prune, keep=keep, days=days)
    if dry_run:
        lines = [
            "📦 Backup prune dry-run",
            f"Would delete: {len(planned)} archive(s)",
        ]
        lines.extend(f"• {archive.name}" for archive in planned)
        if len(lines) == 2:
            lines.append("Nothing to prune.")
        bot.reply(msg, lines)
        return

    removed = await asyncio.to_thread(prune_old_backups, keep=keep, days=days)
    await audit_event(
        bot,
        "backup_pruned",
        actor=sender,
        target="managed_backups",
        details={
            "deleted": len(removed),
            "keep": keep,
            "days": days,
        },
    )
    lines = [
        "📦 Backup prune completed",
        f"Deleted: {len(removed)} archive(s)",
    ]
    lines.extend(f"• {path.name}" for path in removed)
    if len(lines) == 2:
        lines.append("Nothing to prune.")
    bot.reply_ok(msg, "\n".join(lines))


@command(
    "backup verify",
    role=Role.ADMIN,
    short="Verify one managed backup archive.",
    usage="{prefix}backup verify <archive|last>",
    examples=["{prefix}backup verify last"],
    category="admin",
    context="private recommended",
)
async def backup_verify(bot, sender, nick, args, msg, is_room):
    """Verify one managed backup archive."""
    if len(args) != 1:
        bot.reply_usage(msg, f"{bot.prefix}backup verify <archive|last>")
        return
    try:
        archive = resolve_backup(args[0])
        result = await asyncio.to_thread(verify_backup, archive)
    except BackupError as exc:
        bot.reply_error(msg, str(exc))
        return
    except Exception as exc:
        log.exception("[BACKUP] Backup verification failed")
        bot.reply_error(msg, f"Backup verification failed: {exc}")
        return

    lines = [
        "📦 Backup verification",
        f"Archive: {result['name']}",
        f"Status: {status_icon('ok' if result['ok'] else 'failed')} {'ok' if result['ok'] else 'failed'}",
        f"Files: {', '.join(result['files']) if result['files'] else 'none'}",
    ]
    if result["errors"]:
        lines.append("Errors:")
        lines.extend(f"• {error}" for error in result["errors"])
    text = "\n".join(lines)
    if result["ok"]:
        bot.reply_ok(msg, text)
    else:
        bot.reply_error(msg, text)


@command(
    "backup restore-plan",
    role=Role.OWNER,
    aliases=["restore dry-run", "backup restore dry-run"],
    short="Show what a restore would overwrite without writing files.",
    usage="{prefix}backup restore-plan <archive|last>",
    examples=["{prefix}backup restore-plan last"],
    category="admin",
    context="private recommended",
)
async def backup_restore_plan(bot, sender, nick, args, msg, is_room):
    """Show what a restore would overwrite without writing files."""
    if len(args) != 1:
        bot.reply_usage(msg, f"{bot.prefix}backup restore-plan <archive|last>")
        return
    try:
        archive = resolve_backup(args[0])
        plan = await asyncio.to_thread(restore_plan, archive)
    except BackupError as exc:
        bot.reply_error(msg, str(exc))
        return
    bot.reply(msg, _format_restore_plan_lines(plan))


def _format_restore_plan_lines(plan: dict) -> list[str]:
    """Return formatted restore plan lines."""
    lines = [
        "📦 Backup restore dry-run",
        f"Archive: {plan['archive']}",
        f"Created: {plan['manifest'].get('created_at', 'unknown')}",
        "Would restore:",
    ]
    if plan["entries"]:
        for entry in plan["entries"]:
            lines.append(f"• {entry} -> {plan['targets'][entry]}")
    else:
        lines.append("• nothing")
    manual_entries = list(plan.get("manual_restore") or [])
    if manual_entries:
        lines.append("Kept in archive for offline/manual restore:")
        lines.extend(f"• {entry}" for entry in manual_entries)
    return lines


@command(
    "restore",
    role=Role.OWNER,
    aliases=["backup restore"],
    short="Restore a managed backup after explicit confirmation.",
    usage="{prefix}restore <archive|last> confirm",
    examples=["{prefix}restore last confirm"],
    category="admin",
    context="private chat / MUC PM",
    timeout_seconds=0,
)
async def backup_restore(bot, sender, nick, args, msg, is_room):
    """Restore a managed ZIP backup and restart into the restored state."""
    if len(args) == 2 and args[1].lower() in {"dry-run", "dryrun", "check", "plan"}:
        try:
            archive = resolve_backup(args[0])
            plan = await asyncio.to_thread(restore_plan, archive)
        except BackupError as exc:
            bot.reply_error(msg, str(exc))
            return
        bot.reply(msg, _format_restore_plan_lines(plan))
        return

    if len(args) != 2 or args[1].lower() != "confirm":
        bot.reply_warn(
            msg,
            f"Usage: {bot.prefix}restore <archive|last> <dry-run|confirm>\n"
            "Restore fully verifies and stages the selected backup, creates a "
            "verified safety backup, then stops mutable runtime activity before "
            "replacing bot.db, the active config and writable support files. "
            "After the restore, envsbot exits with the restart code so the normal "
            "systemd Restart=on-failure unit starts a fresh process. Legacy "
            "source-tree copies stay in the archive for offline/manual recovery.",
        )
        return

    try:
        archive = resolve_backup(args[0])
    except BackupError as exc:
        bot.reply_error(msg, str(exc))
        return

    await audit_event(
        bot,
        "backup_restore_requested",
        actor=sender,
        target=archive.name,
        details={"automatic_restart": True},
    )
    acknowledgement = bot.reply(
        msg,
        "🔄 Restore starting. The archive will be verified and a safety backup "
        "created first. If validation succeeds, envsbot will stop its runtime, "
        "restore the files and restart automatically. This chat may go silent "
        "during the handover.",
    )
    await _await_reply_delivery(acknowledgement)

    try:
        result = await restore_backup(bot, archive)
    except RestoreRuntimeQuiescedError as exc:
        # The runtime is deliberately no longer safe to resume, even when the
        # original files were rolled back successfully. Always start fresh.
        log.error("[BACKUP] Restore failed after runtime quiesce: %s", exc)
        _request_restore_restart(bot)
        return
    except BackupError as exc:
        bot.reply_error(msg, str(exc))
        return
    except Exception as exc:
        log.exception("[BACKUP] Restore failed")
        if getattr(bot, "_shutdown_complete", False):
            _request_restore_restart(bot)
            return
        bot.reply_error(msg, f"Restore failed: {exc}")
        return

    log.info(
        "[BACKUP] restore status=ok archive=%s restored=%s manual=%s safety=%s restart=required",
        result["archive"],
        result["restored"],
        result.get("manual_restore", []),
        result["safety_backup"],
    )
    _request_restore_restart(bot)
