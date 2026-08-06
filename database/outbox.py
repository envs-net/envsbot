"""Persistent outbound message queue for reliable XMPP delivery."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OutboxMessage:
    """One queued outbound stanza."""

    id: int
    destination: str
    body: str
    message_type: str
    category: str
    dedupe_key: str | None
    attempts: int
    max_attempts: int
    created_at: int
    available_at: int
    last_error: str | None


class OutboxStore:
    """SQLite persistence for pending and failed outbound messages."""

    def __init__(self, db):
        self.db = db

    async def init(self) -> None:
        await self.db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outbox_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                destination TEXT NOT NULL,
                body TEXT NOT NULL,
                message_type TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'message',
                dedupe_key TEXT UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 12,
                created_at INTEGER NOT NULL,
                available_at INTEGER NOT NULL,
                locked_at INTEGER,
                last_error TEXT
            )
            """
        )
        await self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_due "
            "ON outbox_messages(status, available_at, id)"
        )
        await self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_category "
            "ON outbox_messages(category, status)"
        )

    async def recover_inflight(self, *, older_than_seconds: int = 300) -> int:
        cutoff = int(time.time()) - max(0, int(older_than_seconds))
        cursor = await self.db.conn.execute(
            """
            UPDATE outbox_messages
               SET status='pending', locked_at=NULL
             WHERE status='inflight'
               AND COALESCE(locked_at, 0) <= ?
            """,
            (cutoff,),
        )
        await self.db.conn.commit()
        return max(0, int(cursor.rowcount or 0))

    async def enqueue(
        self,
        *,
        destination: str,
        body: str,
        message_type: str = "chat",
        category: str = "message",
        dedupe_key: str | None = None,
        available_at: int | None = None,
        max_attempts: int = 12,
    ) -> int:
        now = int(time.time())
        available = now if available_at is None else int(available_at)
        key = str(dedupe_key).strip() if dedupe_key else None
        params = (
            str(destination),
            str(body),
            str(message_type or "chat"),
            str(category or "message"),
            key,
            max(1, int(max_attempts)),
            now,
            available,
        )
        await self.db.conn.execute(
            """
            INSERT INTO outbox_messages (
                destination, body, message_type, category, dedupe_key,
                max_attempts, created_at, available_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO UPDATE SET
                destination=excluded.destination,
                body=excluded.body,
                message_type=excluded.message_type,
                category=excluded.category,
                max_attempts=excluded.max_attempts,
                available_at=MIN(outbox_messages.available_at, excluded.available_at),
                status=CASE
                    WHEN outbox_messages.status='dead' THEN 'pending'
                    ELSE outbox_messages.status
                END,
                last_error=CASE
                    WHEN outbox_messages.status='dead' THEN NULL
                    ELSE outbox_messages.last_error
                END
            """,
            params,
        )
        await self.db.conn.commit()
        if key:
            row = await self.db.fetch_one(
                "SELECT id FROM outbox_messages WHERE dedupe_key=?",
                (key,),
            )
        else:
            row = await self.db.fetch_one("SELECT last_insert_rowid() AS id")
        return int(row["id"])

    async def claim_due(self, *, limit: int = 20) -> list[OutboxMessage]:
        """Atomically claim due rows for the single delivery worker."""
        now = int(time.time())
        limit = max(1, min(200, int(limit)))
        cursor = await self.db.conn.execute(
            """
            UPDATE outbox_messages
               SET status='inflight', locked_at=?
             WHERE id IN (
                   SELECT id
                     FROM outbox_messages
                    WHERE status='pending' AND available_at <= ?
                    ORDER BY available_at, id
                    LIMIT ?
             )
               AND status='pending'
            RETURNING id, destination, body, message_type, category,
                      dedupe_key, attempts, max_attempts, created_at,
                      available_at, last_error
            """,
            (now, now, limit),
        )
        rows = await cursor.fetchall()
        await self.db.conn.commit()
        rows = sorted(rows, key=lambda row: (int(row["available_at"]), int(row["id"])))
        return [
            OutboxMessage(
                id=int(row["id"]),
                destination=str(row["destination"]),
                body=str(row["body"]),
                message_type=str(row["message_type"]),
                category=str(row["category"]),
                dedupe_key=row["dedupe_key"],
                attempts=int(row["attempts"]),
                max_attempts=int(row["max_attempts"]),
                created_at=int(row["created_at"]),
                available_at=int(row["available_at"]),
                last_error=row["last_error"],
            )
            for row in rows
        ]

    async def defer(
        self,
        message_id: int,
        *,
        retry_delay_seconds: int,
        reason: str | None = None,
    ) -> None:
        """Return an inflight row to pending without consuming an attempt."""
        await self.db.conn.execute(
            """
            UPDATE outbox_messages
               SET status='pending', available_at=?, locked_at=NULL,
                   last_error=?
             WHERE id=?
            """,
            (
                int(time.time()) + max(1, int(retry_delay_seconds)),
                str(reason)[:1000] if reason else None,
                int(message_id),
            ),
        )
        await self.db.conn.commit()

    async def mark_sent(self, message_id: int) -> None:
        await self.db.conn.execute(
            "DELETE FROM outbox_messages WHERE id=?",
            (int(message_id),),
        )
        await self.db.conn.commit()

    async def mark_failed(
        self,
        message: OutboxMessage,
        error: object,
        *,
        retry_delay_seconds: int,
    ) -> bool:
        attempts = int(message.attempts) + 1
        dead = attempts >= int(message.max_attempts)
        await self.db.conn.execute(
            """
            UPDATE outbox_messages
               SET status=?, attempts=?, available_at=?, locked_at=NULL,
                   last_error=?
             WHERE id=?
            """,
            (
                "dead" if dead else "pending",
                attempts,
                int(time.time()) + max(1, int(retry_delay_seconds)),
                f"{type(error).__name__}: {error}"[:1000],
                int(message.id),
            ),
        )
        await self.db.conn.commit()
        return dead

    async def retry_dead(self, *, category: str | None = None) -> int:
        if category:
            cursor = await self.db.conn.execute(
                """
                UPDATE outbox_messages
                   SET status='pending', attempts=0, available_at=?,
                       locked_at=NULL, last_error=NULL
                 WHERE status='dead' AND category=?
                """,
                (int(time.time()), str(category)),
            )
        else:
            cursor = await self.db.conn.execute(
                """
                UPDATE outbox_messages
                   SET status='pending', attempts=0, available_at=?,
                       locked_at=NULL, last_error=NULL
                 WHERE status='dead'
                """,
                (int(time.time()),),
            )
        await self.db.conn.commit()
        return max(0, int(cursor.rowcount or 0))

    async def counts(self) -> dict[str, int]:
        rows = await self.db.fetch_all(
            "SELECT status, COUNT(*) AS count FROM outbox_messages GROUP BY status"
        )
        result = {"pending": 0, "inflight": 0, "dead": 0, "total": 0}
        for row in rows:
            status = str(row["status"])
            count = int(row["count"])
            result[status] = count
            result["total"] += count
        return result

    async def oldest_pending_age(self) -> int:
        row = await self.db.fetch_one(
            "SELECT MIN(created_at) AS oldest FROM outbox_messages "
            "WHERE status IN ('pending', 'inflight')"
        )
        if row is None or row["oldest"] is None:
            return 0
        return max(0, int(time.time()) - int(row["oldest"]))

    async def dead_letters(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.db.fetch_all(
            """
            SELECT id, destination, category, attempts, max_attempts,
                   created_at, last_error
              FROM outbox_messages
             WHERE status='dead'
             ORDER BY id DESC
             LIMIT ?
            """,
            (max(1, min(200, int(limit))),),
        )
        return [dict(row) for row in rows]
