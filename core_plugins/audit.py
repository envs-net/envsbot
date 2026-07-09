"""Audit log commands for administrative actions."""

from __future__ import annotations

import json
import logging
from slixmpp import JID

from utils.audit import audit_event
from utils.command import Role, command
from utils.config import config
from utils.formatting import format_page, parse_page_args

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "audit",
    "version": "0.1.0",
    "description": "Admin audit log viewer",
    "category": "core",
}


def _format_details(raw: str) -> str:
    try:
        data = json.loads(raw or "{}")
    except Exception:
        return "{}"
    if not data:
        return "{}"
    parts = [f"{key}={value}" for key, value in sorted(data.items())]
    return ", ".join(parts)


def _format_row(row) -> str:
    try:
        event_id = row["id"]
        created_at = row["created_at"]
        event = row["event"]
        actor = row["actor"] or "—"
        target = row["target"] or "—"
        details = _format_details(row["details"])
    except Exception:
        event_id, created_at, event, actor, target, details = row
        details = _format_details(details)
    suffix = f" | {details}" if details != "{}" else ""
    return f"#{event_id} {created_at} | {event} | actor={actor} | target={target}{suffix}"


async def _list_events(
    bot,
    *,
    limit: int = 20,
    actor: str | None = None,
    target: str | None = None,
    event: str | None = None,
):
    audit_log = getattr(getattr(bot, "db", None), "audit", None)
    if audit_log is None:
        return []
    return await audit_log.list(
        limit=limit,
        actor=actor,
        target=target,
        event=event,
    )


def _reply_audit_rows(bot, msg, title: str, rows, *, empty: str) -> None:
    """Reply with formatted audit rows."""
    lines = [_format_row(row) for row in rows]
    if not lines:
        lines = [empty]
    bot.reply(msg, "\n".join([title, *lines]))


@command(
    "audit last",
    role=Role.ADMIN,
    aliases=["audit", "audits last"],
    short="Show recent admin audit events.",
    usage="{prefix}audit last [all|page|last|limit]",
    examples=["{prefix}audit last", "{prefix}audit last 2"],
    category="admin",
    context="private recommended",
)
async def audit_last(bot, sender, nick, args, msg, is_room):
    """Show recent audit events."""
    page_request = parse_page_args(args)
    limit = 50 if page_request.all else 30
    if args and str(args[0]).isdigit():
        limit = max(1, min(int(args[0]), 100))
        page_request = parse_page_args([])

    rows = await _list_events(bot, limit=limit)
    lines = [_format_row(row) for row in rows]
    if not lines:
        lines = ["No audit events found."]

    bot.reply(
        msg,
        format_page(
            "🧾 Audit log",
            lines,
            page_request=page_request,
            page_size=10,
            command_hint=f"{bot.prefix}audit last",
        ),
    )


@command(
    "audit user",
    role=Role.ADMIN,
    aliases=["audits user"],
    short="Show recent audit events for one actor JID.",
    usage="{prefix}audit user <jid>",
    examples=["{prefix}audit user admin@example.org"],
    category="admin",
    context="private recommended",
)
async def audit_user(bot, sender, nick, args, msg, is_room):
    """Show audit events for one actor."""
    if len(args) != 1:
        bot.reply_usage(msg, f"{config.get('prefix', ',')}audit user <jid>")
        return
    try:
        actor = str(JID(args[0]).bare)
    except Exception:
        bot.reply_error(msg, "Invalid JID.")
        return

    rows = await _list_events(bot, limit=50, actor=actor)
    _reply_audit_rows(
        bot,
        msg,
        "🧾 Audit log",
        rows,
        empty=f"No audit events found for {actor}.",
    )


