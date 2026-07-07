"""Split module for plugins/reminder.py: tasks."""

import asyncio
from utils.task_supervisor import create_plugin_task


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

    ACTIVE_REMINDERS[reminder_id] = task
    return task


async def _cancel_all_active_tasks() -> int:
    """Cancel all active in-memory reminder tasks and return the count."""
    cancelled = 0

    for reminder_id, task in list(ACTIVE_REMINDERS.items()):
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

    ACTIVE_REMINDERS.clear()
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
        task = ACTIVE_REMINDERS.pop(reminder_id, None)

        if task and not task.done():
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


async def on_unload(bot):
    """Cancel all active reminder tasks."""
    try:
        log.info("[REMINDER] Unloading reminder plugin...")

        cancelled = await _cancel_all_active_tasks()
        log.info("[REMINDER] ✅ Plugin unloaded; cancelled %s task(s)",
                 cancelled)

    except Exception as exc:
        log.exception("[REMINDER] Error during plugin unload: %s", exc)


async def cleanup_room_state(bot, room_jid: str) -> dict[str, int]:
    """Cancel and delete pending reminders for a deleted room."""
    target = str(room_jid or "").split("/", 1)[0].strip().lower()
    await _init_reminder_db(bot)
    pending = await _get_all_pending_reminders(bot)
    room_ids = [
        int(reminder["id"])
        for reminder in pending
        if str(reminder.get("room_jid") or "").split("/", 1)[0].strip().lower() == target
    ]

    cancelled = await _cancel_active_tasks_for_room(bot, room_jid)
    for reminder_id in room_ids:
        await _delete_reminder(bot, reminder_id)

    return {"reminders": len(room_ids), "tasks": cancelled}
