"""Reminder persistence and database queries."""

from __future__ import annotations

import datetime

from utils.room_features import get_room_feature

from . import runtime

log = runtime.log


async def get_reminder_store(bot):
    """Return the plugin runtime store used for room-scoped settings."""
    return bot.db.users.plugin("reminder")


async def _get_room_reminder_state(bot, room_jid: str) -> bool:
    """Return the effective reminder state for a room."""
    try:
        return (await get_room_feature(bot, room_jid, "reminder")).enabled
    except Exception as exc:
        log.exception(
            "[REMINDER] Error reading room control state for %s: %s",
            room_jid,
            exc,
        )
        return False


async def _init_reminder_db(bot):
    """Create the reminders table and indexes if they do not exist.

    Keeping this inside the plugin makes reminder.py self-contained while all
    writes still pass through DatabaseManager's nested-safe transaction API.
    """
    if runtime.REMINDER_DB_READY:
        return

    async with bot.db.transaction(label="reminder_init") as conn:
        await conn.execute("""
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
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reminders_user_jid
            ON reminders(user_jid)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reminders_remind_at
            ON reminders(remind_at)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reminders_is_active
            ON reminders(is_active)
        """)

    runtime.REMINDER_DB_READY = True
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

    cursor = await bot.db.write(
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

    await bot.db.write(
        "DELETE FROM reminders WHERE id = ?",
        (reminder_id,),
    )
async def _get_reminder(bot, reminder_id: int) -> dict | None:
    """Return one reminder by ID, or None if it does not exist."""
    await _init_reminder_db(bot)

    row = await bot.db.fetch_one(
        "SELECT * FROM reminders WHERE id = ?",
        (reminder_id,),
    )

    return dict(row) if row is not None else None
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
