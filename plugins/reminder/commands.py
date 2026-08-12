"""Reminder commands and room/global control."""

from __future__ import annotations

import asyncio
import datetime

from core_plugins._core import get_reply_target, handle_room_toggle_command
from utils.command import Role, command
from utils.config import config
from utils.formatting import format_page, parse_page_args

from . import runtime
from .config import REMINDER_KEY
from .events import _reply_message_text
from .formatting import (
    _is_reminder_enabled_for_context,
    _reminder_context,
    _room_jid_from_context,
)
from .parsing import (
    _format_local_datetime,
    _parse_datetime,
    _utcnow,
    explain_invalid_reminder_time,
    format_seconds,
    get_reminder_tzinfo,
    parse_reminder_when,
)
from .store import (
    _create_reminder,
    _delete_reminder,
    _get_pending_reminders,
    _get_reminder,
    _get_room_reminder_state,
    get_reminder_store,
)
from .tasks import (
    _cancel_active_tasks_for_room,
    _cancel_all_active_tasks,
    _restore_pending_reminders,
    _schedule_task,
)

log = runtime.log


async def _handle_reminder_control_command(bot, args,
                                           msg, is_room: bool) -> bool:
    """Handle reminder on/off/status.

    Room contexts are delegated to
    utils.plugin_helper.handle_room_toggle_command.  Normal DMs control
    the global runtime kill-switch.
    """
    if not args:
        return False

    subcmd = str(args[0]).lower()
    if subcmd not in {"on", "off", "status"}:
        return False

    room_jid = _room_jid_from_context(msg, is_room)

    if room_jid:
        before = await _get_room_reminder_state(bot, room_jid)

        handled = await handle_room_toggle_command(
            bot,
            msg,
            is_room,
            args,
            store_getter=get_reminder_store,
            key=REMINDER_KEY,
            label="Use 'reminder' commands",
            plugin="reminder",
            storage="dict",
            log_prefix="[REMINDER]",
        )

        if handled:
            after = await _get_room_reminder_state(bot, room_jid)

            if subcmd == "on" and not before and after and runtime.REMINDER_ENABLED:
                restored = await _restore_pending_reminders(bot)
                log.info(
                    "[REMINDER] Room %s enabled via helper; restored %s"
                    " reminders",
                    room_jid,
                    restored,
                )

            elif subcmd == "off" and before and not after:
                cancelled = await _cancel_active_tasks_for_room(bot, room_jid)
                log.info(
                    "[REMINDER] Room %s disabled via helper; cancelled %s"
                    " tasks",
                    room_jid,
                    cancelled,
                )

        return handled

    # Normal DM: global runtime switch.
    if subcmd == "status":
        global_state = "on" if runtime.REMINDER_ENABLED else "off"
        active_count = sum(
            1 for task in runtime.ACTIVE_REMINDERS.values() if not task.done())
        bot.reply(
            msg,
            f"ℹ️ Reminder plugin global: {global_state}. "
            f"Active scheduled reminders: {active_count}.",
        )
        return True

    if subcmd == "on":
        if runtime.REMINDER_ENABLED:
            bot.reply(msg, "ℹ️ Reminder plugin is already globally on.")
            return True

        runtime.REMINDER_ENABLED = True
        restored = await _restore_pending_reminders(bot)
        bot.reply(
            msg,
            f"▶️ Reminder plugin enabled globally. "
            f"Restored {restored} pending reminder task(s).",
        )
        log.info("[REMINDER] Plugin enabled globally; restored %s reminders",
                 restored)
        return True

    if not runtime.REMINDER_ENABLED:
        bot.reply(msg, "ℹ️ Reminder plugin is already globally off.")
        return True

    runtime.REMINDER_ENABLED = False
    cancelled = await _cancel_all_active_tasks()
    bot.reply(
        msg,
        f"⏸️ Reminder plugin disabled globally. Pending reminders stay saved. "
        f"Cancelled {cancelled} active task(s).",
    )
    log.info("[REMINDER] Plugin disabled globally; cancelled %s tasks",
             cancelled)
    return True
