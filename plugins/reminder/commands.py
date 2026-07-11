"""Split module for plugins/reminder.py: commands."""

import datetime
import pytz
from utils.command import command, Role
from utils.formatting import format_page, parse_page_args
from .parsing import get_reminder_tzinfo


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _utc_tz():
    return pytz.UTC


async def _get_reminder(bot, reminder_id: int) -> dict | None:
    """Return one reminder by ID, or None if it does not exist."""
    await _init_reminder_db(bot)

    rows = await bot.db.fetch_all(
        "SELECT * FROM reminders WHERE id = ?",
        (reminder_id,),
    )

    if not rows:
        return None

    return dict(rows[0])


async def _get_pending_reminders(bot, user_jid: str) -> list[dict]:
    """Return pending reminders for one user ordered by due date."""
    await _init_reminder_db(bot)

    rows = await bot.db.fetch_all(
        """
        SELECT * FROM reminders
        WHERE user_jid = ? AND is_active = 1
        ORDER BY remind_at ASC
        """,
        (user_jid,),
    )

    return [dict(row) for row in rows]


async def _get_all_pending_reminders(bot) -> list[dict]:
    """Return all pending reminders ordered by due date."""
    await _init_reminder_db(bot)

    rows = await bot.db.fetch_all(
        """
        SELECT * FROM reminders
        WHERE is_active = 1
        ORDER BY remind_at ASC
        """
    )

    return [dict(row) for row in rows]


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
