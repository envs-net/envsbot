"""Schedule and manage reminders.

Schedule reminders to notify you at a later time.

Commands:
• {prefix}remind <duration> <message>   - Set a new reminder
• {prefix}reminders                     - List all your pending reminders
• {prefix}remind delete <id>            - Delete a reminder by ID

Duration formats:
• Single: 10s, 5m, 1h, 2d
• Combined: 1h30m, 2d5h, 3d12h30m45s

Examples:
• {prefix}remind 30m Take a break
• {prefix}remind 1h Important meeting
• {prefix}remind 2d5h3m20s Long term goal with exact time
• {prefix}reminders
• {prefix}remind delete 1

Limits:
• Maximum reminder duration: 365 days by default
• Maximum message length: 500 characters
"""

import asyncio
import datetime
import logging
import re

from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "reminder",
    "version": "0.1.1",
    "description": "Schedule and manage reminders",
    "category": "utility",
}

# In-memory storage of active asyncio tasks: {reminder_id: task}
ACTIVE_REMINDERS: dict[int, asyncio.Task] = {}


# ============================================================================
# HELPERS
# ============================================================================

def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _normalize_user_jid(sender_jid) -> str:
    """Return a stable bare JID-ish string for ownership checks.

    This avoids storing resource/nick variants for the same user when possible.
    """
    value = str(sender_jid)

    if "/" in value:
        return value.split("/", 1)[0]

    return value


def _display_nick(sender_jid, nick: str | None = None) -> str:
    """Best-effort display name for reminder messages."""
    if nick:
        return str(nick)

    value = str(sender_jid)

    if "/" in value:
        resource = value.rsplit("/", 1)[-1]
        if resource:
            return resource

    if "@" in value:
        return value.split("@", 1)[0]

    return value


def _is_muc_pm(msg, is_room: bool) -> bool:
    """Return True for private messages from a MUC occupant."""
    if is_room:
        return False

    try:
        return msg["from"].bare in JOINED_ROOMS
    except Exception:
        return False


def _reminder_context(sender_jid, nick, msg, is_room: bool):
    """Build stable ownership and delivery context.

    Cases:
    - normal DM: send chat to bare user JID
    - MUC: send groupchat to room bare JID
    - MUC-PM: send chat to full occupant JID room@conference/nick
    """
    if is_room:
        room_jid = msg["from"].bare
        user_jid = _normalize_user_jid(sender_jid)
        display_nick = _display_nick(sender_jid, nick)

        return {
            "user_jid": user_jid,
            "display_nick": display_nick,
            "room_jid": room_jid,
            "msg_mto": room_jid,
            "msg_type": "groupchat",
        }

    if _is_muc_pm(msg, is_room):
        muc_occupant_jid = str(msg["from"])
        display_nick = msg["from"].resource or _display_nick(sender_jid, nick)

        return {
            "user_jid": muc_occupant_jid,
            "display_nick": display_nick,
            "room_jid": None,
            "msg_mto": muc_occupant_jid,
            "msg_type": "chat",
        }

    user_jid = _normalize_user_jid(sender_jid)

    return {
        "user_jid": user_jid,
        "display_nick": _display_nick(sender_jid, nick),
        "room_jid": None,
        "msg_mto": user_jid,
        "msg_type": "chat",
    }


def parse_duration(duration_str: str) -> int | None:
    """Parse a duration string to seconds.

    Supports:
    - Single formats: 10s, 5m, 1h, 2d
    - Combined formats: 2d5h3m20s, 1h30m, 3d12h
    """
    if not duration_str:
        return None

    duration_str = duration_str.lower().strip()

    pattern = r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?"
    match = re.fullmatch(pattern, duration_str)

    if not match:
        return None

    days, hours, minutes, seconds = match.groups()

    if not any([days, hours, minutes, seconds]):
        return None

    total_seconds = (
        (int(days) if days else 0) * 86400
        + (int(hours) if hours else 0) * 3600
        + (int(minutes) if minutes else 0) * 60
        + (int(seconds) if seconds else 0)
    )

    return total_seconds if total_seconds > 0 else None