@command(
    "remind",
    role=Role.USER,
    aliases=["rem", "reminder"],
    short="Create a reminder.",
    usage="{prefix}remind <when> [text or reply]",
    examples=[
        "{prefix}remind 10m check logs",
        "Reply to a message with {prefix}remind 1h",
        "{prefix}remind 2026-05-01 14:30 Take a break",
        "Reply to a message with {prefix}remind 2026-05-01 14:30",
        "{prefix}remind 2026-05-01 14:30 CEST Take a break",
        "{prefix}remind 2026-05-01 14:30 Europe/Berlin Take a break",
        "{prefix}remind 2026-05-01 14:30 +02:00 Take a break",
        "{prefix}timezone set Europe/Berlin",
        "{prefix}rooms enable reminder",
    ],
    category="utility",
    context="any",
)
async def remind_command(bot, sender_jid, nick, args, msg, is_room):
    """Set a new reminder."""
    prefix = config.get("prefix", ",")

    if await _handle_reminder_control_command(bot, args, msg, is_room):
        return

    if not runtime.REMINDER_ENABLED:
        bot.reply(
            msg,
            f"⏸️ Reminder plugin is globally off. Use {
                prefix}remind on in a DM to enable it.",
        )
        return

    if not await _is_reminder_enabled_for_context(bot, msg, is_room):
        bot.reply(
            msg,
            f"⏸️ Reminders are disabled for this room. Use {
                prefix}reminder on in a MUC DM to enable them here.",
        )
        return

    try:
        ctx = _reminder_context(bot, sender_jid, nick, msg, is_room)
        user_tz = await get_reminder_tzinfo(bot, ctx.get("timezone_jid"))

        parse_args = list(args or [])
        reply_target_id = get_reply_target(msg)
        reply_text = None
        seconds, message, display_when = parse_reminder_when(
            parse_args,
            user_tz,
        )

        if seconds is None or not message:
            reply_text = _reply_message_text(bot, msg, is_room)
            if reply_text:
                parse_args = [*parse_args, reply_text]
                seconds, message, display_when = parse_reminder_when(
                    parse_args,
                    user_tz,
                )

        if seconds is None or seconds < 1 or not message:
            detail = explain_invalid_reminder_time(parse_args, user_tz)
            probe_seconds, probe_message, _probe_when = parse_reminder_when(
                [*list(args or []), "__reply_message__"],
                user_tz,
            )
            valid_reply_time = bool(probe_seconds and probe_message)

            if reply_target_id and not reply_text and valid_reply_time:
                bot.reply(
                    msg,
                    "❌ Could not resolve the replied-to message. It may no "
                    "longer be available in the shared message cache. Add "
                    "the reminder text explicitly.",
                )
            elif detail:
                bot.reply(msg, detail)
            elif len(args or []) < 2:
                bot.reply(
                    msg,
                    f"ℹ️ Usage: {prefix}remind <duration|date time> <message>\n"
                    "Or reply to a message with: "
                    f"{prefix}remind <duration|date time>\n"
                    f"Example: {prefix}remind 30m Take a break\n"
                    f"Reply example: {prefix}remind 1h\n"
                    "Example: "
                    f"{prefix}remind 2026-05-01 14:30 Take a break\n"
                    "Example: "
                    f"{prefix}remind 2026-05-01 14:30 CEST Take a break\n"
                    "Example: "
                    f"{prefix}remind 01.05.2026 14:30 Take a break\n"
                    "Formats: 10s, 5m, 1h, 2d, 1h30m, "
                    "YYYY-MM-DD HH:MM, DD.MM.YYYY HH:MM, optional TZ "
                    f"(max {config.get('reminder_max_age_days', 365)} days)",
                )
            else:
                bot.reply(
                    msg,
                    "❌ Invalid reminder time.\n"
                    "Use relative format: 10s, 5m, 1h, 2d, 1h30m\n"
                    "Or absolute format: 2026-05-01 14:30, "
                    "2026-05-01 14:30 CEST, "
                    "2026-05-01 14:30 +02:00, 01.05.2026 14:30",
                )
            return

        max_days = config.get("reminder_max_age_days", 365)
        max_seconds = max_days * 24 * 3600

        if seconds > max_seconds:
            bot.reply(msg, f"❌ Reminder too far in the future. Maximum is {
                      max_days} days.")
            return

        if len(message) > 500:
            bot.reply(msg, "❌ Message too long. Maximum is 500 characters.")
            return

        user_jid = ctx["user_jid"]
        display_nick = ctx["display_nick"]
        room_jid = ctx["room_jid"]
        msg_mto = ctx["msg_mto"]
        msg_type = ctx["msg_type"]

        scheduled_at = _utcnow()
        remind_at = scheduled_at + datetime.timedelta(seconds=seconds)

        reminder_id = await _create_reminder(
            bot,
            user_jid=user_jid,
            message=message,
            scheduled_at=scheduled_at,
            remind_at=remind_at,
            room_jid=room_jid,
        )

        _schedule_task(
            bot,
            reminder_id,
            user_jid,
            display_nick,
            message,
            seconds,
            msg,
            room_jid=room_jid,
            msg_mto=msg_mto,
            msg_type=msg_type,
        )

        bot.reply(msg, f"✅ Reminder set! I'll remind you {display_when}")
        log.info("[REMINDER] Created reminder %s for %s", reminder_id,
                 user_jid)

    except Exception as exc:
        log.exception("[REMINDER] Error creating reminder: %s", exc)
        bot.reply(msg, "❌ Error creating reminder. Please try again.")
