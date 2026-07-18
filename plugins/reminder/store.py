"""Split module for plugins/reminder.py: store."""

import asyncio
import datetime
import logging
from functools import partial

from utils.command import command, Role
from utils.config import config
from utils import message_cache
from core_plugins._core import (
    JOINED_ROOMS,
    extract_reply_quote,
    get_reply_target,
    get_stanza_id,
    handle_room_toggle_command,
    remember_stanza,
)
from .parsing import explain_invalid_reminder_time, get_reminder_tzinfo


log = logging.getLogger(__name__)


PLUGIN_META = {
    "name": "reminder",
    "version": "0.2.3",
    "description": "Schedule and manage reminders",
    "category": "utility",
    "requires": ["_core", "rooms"],
}


ACTIVE_REMINDERS: dict[int, asyncio.Task] = {}


REMINDER_ENABLED: bool = bool(config.get("reminder_enabled", True))


REMINDER_KEY = "REMINDER"


REMINDER_DB_READY = False


REMINDER_REPLY_FALLBACK_NAMESPACE = "reminder-reply-fallback"


def _body_without_reply_quote(body: str) -> str:
    """Remove a leading XEP-0461 plain-text fallback quote."""
    lines = str(body or "").splitlines()
    index = 0

    while index < len(lines) and lines[index].startswith(">"):
        index += 1

    while index < len(lines) and not lines[index].strip():
        index += 1

    return "\n".join(lines[index:]).strip()


def _is_remind_command_body(body: str) -> bool:
    """Return whether a body contains a reminder command or alias."""
    prefix = str(config.get("prefix", ",") or ",")
    stripped = str(body or "").strip().lower()
    commands = ("remind", "rem", "reminder")
    return any(
        stripped == f"{prefix}{name}"
        or stripped.startswith(f"{prefix}{name} ")
        for name in commands
    )


def _is_own_room_message(bot, msg) -> bool:
    """Return True when a room stanza was sent by the bot itself."""
    try:
        room = str(msg["from"].bare)
        sender_nick = str(msg.get("mucnick") or msg["from"].resource or "")
        joined_rooms = getattr(
            getattr(bot, "presence", None),
            "joined_rooms",
            {},
        )
        bot_nick = str(
            joined_rooms.get(room) or getattr(bot, "nick", "") or ""
        )
        return bool(sender_nick and bot_nick and sender_nick == bot_nick)
    except Exception:
        return False


def _reply_message_text(bot, msg, is_room: bool) -> str | None:
    """Resolve the replied-to message from the shared cache or fallback quote."""
    reply_id = get_reply_target(msg)
    if reply_id:
        conversation = message_cache.conversation_key(
            msg,
            is_room=is_room,
            joined_rooms=JOINED_ROOMS,
        )
        cache = getattr(bot, "message_cache", None)
        get_by_id = getattr(cache, "get_by_id", None)
        if conversation and callable(get_by_id):
            cached = get_by_id(conversation, reply_id)
            if cached:
                text = str(cached.get("body") or "").strip()
                if text:
                    return text

    return extract_reply_quote(str(msg.get("body", "") or ""))


async def _redispatch_reply_fallback(bot, msg, *, is_room: bool) -> None:
    """Redispatch a quoted XEP-0461 reminder command through normal routing."""
    try:
        msg_type = str(msg.get("type") or "")
        if is_room:
            if msg_type != "groupchat" or _is_own_room_message(bot, msg):
                return
        elif msg_type not in {"chat", "normal"}:
            return

        body = str(msg.get("body", "") or "").strip()
        if not body or not extract_reply_quote(body):
            return

        command_body = _body_without_reply_quote(body)
        if not _is_remind_command_body(command_body):
            return

        stanza_id = get_stanza_id(msg)
        if not remember_stanza(REMINDER_REPLY_FALLBACK_NAMESPACE, stanza_id):
            return

        nick = None
        if is_room:
            nick = msg.get("mucnick") or getattr(msg["from"], "resource", None)
        await bot.handle_command(
            command_body,
            msg["from"],
            nick,
            msg,
            is_room,
        )
    except Exception:
        log.exception("[REMINDER] Error handling reply fallback command")


async def _on_groupchat_message(bot, msg) -> None:
    await _redispatch_reply_fallback(bot, msg, is_room=True)


async def _on_private_message(bot, msg) -> None:
    await _redispatch_reply_fallback(bot, msg, is_room=False)


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


async def on_load(bot):
    """Register XEP-0461 fallback handlers for room and private replies."""
    bot.bot_plugins.register_event(
        "reminder",
        "groupchat_message",
        partial(_on_groupchat_message, bot),
    )
    bot.bot_plugins.register_event(
        "reminder",
        "message",
        partial(_on_private_message, bot),
    )


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
