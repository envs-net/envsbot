"""
Schedule and manage reminders.

Schedule reminders to notify you at a later time.

**Commands:**
• {prefix}remind <duration> <message> — Set a new reminder
• {prefix}reminders — List all your pending reminders
• {prefix}remind delete <id> — Delete a reminder by ID

**Duration Formats:**
• Single: 10s, 5m, 1h, 2d
• Combined: 1h30m, 2d5h, 3d12h30m45s

**Examples:**
• {prefix}remind 30m Take a break
• {prefix}remind 1h Important meeting
• {prefix}remind 2d5h3m20s Long term goal with exact time
• {prefix}remind 1h30m Team standup
• {prefix}reminders
• {prefix}remind delete 1

**Limits:**
• Maximum reminder duration: 365 days
• Maximum message length: 500 characters
"""

import asyncio
import datetime
import re
import logging
from utils.command import command, Role
from utils.config import config

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "reminder",
    "version": "0.1.0",
    "description": "Schedule and manage reminders (max 365 days)",
    "category": "utility",
}

# In-memory storage of active asyncio tasks: {reminder_id: task}
ACTIVE_REMINDERS = {}

# ============================================================================
# HELPERS
# ============================================================================

def parse_duration(duration_str: str) -> int:
    """
    Parse duration string to seconds.

    Supports:
    - Single formats: 10s, 5m, 1h, 2d
    - Combined formats: 2d5h3m20s, 1h30m, 3d12h, etc.

    Returns: seconds as int, or None if invalid

    Examples:
        - "30s" → 30
        - "5m" → 300
        - "1h30m" → 5400
        - "2d5h3m20s" → 183800
    """
    duration_str = duration_str.lower().strip()

    if not duration_str:
        return None

    # Pattern for each unit (optional)
    pattern = r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
    match = re.match(f'^{pattern}$', duration_str)

    if not match or duration_str == '':
        return None

    days, hours, minutes, seconds = match.groups()

    # At least one unit must be specified
    if not any([days, hours, minutes, seconds]):
        return None

    total_seconds = (
        (int(days) if days else 0) * 86400 +
        (int(hours) if hours else 0) * 3600 +
        (int(minutes) if minutes else 0) * 60 +
        (int(seconds) if seconds else 0)
    )

    return total_seconds if total_seconds > 0 else None


