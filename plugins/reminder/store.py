"""Split module for plugins/reminder.py: store."""

import asyncio
import datetime
import logging
from utils.command import command, Role
from utils.config import config
from core_plugins._core import handle_room_toggle_command, get_user_tzinfo


log = logging.getLogger(__name__)


PLUGIN_META = {
    "name": "reminder",
    "version": "0.2.2",
    "description": "Schedule and manage reminders",
    "category": "utility",
    "requires": ["_core", "rooms"],
}


ACTIVE_REMINDERS: dict[int, asyncio.Task] = {}


REMINDER_ENABLED: bool = bool(config.get("reminder_enabled", True))


REMINDER_KEY = "REMINDER"


REMINDER_DB_READY = False


async def get_reminder_store(bot):
    """Return the plugin runtime store used for room-scoped settings."""
    return bot.db.users.plugin("reminder")


async def _get_room_reminder_state(bot, room_jid: str) -> bool:
    """Return whether reminders are enabled for a room.

    This intentionally matches core_plugins/rooms.py dict semantics:
    {room_jid: True} means enabled. Missing keys are disabled, even if the
    configured default is on, because rooms.py writes defaults explicitly.
    """
    try:
        store = await get_reminder_store(bot)
        state = await store.get_global(REMINDER_KEY, default={})
    except Exception as exc:
        log.exception(
            "[REMINDER] Error reading room control state for %s: %s",
            room_jid,
            exc,
        )
        return False

    if not isinstance(state, dict):
        return False

    return bool(state.get(room_jid))


async def _handle_reminder_control_command(bot, args,
                                           msg, is_room: bool) -> bool:
    """Handle reminder on/off/status.

    Room contexts are delegated to
    utils.plugin_helper.handle_room_toggle_command.  Normal DMs control
    the global runtime kill-switch.
    """
    global REMINDER_ENABLED

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
            storage="dict",
            log_prefix="[REMINDER]",
        )

        if handled:
            after = await _get_room_reminder_state(bot, room_jid)

            if subcmd == "on" and not before and after and REMINDER_ENABLED:
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
        global_state = "on" if REMINDER_ENABLED else "off"
        active_count = sum(
            1 for task in ACTIVE_REMINDERS.values() if not task.done())
        bot.reply(
            msg,
            f"ℹ️ Reminder plugin global: {global_state}. "
            f"Active scheduled reminders: {active_count}.",
        )
        return True

    if subcmd == "on":
        if REMINDER_ENABLED:
            bot.reply(msg, "ℹ️ Reminder plugin is already globally on.")
            return True

        REMINDER_ENABLED = True
        restored = await _restore_pending_reminders(bot)
        bot.reply(
            msg,
            f"▶️ Reminder plugin enabled globally. "
            f"Restored {restored} pending reminder task(s).",
        )
        log.info("[REMINDER] Plugin enabled globally; restored %s reminders",
                 restored)
        return True

    if not REMINDER_ENABLED:
        bot.reply(msg, "ℹ️ Reminder plugin is already globally off.")
        return True

    REMINDER_ENABLED = False
    cancelled = await _cancel_all_active_tasks()
    bot.reply(
        msg,
        f"⏸️ Reminder plugin disabled globally. Pending reminders stay saved. "
        f"Cancelled {cancelled} active task(s).",
    )
    log.info("[REMINDER] Plugin disabled globally; cancelled %s tasks",
             cancelled)
    return True


