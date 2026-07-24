"""Reminder scheduling, delivery, restoration, and cancellation."""

from __future__ import annotations

import asyncio

from utils.task_supervisor import create_plugin_task

from . import runtime
from .formatting import _display_nick, _send_reminder_message
from .parsing import _format_overdue, _parse_datetime, _utcnow
from .store import (
    _delete_reminder,
    _get_all_pending_reminders,
    _get_room_reminder_state,
)

log = runtime.log


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
    old_task = runtime.ACTIVE_REMINDERS.get(reminder_id)

    if old_task and not old_task.done():
        old_task.cancel()

    task = create_plugin_task(bot,
        "reminder",
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
        ),
        name=f"reminder-{reminder_id}",
    )

    runtime.ACTIVE_REMINDERS[reminder_id] = task
    return task
async def _cancel_all_active_tasks() -> int:
    """Cancel all active in-memory reminder tasks and return the count."""
    cancelled = 0

    for reminder_id, task in list(runtime.ACTIVE_REMINDERS.items()):
        if task and not task.done():
            task.cancel()
            cancelled += 1

        try:
            await task
        except asyncio.CancelledError:
            log.debug("[REMINDER] Reminder task %s cancelled", reminder_id)
        except Exception as exc:
            log.exception(
                "[REMINDER] Error cancelling reminder %s: %s",
                reminder_id,
                exc,
            )

    runtime.ACTIVE_REMINDERS.clear()
    return cancelled
async def _cancel_active_tasks_for_room(bot, room_jid: str) -> int:
    """Cancel active in-memory reminder tasks belonging to one room."""
    pending = await _get_all_pending_reminders(bot)
    room_reminder_ids = {
        int(reminder["id"])
        for reminder in pending
        if reminder.get("room_jid") == room_jid
    }

    cancelled = 0

    for reminder_id in room_reminder_ids:
        task = runtime.ACTIVE_REMINDERS.pop(reminder_id, None)

        if task is None:
            continue

        if not task.done():
            task.cancel()
            cancelled += 1

        try:
            await task
        except asyncio.CancelledError:
            log.debug("[REMINDER] Room reminder task %s cancelled", reminder_id)
        except Exception as exc:
            log.exception(
                "[REMINDER] Error cancelling room reminder %s: %s",
                reminder_id,
                exc,
            )

    return cancelled
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

        if not runtime.REMINDER_ENABLED:
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
                reminder_text = (
                    f"🔔 Reminder (was due {overdue_str}): {message}"
                )
            else:
                reminder_text = f"🔔 Reminder: {message}"

        try:
            target = msg_mto or (room_jid if room_jid else user_jid)
            message_type = msg_type or ("groupchat" if room_jid else "chat")

            sent = await _send_reminder_message(
                bot,
                mto=target,
                mbody=reminder_text,
                mtype=message_type,
            )

            if not sent:
                log.error(
                    "[REMINDER] Reminder %s was not accepted for sending;"
                    " keeping pending",
                    reminder_id,
                )
                return

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
        runtime.ACTIVE_REMINDERS.pop(reminder_id, None)
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

        existing_task = runtime.ACTIVE_REMINDERS.get(reminder_id)
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
