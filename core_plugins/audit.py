"""Audit log commands for administrative actions."""

from __future__ import annotations

import json
import logging
from slixmpp import JID

from utils.audit import audit_event
from utils.command import Role, command
from utils.config import config
from utils.formatting import parse_page_args

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


def _audit_log(bot):
    """Return the configured audit log object, if available."""
    return getattr(getattr(bot, "db", None), "audit", None)


async def _list_events(
    bot,
    *,
    limit: int = 20,
    offset: int = 0,
    actor: str | None = None,
    target: str | None = None,
    event: str | None = None,
):
    audit_log = _audit_log(bot)
    if audit_log is None:
        return []
    return await audit_log.list(
        limit=limit,
        offset=offset,
        actor=actor,
        target=target,
        event=event,
    )


async def _count_events(
    bot,
    *,
    actor: str | None = None,
    target: str | None = None,
    event: str | None = None,
) -> int:
    audit_log = _audit_log(bot)
    counter = getattr(audit_log, "count", None)
    if callable(counter):
        return await counter(actor=actor, target=target, event=event)
    return len(await _list_events(bot, limit=1000, actor=actor, target=target, event=event))


def _format_audit_page(
    title: str,
    rows,
    *,
    empty: str,
    page_request,
    total: int,
    page_size: int,
    command_hint: str,
) -> list[str]:
    """Format already paged audit rows without re-slicing them."""
    lines = [_format_row(row) for row in rows]
    if page_request.all:
        return [title, *(lines or [empty])]

    total_pages = max(1, (total + page_size - 1) // page_size)
    page = total_pages if page_request.page == -1 else min(max(page_request.page, 1), total_pages)
    suffix = f" (page {page}/{total_pages})" if total_pages > 1 else ""
    result = [title + suffix]
    result.extend(lines or [empty])
    if total_pages > 1:
        result.append(f"Use {command_hint} <page|last|all> for more.")
    return result


async def _reply_audit_query(
    bot,
    msg,
    title: str,
    *,
    empty: str,
    page_args: list[str] | None = None,
    command_hint: str | None = None,
    actor: str | None = None,
    target: str | None = None,
    event: str | None = None,
) -> None:
    """Reply with a database-backed, paginated audit query."""
    page_request = parse_page_args(page_args or [])
    page_size = 10
    command_hint = command_hint or f"{config.get('prefix', ',')}audit last"
    total = await _count_events(bot, actor=actor, target=target, event=event)

    if page_request.all:
        rows = await _list_events(
            bot,
            limit=max(total, 1),
            actor=actor,
            target=target,
            event=event,
        )
    else:
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = total_pages if page_request.page == -1 else min(max(page_request.page, 1), total_pages)
        rows = await _list_events(
            bot,
            limit=page_size,
            offset=(page - 1) * page_size,
            actor=actor,
            target=target,
            event=event,
        )
        page_request = type(page_request)(page=page, all=False)

    bot.reply(
        msg,
        _format_audit_page(
            title,
            rows,
            empty=empty,
            page_request=page_request,
            total=total,
            page_size=page_size,
            command_hint=command_hint,
        ),
    )


def _parse_filter_command_args(args: list[str], usage: str) -> tuple[str | None, list[str], str | None]:
    """Return ``(value, page_args, error)`` for simple audit filters."""
    if not args:
        return None, [], usage
    value = str(args[0]).strip()
    if not value:
        return None, [], usage
    return value, list(args[1:]), None


def _parse_export_args(args: list[str]) -> tuple[int, dict[str, str], str | None]:
    """Parse audit export arguments."""
    limit = 100
    filters: dict[str, str] = {}
    remaining = list(args or [])
    if remaining and str(remaining[0]).isdigit():
        limit = max(1, min(int(remaining.pop(0)), 500))
    while remaining:
        key = remaining.pop(0).lower()
        if key in {"user", "actor"}:
            field = "actor"
        elif key in {"target", "room"}:
            field = "target"
        elif key in {"action", "event"}:
            field = "event"
        else:
            return limit, filters, f"invalid filter: {key}"
        if not remaining:
            return limit, filters, f"missing value for {key}"
        filters[field] = str(remaining.pop(0))
    return limit, filters, None


@command(
    "audit last",
    role=Role.ADMIN,
    aliases=["audit", "audits last"],
    short="Show recent admin audit events.",
    usage="{prefix}audit last [all|page|last|limit <n>]",
    examples=[
        "{prefix}audit last",
        "{prefix}audit last 2",
        "{prefix}audit last limit 50",
    ],
    category="admin",
    context="private recommended",
)
async def audit_last(bot, sender, nick, args, msg, is_room):
    """Show recent audit events."""
    if args and str(args[0]).lower() == "limit":
        if len(args) != 2 or not str(args[1]).isdigit():
            bot.reply_usage(msg, f"{bot.prefix}audit last [all|page|last|limit <n>]")
            return
        rows = await _list_events(bot, limit=max(1, min(int(args[1]), 100)))
        bot.reply(
            msg,
            _format_audit_page(
                "🧾 Audit log",
                rows,
                empty="No audit events found.",
                page_request=parse_page_args(["all"]),
                total=len(rows),
                page_size=10,
                command_hint=f"{bot.prefix}audit last",
            ),
        )
        return

    await _reply_audit_query(
        bot,
        msg,
        "🧾 Audit log",
        empty="No audit events found.",
        page_args=list(args or []),
        command_hint=f"{bot.prefix}audit last",
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
    if not args:
        bot.reply_usage(msg, f"{config.get('prefix', ',')}audit user <jid> [all|page|last]")
        return
    try:
        actor = str(JID(args[0]).bare)
    except Exception:
        bot.reply_error(msg, "Invalid JID.")
        return

    await _reply_audit_query(
        bot,
        msg,
        f"🧾 Audit log — actor={actor}",
        empty=f"No audit events found for {actor}.",
        page_args=list(args[1:]),
        command_hint=f"{config.get('prefix', ',')}audit user {actor}",
        actor=actor,
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
    target, page_args, error = _parse_filter_command_args(
        args,
        f"{config.get('prefix', ',')}audit target <target> [all|page|last]",
    )
    if error or target is None:
        bot.reply_usage(msg, error or f"{config.get('prefix', ',')}audit target <target>")
        return
    await _reply_audit_query(
        bot,
        msg,
        f"🧾 Audit log — target={target}",
        empty=f"No audit events found for target {target}.",
        page_args=page_args,
        command_hint=f"{config.get('prefix', ',')}audit target {target}",
        target=target,
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
    event, page_args, error = _parse_filter_command_args(
        args,
        f"{config.get('prefix', ',')}audit action <event_type> [all|page|last]",
    )
    if error or event is None:
        bot.reply_usage(msg, error or f"{config.get('prefix', ',')}audit action <event_type>")
        return
    await _reply_audit_query(
        bot,
        msg,
        f"🧾 Audit log — action={event}",
        empty=f"No audit events found for action {event}.",
        page_args=page_args,
        command_hint=f"{config.get('prefix', ',')}audit action {event}",
        event=event,
    )

@command(
    "audit export",
    role=Role.ADMIN,
    aliases=["audits export"],
    short="Export recent audit events as JSON Lines.",
    usage="{prefix}audit export [limit]",
    examples=[
        "{prefix}audit export",
        "{prefix}audit export 100",
    ],
    category="admin",
    context="private recommended",
)
async def audit_export(bot, sender, nick, args, msg, is_room):
    """Export recent audit events as JSON Lines."""
    limit, filters, error = _parse_export_args(args or [])
    if error:
        bot.reply_usage(
            msg,
            f"{config.get('prefix', ',')}audit export [limit] [user <jid>|target <target>|action <event>]",
        )
        return
    audit_log = getattr(getattr(bot, "db", None), "audit", None)
    exporter = getattr(audit_log, "export_jsonl", None)
    if not callable(exporter):
        bot.reply_error(msg, "Audit export is not available.")
        return
    payload = await exporter(limit=limit, **filters)
    if not payload:
        bot.reply(msg, "🧾 Audit export\nNo audit events found.")
        return
    suffix = "" if not filters else " · " + ", ".join(f"{k}={v}" for k, v in sorted(filters.items()))
    bot.reply(msg, f"🧾 Audit export (JSONL, newest {limit}{suffix})\n{payload}", no_store=True)


@command(
    "audit prune",
    role=Role.OWNER,
    aliases=["audits prune"],
    short="Prune old audit events after confirmation.",
    usage="{prefix}audit prune <days> [dry-run|confirm]",
    examples=[
        "{prefix}audit prune 90 dry-run",
        "{prefix}audit prune 90 confirm",
    ],
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
