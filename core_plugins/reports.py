"""Optional daily operational report delivered through XMPP."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from utils.admin_notify import admin_notify_target, notify_admin
from utils.admin_reports import build_daily_admin_report
from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand
from utils.task_supervisor import create_resilient_plugin_task

PLUGIN_META = {
    "name": "reports",
    "version": "1.0.0",
    "description": "Optional daily admin health report.",
    "category": "core",
}

_REPORT_TASK = None


def _timezone(bot):
    value = str((getattr(bot, "config", {}) or {}).get("admin_report_timezone") or "").strip()
    if not value:
        value = str((getattr(bot, "config", {}) or {}).get("timezone") or "UTC")
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _report_time(bot) -> tuple[int, int]:
    raw = str((getattr(bot, "config", {}) or {}).get("admin_report_time", "08:00") or "08:00")
    try:
        hour_text, minute_text = raw.split(":", 1)
        hour = min(23, max(0, int(hour_text)))
        minute = min(59, max(0, int(minute_text)))
    except (TypeError, ValueError):
        hour, minute = 8, 0
    return hour, minute


def _next_report_at(bot, *, now: datetime | None = None) -> datetime:
    tz = _timezone(bot)
    local_now = now.astimezone(tz) if now is not None else datetime.now(tz)
    hour, minute = _report_time(bot)
    target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local_now:
        target += timedelta(days=1)
    return target


async def send_report(bot, *, manual: bool = False) -> bool:
    report = await build_daily_admin_report(bot)
    day = datetime.now(_timezone(bot)).strftime("%Y-%m-%d")
    return await notify_admin(
        bot,
        report,
        category="admin_report",
        dedupe_key=None if manual else f"daily-admin-report:{day}",
    )


async def _report_loop(bot) -> None:
    while True:
        target = _next_report_at(bot)
        delay = max(1.0, (target - datetime.now(target.tzinfo)).total_seconds())
        await asyncio.sleep(delay)
        await send_report(bot)


async def on_ready(bot):
    global _REPORT_TASK
    if not bool((getattr(bot, "config", {}) or {}).get("admin_report_enabled", False)):
        return
    if _REPORT_TASK is not None and not _REPORT_TASK.done():
        return
    _REPORT_TASK = create_resilient_plugin_task(
        bot,
        "reports",
        lambda: _report_loop(bot),
        name="daily-admin-report",
    )


async def on_unload(bot):
    global _REPORT_TASK
    if _REPORT_TASK is not None and not _REPORT_TASK.done():
        _REPORT_TASK.cancel()
        await asyncio.gather(_REPORT_TASK, return_exceptions=True)
    _REPORT_TASK = None


async def restart_tasks(bot):
    await on_unload(bot)
    await on_ready(bot)


@command(
    "report",
    role=Role.ADMIN,
    short="Show or send the optional daily operational report.",
    usage="{prefix}report <now|status>",
    subcommands=[
        help_subcommand(
            "now",
            "now",
            "Generate and send the report now.",
            examples=[help_example("{prefix}report now", "Send the report immediately.")],
        ),
        help_subcommand(
            "status",
            "status",
            "Show report scheduling and destination.",
            examples=[help_example("{prefix}report status", "Inspect the daily schedule.")],
        ),
    ],
    examples=[
        help_example("{prefix}report now", "Send a health report immediately."),
        help_example("{prefix}report status", "Inspect the configured schedule."),
    ],
    category="Admin",
    context="private chat / MUC PM",
)
async def report_command(bot, sender, nick, args, msg, is_room):
    del sender, nick, is_room
    subcommand = str(args[0]).lower() if args else "status"
    if subcommand == "now":
        if await send_report(bot, manual=True):
            bot.reply_ok(msg, "Admin report sent or durably queued.")
        else:
            bot.reply_error(msg, "No admin report destination is configured.")
        return
    if subcommand != "status":
        bot.reply_usage(msg, f"{bot.prefix}report <now|status>")
        return
    config = getattr(bot, "config", {}) or {}
    enabled = bool(config.get("admin_report_enabled", False))
    next_at = _next_report_at(bot).isoformat(timespec="minutes")
    bot.reply(
        msg,
        [
            "🩺 Daily admin report",
            f"• enabled: {enabled}",
            f"• destination: {admin_notify_target(bot) or '-'}",
            f"• next run: {next_at}",
            f"• worker: {'running' if _REPORT_TASK and not _REPORT_TASK.done() else 'stopped'}",
        ],
    )


async def get_runtime_state(bot, room_jid=None):
    del room_jid
    config = getattr(bot, "config", {}) or {}
    return {
        "enabled": bool(config.get("admin_report_enabled", False)),
        "destination_configured": bool(admin_notify_target(bot)),
        "worker_running": bool(_REPORT_TASK and not _REPORT_TASK.done()),
        "next_run": _next_report_at(bot).isoformat(timespec="minutes"),
    }


async def doctor(bot, room_jid=None):
    state = await get_runtime_state(bot, room_jid)
    if not state["enabled"]:
        return {"ok": True, "summary": "daily report disabled"}
    ok = state["destination_configured"] and state["worker_running"]
    return {
        "ok": ok,
        "summary": (
            f"destination={'configured' if state['destination_configured'] else 'missing'}, "
            f"worker={'running' if state['worker_running'] else 'stopped'}"
        ),
    }