async def _init_reminder_db(bot):
    """Create the reminders table and indexes if they do not exist.

    Keeping this inside the plugin makes reminder.py self-contained: the core
    database manager only has to provide execute()/fetch_all().
    """
    global REMINDER_DB_READY

    if REMINDER_DB_READY:
        return

    await bot.db.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY,
            user_jid TEXT NOT NULL,
            room_jid TEXT,
            message TEXT NOT NULL,
            scheduled_at TIMESTAMP NOT NULL,
            remind_at TIMESTAMP NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await bot.db.execute("""
        CREATE INDEX IF NOT EXISTS idx_reminders_user_jid
        ON reminders(user_jid)
    """)

    await bot.db.execute("""
        CREATE INDEX IF NOT EXISTS idx_reminders_remind_at
        ON reminders(remind_at)
    """)

    await bot.db.execute("""
        CREATE INDEX IF NOT EXISTS idx_reminders_is_active
        ON reminders(is_active)
    """)

    REMINDER_DB_READY = True
    log.info("[REMINDER] ✅ Initialized reminders table")


async def _create_reminder(
    bot,
    user_jid: str,
    message: str,
    scheduled_at: datetime.datetime,
    remind_at: datetime.datetime,
    room_jid: str | None = None,
) -> int:
    """Insert a reminder and return its ID."""
    await _init_reminder_db(bot)

    cursor = await bot.db.execute(
        """
        INSERT INTO reminders
        (user_jid, room_jid, message, scheduled_at, remind_at, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (
            user_jid,
            room_jid,
            message,
            scheduled_at.isoformat(),
            remind_at.isoformat(),
        ),
    )

    return cursor.lastrowid


async def _delete_reminder(bot, reminder_id: int):
    """Delete one reminder by ID."""
    await _init_reminder_db(bot)

    await bot.db.execute(
        "DELETE FROM reminders WHERE id = ?",
        (reminder_id,),
    )


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

        if not REMINDER_ENABLED:
            log.info(
                "[REMINDER] Reminder %s due while plugin disabled; keeping"
                " pending",
                reminder_id,
            )
            return

        if room_jid and not await _get_room_reminder_state(bot, room_jid):
            log.info(
                "[REMINDER] Reminder %s due while room %s disabled; keeping"
                " pending",
                reminder_id,
                room_jid,
            )
            return

        if room_jid:
            if overdue_str:
                reminder_text = (f"🔔 {nick}: Reminder"
                                 f" (was due {overdue_str}): {message}")
            else:
                reminder_text = f"🔔 {nick}: Reminder: {message}"
        else:
            if overdue_str:
                reminder_text = f"🔔 Reminder (was due {overdue_str}): {
                    message}"
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

        await _delete_reminder(bot, reminder_id)
        log.info("[REMINDER] ✅ Reminder %s deleted after sending", reminder_id)

    except asyncio.CancelledError:
        log.debug("[REMINDER] ⚠️ Reminder %s was cancelled", reminder_id)
        raise

    except Exception as exc:
        log.exception(
            "[REMINDER] Error in reminder task %s: %s", reminder_id, exc)

    finally:
        ACTIVE_REMINDERS.pop(reminder_id, None)


async def _restore_pending_reminders(bot) -> int:
    """Restore pending reminders from the database.

    Returns the number of reminders scheduled in memory.
    """
    pending = await _get_all_pending_reminders(bot)

    if not pending:
        log.info("[REMINDER] ✅ No pending reminders to restore")
        return 0

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
            log.debug("[REMINDER] Reminder %s already scheduled; skipping",
                      reminder_id)
            continue

        if room_jid and not await _get_room_reminder_state(bot, room_jid):
            log.debug(
                "[REMINDER] Reminder %s belongs to disabled room %s;"
                " skipping restore",
                reminder_id,
                room_jid,
            )
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
        # - otherwise normal DM or MUC-PM -> send chat to stored user_jid
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
                "[REMINDER] ✅ Restored reminder %s (%.1f h remaining)",
                reminder_id,
                hours,
            )

        except Exception as exc:
            log.exception(
                "[REMINDER] Error restoring reminder %s: %s",
                reminder_id,
                exc,
            )

    if restored > 0:
        log.info("[REMINDER] ✅ Successfully restored %s pending reminders",
                 restored)

    return restored


@command(
    "remind",
    role=Role.USER,
    aliases=["rem", "reminder"],
    short="Create a reminder.",
    usage="{prefix}remind <on|off|status|when> [text]",
    examples=[
        "{prefix}remind status",
        "{prefix}remind 10m check logs",
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

    if not REMINDER_ENABLED:
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

    if len(args) < 2:
        bot.reply(
            msg,
            f"ℹ️ Usage: {prefix}remind <duration|date time> <message>\n"
            f"Example: {prefix}remind 30m Take a break\n"
            f"Example: {prefix}remind 2026-05-01 14:30 Take a break\n"
            f"Example: {prefix}remind 01.05.2026 14:30 Take a break\n"
            "Formats: 10s, 5m, 1h, 2d, 1h30m, "
            "YYYY-MM-DD HH:MM, DD.MM.YYYY HH:MM "
            f"(max {config.get('reminder_max_age_days', 365)} days)",
        )
        return

    try:
        ctx = _reminder_context(bot, sender_jid, nick, msg, is_room)
        user_tz = await get_user_tzinfo(bot, ctx.get("timezone_jid"))

        seconds, message, display_when = parse_reminder_when(args, user_tz)

        if seconds is None or seconds < 1 or not message:
            bot.reply(
                msg,
                "❌ Invalid reminder time.\n"
                "Use relative format: 10s, 5m, 1h, 2d, 1h30m\n"
                "Or absolute format: 2026-05-01 14:30, 01.05.2026 14:30",
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

        task = ACTIVE_REMINDERS.pop(reminder_id, None)
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


async def on_ready(bot):
    """
    Initialize the reminder table and restore pending reminders after
    startup/reload.
    """
    try:
        await _init_reminder_db(bot)

        if not REMINDER_ENABLED:
            log.info(
                "[REMINDER] Plugin is disabled; pending reminders will"
                " not be restored")
            return

        log.info("[REMINDER] Loading pending reminders from database...")
        await _restore_pending_reminders(bot)

    except Exception as exc:
        log.exception("[REMINDER] Error during reminder restoration: %s", exc)


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int]:
    """Return small reminder counters for diagnostics."""
    await _init_reminder_db(bot)
    pending = await _get_all_pending_reminders(bot)
    if room_jid:
        target = str(room_jid or "").split("/", 1)[0].strip().lower()
        room_pending = [
            reminder for reminder in pending
            if str(reminder.get("room_jid") or "")
            .split("/", 1)[0]
            .strip()
            .lower() == target
        ]
        room_ids = {int(reminder["id"]) for reminder in room_pending}
        return {
            "pending_reminders": len(room_pending),
            "active_tasks": sum(
                1 for reminder_id, task in ACTIVE_REMINDERS.items()
                if reminder_id in room_ids and not task.done()
            ),
        }
    return {
        "pending_reminders": len(pending),
        "active_tasks": sum(1 for task in ACTIVE_REMINDERS.values() if not task.done()),
        "enabled": int(REMINDER_ENABLED),
    }

async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return reminder health diagnostics."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    enabled = state.get("enabled", 1)
    pending = int(state.get("pending_reminders", 0) or 0)
    active = int(state.get("active_tasks", 0) or 0)
    icon = "✅" if int(enabled or 0) else "ℹ️"
    status = "enabled" if int(enabled or 0) else "disabled"
    return [f"{icon} Reminder{scope}: {status}, pending={pending}, active_tasks={active}"]

__all__ = [
    'log',
    'PLUGIN_META',
    'ACTIVE_REMINDERS',
    'REMINDER_ENABLED',
    'REMINDER_KEY',
    'REMINDER_DB_READY',
    'get_reminder_store',
    '_get_room_reminder_state',
    '_handle_reminder_control_command',
    '_init_reminder_db',
    '_create_reminder',
    '_delete_reminder',
    'schedule_reminder_task',
    '_restore_pending_reminders',
    'remind_command',
    'delete_reminder',
    'on_ready',
    'get_runtime_state',
    'doctor',
]