@command(
    "audit target",
    role=Role.ADMIN,
    aliases=["audits target", "audit room", "audits room"],
    short="Show recent audit events for one target value.",
    usage="{prefix}audit target <target>",
    examples=["{prefix}audit target room@conference.example.org"],
    category="admin",
    context="private recommended",
)
async def audit_target(bot, sender, nick, args, msg, is_room):
    """Show audit events for one target."""
    if len(args) != 1:
        bot.reply_usage(msg, f"{config.get('prefix', ',')}audit target <target>")
        return
    target = str(args[0])
    rows = await _list_events(bot, limit=50, target=target)
    _reply_audit_rows(
        bot,
        msg,
        "🧾 Audit log",
        rows,
        empty=f"No audit events found for target {target}.",
    )


@command(
    "audit action",
    role=Role.ADMIN,
    aliases=["audits action", "audit event", "audits event"],
    short="Show recent audit events for one action/event type.",
    usage="{prefix}audit action <event_type>",
    examples=["{prefix}audit action room_feature_changed"],
    category="admin",
    context="private recommended",
)
async def audit_action(bot, sender, nick, args, msg, is_room):
    """Show audit events for one event type."""
    if len(args) != 1:
        bot.reply_usage(msg, f"{config.get('prefix', ',')}audit action <event_type>")
        return
    event = str(args[0])
    rows = await _list_events(bot, limit=50, event=event)
    _reply_audit_rows(
        bot,
        msg,
        "🧾 Audit log",
        rows,
        empty=f"No audit events found for action {event}.",
    )

@command(
    "audit export",
    role=Role.ADMIN,
    aliases=["audits export"],
    short="Export recent audit events as JSON Lines.",
    usage="{prefix}audit export [limit]",
    examples=["{prefix}audit export", "{prefix}audit export 100"],
    category="admin",
    context="private recommended",
)
async def audit_export(bot, sender, nick, args, msg, is_room):
    """Export recent audit events as JSON Lines."""
    limit = 100
    if args:
        try:
            limit = max(1, min(int(args[0]), 500))
        except ValueError:
            bot.reply_usage(msg, f"{config.get('prefix', ',')}audit export [limit]")
            return
    audit_log = getattr(getattr(bot, "db", None), "audit", None)
    exporter = getattr(audit_log, "export_jsonl", None)
    if not callable(exporter):
        bot.reply_error(msg, "Audit export is not available.")
        return
    payload = await exporter(limit=limit)
    if not payload:
        bot.reply(msg, "🧾 Audit export\nNo audit events found.")
        return
    bot.reply(msg, f"🧾 Audit export (JSONL, newest {limit})\n{payload}", no_store=True)


@command(
    "audit prune",
    role=Role.OWNER,
    aliases=["audits prune"],
    short="Prune old audit events after confirmation.",
    usage="{prefix}audit prune <days> [dry-run|confirm]",
    examples=["{prefix}audit prune 90 dry-run", "{prefix}audit prune 90 confirm"],
    category="admin",
    context="private recommended",
)
async def audit_prune(bot, sender, nick, args, msg, is_room):
    """Prune old audit events after confirmation."""
    if len(args) != 2 or args[1].lower() not in {"dry-run", "dryrun", "check", "confirm"}:
        bot.reply_usage(msg, f"{config.get('prefix', ',')}audit prune <days> [dry-run|confirm]")
        return
    try:
        days = max(1, int(args[0]))
    except ValueError:
        bot.reply_error(msg, "days must be a number")
        return
    dry_run = args[1].lower() in {"dry-run", "dryrun", "check"}
    audit_log = getattr(getattr(bot, "db", None), "audit", None)
    pruner = getattr(audit_log, "prune_older_than", None)
    if not callable(pruner):
        bot.reply_error(msg, "Audit pruning is not available.")
        return
    count = await pruner(days, dry_run=dry_run)
    if dry_run:
        bot.reply_info(msg, f"Audit prune dry-run: {count} event(s) older than {days} days would be deleted.")
        return
    await audit_event(
        bot,
        "audit_pruned",
        actor=sender,
        target="audit_log",
        details={"days": days, "deleted": count},
    )
    bot.reply_ok(msg, f"Audit prune completed: deleted {count} event(s) older than {days} days.")