def format_seconds(total_seconds: float) -> str:
    """
    Convert seconds to human-readable format.

    Examples:
        30 → "30s"
        90 → "1m 30s"
        3661 → "1h 1m 1s"
        183800 → "2d 5h 3m 20s"
    """
    if total_seconds < 0:
        return "overdue"

    days = int(total_seconds // 86400)
    remaining = total_seconds % 86400

    hours = int(remaining // 3600)
    remaining = remaining % 3600

    minutes = int(remaining // 60)
    seconds = int(remaining % 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts:  # Show seconds if nothing else or if it's the only unit
        parts.append(f"{seconds}s")

    return " ".join(parts)


async def schedule_reminder_task(bot, reminder_id: int, jid: str, nick: str,
                                 message: str, seconds: int, original_msg,
                                 overdue_str: str = None,
                                 room_jid: str = None,
                                 msg_mto: str = None,
                                 msg_type: str = None):
    """
    Background task that waits and sends the reminder.

    Works both for new reminders and restored reminders after bot restart.

    Args:
        reminder_id: ID of the reminder
        jid: User JID
        nick: User nickname
        message: Reminder message
        seconds: Seconds to wait before sending
        original_msg: Original message object (None if restored after restart)
        overdue_str: String indicating how long ago the reminder should have fired
        room_jid: Room JID if reminder was created in a chat (None for DM)
    """
    try:
        await asyncio.sleep(seconds)

        # Build reminder text
        # Only include nick in group chats, not in DMs
        if room_jid:
            # Group chat: include nick
            if overdue_str:
                reminder_text = f"{nick}: 🔔 Reminder (was due {overdue_str}): {message}"
            else:
                reminder_text = f"{nick}: 🔔 Reminder: {message}"
        else:
            # Direct message: no nick needed (already shows sender)
            if overdue_str:
                reminder_text = f"🔔 Reminder (was due {overdue_str}): {message}"
            else:
                reminder_text = f"🔔 Reminder: {message}"

        # Send the actual reminder
        if original_msg is not None:
            # Send to original message (group chat with threading)
            bot.reply(original_msg, reminder_text, ephemeral=False, mention=False)
            log.info(f"[REMINDER] ✅ Reminder {reminder_id} sent to {jid}")
        else:
            # After bot restart: Send via direct message or to room
            try:
                msg = bot.make_message(
                    mto=msg_mto or (room_jid if room_jid else jid),
                    mbody=reminder_text,
                    mtype=msg_type or ("groupchat" if room_jid else "chat")
                )
                msg.send()
                log.info(f"[REMINDER] ✅ Reminder {reminder_id} sent")

            except Exception as e:
                log.exception(f"[REMINDER] 🔴 Failed to send reminder {reminder_id}: {e}")

        # Delete immediately after sending
        await bot.db.reminders.delete(reminder_id)
        log.info(f"[REMINDER] 🗑️ Reminder {reminder_id} deleted after sending")

    except asyncio.CancelledError:
        log.debug(f"[REMINDER] ⚠️ Reminder {reminder_id} was cancelled")
        pass
    except Exception as e:
        log.exception(f"[REMINDER] 🔴 Error in reminder task {reminder_id}: {e}")
    finally:
        # Clean up from active reminders
        ACTIVE_REMINDERS.pop(reminder_id, None)


# ============================================================================
# COMMANDS
# ============================================================================

@command("remind", role=Role.USER, aliases=["rem"])
async def remind_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Set a new reminder.

    Usage: {prefix}remind <duration> <message>

    Examples:
        {prefix}remind 30m Take a break
        {prefix}remind 1h Important meeting
        {prefix}remind 2d Review project

    Supported durations: 10s, 5m, 1h, 2d, ...
    Maximum: 365 days per reminder
    """
    if len(args) < 2:
        prefix = config.get('prefix', ',')
        bot.reply(
            msg,
            f"🟡️ Usage: {prefix}remind <duration> <message>\n"
            f"Example: {prefix}remind 30m Take a break\n"
            f"Formats: 10s, 5m, 1h, 2d, ... (max 365 days)"
        )
        return

    duration_str = args[0]
    message = " ".join(args[1:])

    # Parse duration
    seconds = parse_duration(duration_str)
    if seconds is None or seconds < 1:
        bot.reply(msg, "🟡️ Invalid duration. Use format: 10s, 5m, 1h, 2d")
        return

    # Get max seconds from config
    max_seconds = config.get("reminder_max_age_days", 365) * 24 * 3600
    # Enforce maximum
    if seconds > max_seconds:
        max_days = config.get("reminder_max_age_days", 365)
        bot.reply(msg, f"🟡️ Duration too long (max {max_days} days)")
        return

    # Trim message length
    if len(message) > 500:
        bot.reply(msg, "🟡️ Message too long (max 500 characters)")
        return

    try:
        # Extract nick from sender_jid for fallback
        display_nick = nick if nick else (sender_jid.split('/')[-1] if '/' in sender_jid else sender_jid.split('@')[0])

        # Save room_jid if reminder was created in a chat
        room_jid = msg['from'].bare if is_room else None

        # Store in database
        reminder_id = await bot.db.reminders.create(
            user_jid=str(sender_jid),
            message=message,
            scheduled_at=datetime.datetime.now(datetime.timezone.utc),
            remind_at=datetime.datetime.now(datetime.timezone.utc) +
                      datetime.timedelta(seconds=seconds),
            room_jid=room_jid
        )

        # Create and schedule the background task
        task = asyncio.create_task(
            schedule_reminder_task(
                bot,
                reminder_id,
                sender_jid,
                display_nick,
                message,
                seconds,
                msg,
                room_jid=room_jid,
                msg_mto=room_jid if is_room else sender_jid,
                msg_type="groupchat" if is_room else "chat"
            )
        )

        # Track the task
        ACTIVE_REMINDERS[reminder_id] = task

        bot.reply(msg, f"✅ Reminder set! I'll remind you in {duration_str}")
        log.info(f"[REMINDER] Created reminder {reminder_id} for {sender_jid}: {message}")

    except Exception as e:
        log.exception(f"[REMINDER] 🔴 Error creating reminder: {e}")
        bot.reply(msg, "🔴 Error creating reminder. Please try again.")


@command("reminders", role=Role.USER, aliases=["rems", "remind list"])
async def list_reminders(bot, sender_jid, nick, args, msg, is_room):
    """
    List all your pending reminders.

    Usage: {prefix}reminders

    Shows ID, message, and time until reminder fires.
    """
    try:
        reminders = await bot.db.reminders.get_pending(str(sender_jid))

        if not reminders:
            bot.reply(msg, "No pending reminders 📭")
            return

        lines = ["📋 Your pending reminders:"]
        for reminder in reminders:
            remind_at = reminder['remind_at']

            # Handle both string and datetime
            if isinstance(remind_at, str):
                remind_at = datetime.datetime.fromisoformat(remind_at)

            time_left = remind_at - datetime.datetime.now(datetime.timezone.utc)
            total_seconds = time_left.total_seconds()

            # Use format_seconds function
            time_str = format_seconds(total_seconds)

            lines.append(
                f"  • ID {reminder['id']}: {reminder['message']} (in {time_str})"
            )

        bot.reply(msg, lines)

    except Exception as e:
        log.exception(f"[REMINDER] 🔴 Error listing reminders: {e}")
        bot.reply(msg, "🔴 Error retrieving reminders.")


@command("remind delete", role=Role.USER, aliases=["remind rm", "remind cancel"])
async def delete_reminder(bot, sender_jid, nick, args, msg, is_room):
    """
    Delete or cancel a reminder by its ID.

    Usage: {prefix}remind delete <id>

    Example: {prefix}remind delete 1

    You can only delete your own reminders.
    """
    if not args:
        prefix = config.get('prefix', ',')
        bot.reply(msg, f"🟡️ Usage: {prefix}remind delete <id>")
        return

    try:
        reminder_id = int(args[0])
    except ValueError:
        bot.reply(msg, "🟡️ ID must be a number")
        return

    try:
        # Get reminder first to check ownership
        reminder = await bot.db.reminders.get(reminder_id)

        if not reminder:
            bot.reply(msg, "🟡️ Reminder not found")
            return

        if reminder['user_jid'] != str(sender_jid):
            bot.reply(msg, "🔴 You can only delete your own reminders")
            return

        # Delete from database
        await bot.db.reminders.delete(reminder_id)

        # Cancel the running task if it exists
        if reminder_id in ACTIVE_REMINDERS:
            task = ACTIVE_REMINDERS[reminder_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            ACTIVE_REMINDERS.pop(reminder_id, None)

        bot.reply(msg, f"✅ Reminder {reminder_id} deleted")
        log.info(f"[REMINDER] Deleted reminder {reminder_id}")

    except Exception as e:
        log.exception(f"[REMINDER] 🔴 Error deleting reminder: {e}")
        bot.reply(msg, "🔴 Error deleting reminder.")


# ============================================================================
# PLUGIN LIFECYCLE
# ============================================================================

async def on_ready(bot):
    """
    Called when the bot is fully initialized and database is ready.

    Restores all pending reminders from the database and reschedules them.
    This ensures reminders survive bot restarts.
    """
    try:
        log.info("[REMINDER] 🔄 Loading pending reminders from database...")

        # Get all pending reminders
        pending = await bot.db.reminders.get_all_pending()

        if not pending:
            log.info("[REMINDER] ✅ No pending reminders to restore")
            return

        restored = 0
        now = datetime.datetime.now(datetime.timezone.utc)

        for reminder in pending:
            reminder_id = reminder['id']
            user_jid = reminder['user_jid']
            room_jid = reminder['room_jid']
            message = reminder['message']
            remind_at = reminder['remind_at']

            # Handle both string and datetime
            if isinstance(remind_at, str):
                remind_at = datetime.datetime.fromisoformat(remind_at)

            # Calculate time remaining
            time_left = remind_at - now
            seconds_left = time_left.total_seconds()

            overdue_str = None

            # Guarantee that seconds_left is always at least 0.1 seconds
            # This ensures EVERY reminder is sent, even if overdue!
            if seconds_left < 0.1:
                # Calculate how long it has been overdue
                overdue_seconds = abs(seconds_left)

                if overdue_seconds < 60:
                    overdue_str = f"{int(overdue_seconds)}s ago"
                elif overdue_seconds < 3600:
                    overdue_str = f"{int(overdue_seconds / 60)}m ago"
                elif overdue_seconds < 86400:
                    overdue_str = f"{overdue_seconds / 3600:.1f}h ago"
                else:
                    overdue_str = f"{overdue_seconds / 86400:.1f}d ago"

                log.info(f"[REMINDER] ⏰ Reminder {reminder_id} is overdue ({overdue_str}), sending now")
                seconds_left = 0.1

            # Schedule the reminder
            try:
                # Extract nick from user_jid (format: user@domain/nick or user@domain)
                nick = user_jid.split('/')[-1] if '/' in user_jid else user_jid.split('@')[0]

                task = asyncio.create_task(
                    schedule_reminder_task(
                        bot,
                        reminder_id,
                        user_jid,
                        nick,
                        message,
                        seconds_left,
                        None,
                        overdue_str,
                        room_jid,
                        msg_mto=room_jid if room_jid else user_jid,
                        msg_type="groupchat" if room_jid else "chat"
                    )
                )

                ACTIVE_REMINDERS[reminder_id] = task
                restored += 1

                hours = seconds_left / 3600
                log.info(f"[REMINDER] ✅ Restored reminder {reminder_id}: {message} "
                        f"({hours:.1f}h remaining)")

            except Exception as e:
                log.exception(f"[REMINDER] 🔴 Error restoring reminder {reminder_id}: {e}")

        if restored > 0:
            log.info(f"[REMINDER] ✅ Successfully restored {restored} pending reminders")

    except Exception as e:
        log.exception(f"[REMINDER] 🔴 Error during reminder restoration: {e}")


async def on_unload(bot):
    """
    Called when the plugin is unloaded.

    Cancels all active reminder tasks.
    """
    try:
        log.info("[REMINDER] 🛑 Unloading reminder plugin...")

        # Cancel all active tasks
        for reminder_id, task in list(ACTIVE_REMINDERS.items()):
            try:
                task.cancel()
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.exception(f"[REMINDER] Error cancelling reminder {reminder_id}: {e}")

        ACTIVE_REMINDERS.clear()
        log.info("[REMINDER] ✅ Plugin unloaded")

    except Exception as e:
        log.exception(f"[REMINDER] 🔴 Error during plugin unload: {e}")
