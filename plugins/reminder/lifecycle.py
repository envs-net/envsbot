"""Reminder plugin lifecycle and diagnostics."""

from __future__ import annotations

from functools import partial

from . import runtime
from .events import _on_groupchat_message, _on_private_message
from .store import (
    _delete_reminder,
    _get_all_pending_reminders,
    _init_reminder_db,
)
from .tasks import (
    _cancel_active_tasks_for_room,
    _cancel_all_active_tasks,
    _restore_pending_reminders,
)

log = runtime.log


async def on_ready(bot):
    """
    Initialize the reminder table and restore pending reminders after
    startup/reload.
    """
    try:
        await _init_reminder_db(bot)

        if not runtime.REMINDER_ENABLED:
            log.info(
                "[REMINDER] Plugin is disabled; pending reminders will"
                " not be restored")
            return

        log.info("[REMINDER] Loading pending reminders from database...")
        await _restore_pending_reminders(bot)

    except Exception as exc:
        log.exception("[REMINDER] Error during reminder restoration: %s", exc)
        raise
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
                1 for reminder_id, task in runtime.ACTIVE_REMINDERS.items()
                if reminder_id in room_ids and not task.done()
            ),
        }
    return {
        "pending_reminders": len(pending),
        "active_tasks": sum(1 for task in runtime.ACTIVE_REMINDERS.values() if not task.done()),
        "enabled": int(runtime.REMINDER_ENABLED),
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