@command(
    "remind status",
    role=Role.USER,
    aliases=["rem status", "reminder status"],
    short="Show whether reminders are enabled.",
    usage="{prefix}remind status",
    examples=["{prefix}remind status"],
    category="utility",
    context="room, MUC PM or private chat",
)
async def remind_status_command(bot, sender_jid, nick, args, msg, is_room):
    """Show reminder status for the current context."""
    await remind_command(bot, sender_jid, nick, ["status", *(args or [])], msg, is_room)
@command(
    "remind on",
    role=Role.USER,
    aliases=["rem on", "reminder on"],
    short="Enable reminders globally or for the current room.",
    usage="{prefix}remind on",
    examples=["{prefix}remind on", "{prefix}rooms enable reminder"],
    category="utility",
    context="room, MUC PM or private chat",
)
async def remind_on_command(bot, sender_jid, nick, args, msg, is_room):
    """Enable reminders in the current context."""
    await remind_command(bot, sender_jid, nick, ["on", *(args or [])], msg, is_room)
@command(
    "remind off",
    role=Role.USER,
    aliases=["rem off", "reminder off"],
    short="Disable reminders globally or for the current room.",
    usage="{prefix}remind off",
    examples=["{prefix}remind off", "{prefix}rooms disable reminder"],
    category="utility",
    context="room, MUC PM or private chat",
)
async def remind_off_command(bot, sender_jid, nick, args, msg, is_room):
    """Disable reminders in the current context."""
    await remind_command(bot, sender_jid, nick, ["off", *(args or [])], msg, is_room)
@command(
    "remind delete",
    role=Role.USER,
    aliases=["remind rm", "remind cancel"],
    short="Delete one reminder.",
    usage="{prefix}remind delete <id>",
    examples=["{prefix}remind delete 12"],
    category="utility",
    context="any",
)
async def delete_reminder(bot, sender_jid, nick, args, msg, is_room):
    """Delete or cancel a reminder by ID."""
    prefix = config.get("prefix", ",")

    if not args:
        bot.reply(msg, f"ℹ️ Usage: {prefix}remind delete <id>")
        return

    try:
        reminder_id = int(args[0])
    except ValueError:
        bot.reply(msg, "❌ Reminder ID must be a number.")
        return

    try:
        ctx = _reminder_context(bot, sender_jid, nick, msg, is_room)
        user_jid = ctx["user_jid"]

        reminder = await _get_reminder(bot, reminder_id)

        if not reminder:
            bot.reply(msg, "❌ Reminder not found.")
            return

        if reminder["user_jid"] != user_jid:
            bot.reply(msg, "❌ You can only delete your own reminders.")
            return

        await _delete_reminder(bot, reminder_id)

        task = runtime.ACTIVE_REMINDERS.pop(reminder_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                log.debug("[REMINDER] Deleted reminder task %s cancelled", reminder_id)

        bot.reply(msg, f"✅ Reminder {reminder_id} deleted.")
        log.info("[REMINDER] Deleted reminder %s", reminder_id)

    except Exception as exc:
        log.exception("[REMINDER] Error deleting reminder: %s", exc)
        bot.reply(msg, "❌ Error deleting reminder.")
@command(
    "reminders",
    role=Role.USER,
    aliases=["rems", "remind list"],
    short="List your reminders.",
    usage="{prefix}reminders [all|page|last]",
    examples=["{prefix}reminders"],
    category="utility",
    context="any",
)
async def list_reminders(bot, sender_jid, nick, args, msg, is_room):
    """List all pending reminders for the current user."""
    try:
        ctx = _reminder_context(bot, sender_jid, nick, msg, is_room)
        user_jid = ctx["user_jid"]
        user_tz = await get_reminder_tzinfo(bot, ctx.get("timezone_jid"))

        reminders = await _get_pending_reminders(bot, user_jid)

        if not reminders:
            bot.reply(msg, "✅ No pending reminders.")
            return

        page_request = parse_page_args(args or [])
        lines = []

        for reminder in reminders:
            remind_at = _parse_datetime(reminder["remind_at"])
            time_left = remind_at - _utcnow()
            time_str = format_seconds(time_left.total_seconds())
            local_time = _format_local_datetime(remind_at, user_tz)

            lines.append(
                f"• ID {reminder['id']}: {reminder['message']} "
                f"(in {time_str}, at {local_time})"
            )

        bot.reply(
            msg,
            "\n".join(format_page(
                "⏰ Your pending reminders:",
                lines,
                page_request=page_request,
                page_size=10,
                command_hint=f"{getattr(bot, 'prefix', ',')}reminders",
            )),
        )

    except Exception as exc:
        log.exception("[REMINDER] Error listing reminders: %s", exc)
        bot.reply(msg, "❌ Error retrieving reminders.")
