"""
Reminders database manager.

Handles all database operations for the reminder plugin,
including creating, retrieving, updating, and deleting reminders.
"""

import logging
import datetime
from utils.config import config

log = logging.getLogger(__name__)

# Maximum reminder duration (from config, default 365 days)
MAX_REMINDER_DAYS = config.get("reminder_max_age_days", 365)
MAX_REMINDER_SECONDS = MAX_REMINDER_DAYS * 24 * 3600

class RemindersManager:
    """
    Manages the reminders table and provides an async interface
    for reminder operations.
    """

    def __init__(self, db_manager):
        """Initialize with database manager (not connection)."""
        self.db = db_manager
        # Update max seconds from config on init
        global MAX_REMINDER_SECONDS
        MAX_REMINDER_DAYS = config.get("reminder_max_age_days", 365)
        MAX_REMINDER_SECONDS = MAX_REMINDER_DAYS * 24 * 3600

    async def init(self):
        """Create the reminders table if it doesn't exist."""
        await self.db.execute("""
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

        # Create index on user_jid for faster queries
        await self.db.execute("""
        CREATE INDEX IF NOT EXISTS idx_reminders_user_jid
        ON reminders(user_jid)
        """)

        # Create index on remind_at for sorting
        await self.db.execute("""
        CREATE INDEX IF NOT EXISTS idx_reminders_remind_at
        ON reminders(remind_at)
        """)

        # Create index on is_active for pending reminders query
        await self.db.execute("""
        CREATE INDEX IF NOT EXISTS idx_reminders_is_active
        ON reminders(is_active)
        """)

        log.info("[REMINDERS DB] ✅ Initialized reminders table")

    async def create(self, user_jid: str, message: str,
                     scheduled_at: datetime.datetime,
                     remind_at: datetime.datetime,
                     room_jid: str = None) -> int:
        """
        Create a new reminder.

        Args:
            user_jid: JID of the user creating the reminder
            message: Reminder message
            scheduled_at: When the reminder was created (UTC)
            remind_at: When the reminder should fire (UTC)
            room_jid: Optional - JID of the room where reminder was created

        Returns:
            ID of the created reminder
        """
        cursor = await self.db.execute("""
        INSERT INTO reminders
        (user_jid, room_jid, message, scheduled_at, remind_at, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
        """, (
            user_jid,
            room_jid,
            message,
            scheduled_at.isoformat(),
            remind_at.isoformat()
        ))

        log.info(f"[REMINDERS DB] Created reminder for {user_jid}")
        return cursor.lastrowid

    async def get(self, reminder_id: int):
        """Get a single reminder by ID."""
        rows = await self.db.fetch_all("""
        SELECT * FROM reminders WHERE id = ?
        """, (reminder_id,))

        if not rows:
            return None

        return dict(rows[0])

    async def get_pending(self, user_jid: str) -> list:
        """
        Get all pending reminders for a user.

        Returns reminders ordered by remind_at ascending.
        """
        rows = await self.db.fetch_all("""
        SELECT * FROM reminders
        WHERE user_jid = ? AND is_active = 1
        ORDER BY remind_at ASC
        """, (user_jid,))

        return [dict(row) for row in rows]

    async def get_all_pending(self) -> list:
        """Get ALL pending reminders across all users."""
        rows = await self.db.fetch_all("""
        SELECT * FROM reminders
        WHERE is_active = 1
        ORDER BY remind_at ASC
        """)

        return [dict(row) for row in rows] if rows else []

    async def delete(self, reminder_id: int):
        """
        Delete a reminder by ID.

        Permanently removes the reminder from the database.
        """
        await self.db.execute("""
        DELETE FROM reminders WHERE id = ?
        """, (reminder_id,))

        log.debug(f"[REMINDERS DB] Deleted reminder {reminder_id}")

    async def delete_by_user(self, user_jid: str):
        """Delete all reminders for a specific user."""
        await self.db.execute("""
        DELETE FROM reminders WHERE user_jid = ?
        """, (user_jid,))

        log.debug(f"[REMINDERS DB] Deleted all reminders for {user_jid}")