def format_seconds(total_seconds: float) -> str:
    """Convert seconds to a human-readable duration."""
    if total_seconds < 0:
        return "overdue"

    days = int(total_seconds // 86400)
    remaining = total_seconds % 86400

    hours = int(remaining // 3600)
    remaining %= 3600

    minutes = int(remaining // 60)
    seconds = int(remaining % 60)

    parts = []

    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


def _format_overdue(seconds: float) -> str:
    overdue_seconds = abs(seconds)

    if overdue_seconds < 60:
        return f"{int(overdue_seconds)}s ago"
    if overdue_seconds < 3600:
        return f"{int(overdue_seconds / 60)}m ago"
    if overdue_seconds < 86400:
        return f"{overdue_seconds / 3600:.1f}h ago"

    return f"{overdue_seconds / 86400:.1f}d ago"


def _parse_datetime(value) -> datetime.datetime:
    """Handle DB values returned as datetime or ISO string."""
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        dt = datetime.datetime.fromisoformat(str(value))

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    return dt


async def _send_reminder_message(bot, mto: str, mbody: str, mtype: str):
    """Send reminder as a fresh message.

    Do not use bot.reply() here because delayed reminders should not depend on
    an old message object or client-specific reply/thread rendering.
    """
    msg = bot.make_message(
        mto=mto,
        mbody=mbody,
        mtype=mtype,
    )

    if hasattr(bot, "_safe_send_message"):
        await bot._safe_send_message(msg)
    else:
        msg.send()


async def schedule_reminder_task(
    bot,
    reminder_id: int,
    user_jid: str,
    nick: str,
    message: str,
    seconds: float,
    original_msg,
    overdue_str: str | None = None,
    room_jid: str | None = None,
    msg_mto: str | None = None,
    msg_type: str | None = None,
):
    """Background task that waits and sends the reminder.

    Works for both new reminders and restored reminders after bot restart.
    """
    try:
        await asyncio.sleep(max(0.1, float(seconds)))

        if room_jid:
            if overdue_str:
                reminder_text = f"🔔 {nick}: Reminder (was due {overdue_str}): {message}"
            else:
                reminder_text = f"🔔 {nick}: Reminder: {message}"
        else:
            if overdue_str:
                reminder_text = f"🔔 Reminder (was due {overdue_str}): {message}"
            else:
                reminder_text = f"🔔 Reminder: {message}"

        try:
            target = msg_mto or (room_jid if room_jid else user_jid)
            message_type = msg_type or ("groupchat" if room_jid else "chat")

            await _send_reminder_message(
                bot,
                mto=target,
                mbody=reminder_text,
                mtype=message_type,
            )

            log.info(
                "[REMINDER] ✅ Reminder %s sent to %s",
                reminder_id,
                target,
            )

        except Exception as exc:
            log.exception(
                "[REMINDER] Failed to send reminder %s: %s",
                reminder_id,
                exc,
            )
            return

        await bot.db.reminders.delete(reminder_id)
        log.info("[REMINDER] ✅ Reminder %s deleted after sending", reminder_id)

    except asyncio.CancelledError:
        log.debug("[REMINDER] ⚠️ Reminder %s was cancelled", reminder_id)
        raise

    except Exception as exc:
        log.exception("[REMINDER] Error in reminder task %s: %s", reminder_id, exc)

    finally:
        ACTIVE_REMINDERS.pop(reminder_id, None)


def _schedule_task(
    bot,
    reminder_id: int,
    user_jid: str,
    nick: str,
    message: str,
    seconds: float,
    original_msg,
    overdue_str: str | None = None,
    room_jid: str | None = None,
    msg_mto: str | None = None,
    msg_type: str | None = None,
):
    """Create or replace an active reminder task safely."""
    old_task = ACTIVE_REMINDERS.get(reminder_id)

    if old_task and not old_task.done():
        old_task.cancel()

    task = asyncio.create_task(
        schedule_reminder_task(
            bot,
            reminder_id,
            user_jid,
            nick,
            message,
            seconds,
            original_msg,
            overdue_str=overdue_str,
            room_jid=room_jid,
            msg_mto=msg_mto,
            msg_type=msg_type,
        )
    )

    ACTIVE_REMINDERS[reminder_id] = task
    return task


# ============================================================================
# COMMANDS
# ============================================================================

@command("remind", role=Role.USER, aliases=["rem"])
async def remind_command(bot, sender_jid, nick, args, msg, is_room):
    """Set a new reminder."""
    prefix = config.get("prefix", ",")

    if len(args) < 2:
        bot.reply(
            msg,
            f"ℹ️ Usage: {prefix}remind <duration> <message>\n"
            f"Example: {prefix}remind 30m Take a break\n"
            "Formats: 10s, 5m, 1h, 2d, 1h30m "
            f"(max {config.get('reminder_max_age_days', 365)} days)",
        )
        return

    duration_str = args[0]
    message = " ".join(args[1:]).strip()

    seconds = parse_duration(duration_str)

    if seconds is None or seconds < 1:
        bot.reply(msg, "❌ Invalid duration. Use format: 10s, 5m, 1h, 2d, 1h30m")
        return

    max_days = config.get("reminder_max_age_days", 365)
    max_seconds = max_days * 24 * 3600

    if seconds > max_seconds:
        bot.reply(msg, f"❌ Duration too long. Maximum is {max_days} days.")
        return

    if len(message) > 500:
        bot.reply(msg, "❌ Message too long. Maximum is 500 characters.")
        return

    try:
        ctx = _reminder_context(sender_jid, nick, msg, is_room)

        user_jid = ctx["user_jid"]
        display_nick = ctx["display_nick"]
        room_jid = ctx["room_jid"]
        msg_mto = ctx["msg_mto"]
        msg_type = ctx["msg_type"]

        scheduled_at = _utcnow()
        remind_at = scheduled_at + datetime.timedelta(seconds=seconds)

        reminder_id = await bot.db.reminders.create(
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

        bot.reply(msg, f"✅ Reminder set! I'll remind you in {format_seconds(seconds)}")
        log.info("[REMINDER] Created reminder %s for %s: %s", reminder_id, user_jid, message)

    except Exception as exc:
        log.exception("[REMINDER] Error creating reminder: %s", exc)
        bot.reply(msg, "❌ Error creating reminder. Please try again.")


@command("reminders", role=Role.USER, aliases=["rems", "remind list"])
async def list_reminders(bot, sender_jid, nick, args, msg, is_room):
    """List all pending reminders for the current user."""
    try:
        ctx = _reminder_context(sender_jid, nick, msg, is_room)
        user_jid = ctx["user_jid"]

        reminders = await bot.db.reminders.get_pending(user_jid)

        if not reminders:
            bot.reply(msg, "✅ No pending reminders.")
            return

        lines = ["⏰ Your pending reminders:"]

        for reminder in reminders:
            remind_at = _parse_datetime(reminder["remind_at"])
            time_left = remind_at - _utcnow()
            time_str = format_seconds(time_left.total_seconds())

            lines.append(
                f"• ID {reminder['id']}: {reminder['message']} "
                f"(in {time_str})"
            )

        bot.reply(msg, "\n".join(lines))

    except Exception as exc:
        log.exception("[REMINDER] Error listing reminders: %s", exc)
        bot.reply(msg, "❌ Error retrieving reminders.")


@command("remind delete", role=Role.USER, aliases=["remind rm", "remind cancel"])
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
        ctx = _reminder_context(sender_jid, nick, msg, is_room)
        user_jid = ctx["user_jid"]

        reminder = await bot.db.reminders.get(reminder_id)

        if not reminder:
            bot.reply(msg, "❌ Reminder not found.")
            return

        if reminder["user_jid"] != user_jid:
            bot.reply(msg, "❌ You can only delete your own reminders.")
            return

        await bot.db.reminders.delete(reminder_id)

        task = ACTIVE_REMINDERS.pop(reminder_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        bot.reply(msg, f"✅ Reminder {reminder_id} deleted.")
        log.info("[REMINDER] Deleted reminder %s", reminder_id)

    except Exception as exc:
        log.exception("[REMINDER] Error deleting reminder: %s", exc)
        bot.reply(msg, "❌ Error deleting reminder.")


# ============================================================================
# PLUGIN LIFECYCLE
# ============================================================================

async def on_ready(bot):
    """Restore pending reminders from the database after startup/reload."""
    try:
        log.info("[REMINDER] Loading pending reminders from database...")

        pending = await bot.db.reminders.get_all_pending()

        if not pending:
            log.info("[REMINDER] ✅ No pending reminders to restore")
            return

        restored = 0
        now = _utcnow()

        for reminder in pending:
            reminder_id = reminder["id"]
            user_jid = reminder["user_jid"]
            room_jid = reminder.get("room_jid")
            message = reminder["message"]
            remind_at = _parse_datetime(reminder["remind_at"])

            existing_task = ACTIVE_REMINDERS.get(reminder_id)
            if existing_task and not existing_task.done():
                log.debug("[REMINDER] Reminder %s already scheduled; skipping", reminder_id)
                continue

            time_left = remind_at - now
            seconds_left = time_left.total_seconds()
            overdue_str = None

            if seconds_left < 0.1:
                overdue_str = _format_overdue(seconds_left)
                log.info(
                    "[REMINDER] ⏰ Reminder %s is overdue (%s), sending now",
                    reminder_id,
                    overdue_str,
                )
                seconds_left = 0.1

            display_nick = _display_nick(user_jid)

            # Backwards-compatible delivery restore:
            # - room_jid set: old/new MUC reminder -> send groupchat to room
            # - user_jid contains "/" and looks like room@conference/nick:
            #   MUC-PM reminder -> send chat to full occupant JID
            # - otherwise normal DM -> send chat to bare user JID
            if room_jid:
                msg_mto = room_jid
                msg_type = "groupchat"
            else:
                msg_mto = user_jid
                msg_type = "chat"

            try:
                _schedule_task(
                    bot,
                    reminder_id,
                    user_jid,
                    display_nick,
                    message,
                    seconds_left,
                    None,
                    overdue_str=overdue_str,
                    room_jid=room_jid,
                    msg_mto=msg_mto,
                    msg_type=msg_type,
                )

                restored += 1
                hours = seconds_left / 3600

                log.info(
                    "[REMINDER] ✅ Restored reminder %s: %s (%.1fh remaining)",
                    reminder_id,
                    message,
                    hours,
                )

            except Exception as exc:
                log.exception(
                    "[REMINDER] Error restoring reminder %s: %s",
                    reminder_id,
                    exc,
                )

        if restored > 0:
            log.info("[REMINDER] ✅ Successfully restored %s pending reminders", restored)

    except Exception as exc:
        log.exception("[REMINDER] Error during reminder restoration: %s", exc)


async def on_unload(bot):
    """Cancel all active reminder tasks."""
    try:
        log.info("[REMINDER] Unloading reminder plugin...")

        for reminder_id, task in list(ACTIVE_REMINDERS.items()):
            try:
                task.cancel()
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.exception(
                    "[REMINDER] Error cancelling reminder %s: %s",
                    reminder_id,
                    exc,
                )

        ACTIVE_REMINDERS.clear()
        log.info("[REMINDER] ✅ Plugin unloaded")

    except Exception as exc:
        log.exception("[REMINDER] Error during plugin unload: %s", exc)
