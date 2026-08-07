"""Persistent storage for the shared recent-message cache."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class MessageCacheStore:
    """SQLite-backed storage for bounded recent conversation messages."""

    def __init__(self, db):
        self.db = db

    async def init(self, *, commit: bool = True) -> None:
        """Create the persistent message-cache table and lookup indexes."""
        del commit
        async with self.db.transaction(label="message_cache_init") as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS message_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cache_key TEXT NOT NULL UNIQUE,
                    conversation TEXT NOT NULL,
                    stanza_id TEXT,
                    sender_nick TEXT,
                    sender_jid TEXT,
                    body TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    received_at INTEGER NOT NULL
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_cache_conversation_id "
                "ON message_cache(conversation, id)"
            )
            await conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_message_cache_reply_lookup "
                "ON message_cache(conversation, stanza_id) "
                "WHERE stanza_id IS NOT NULL"
            )

    async def prune_all(
        self,
        limit_per_conversation: int,
        *,
        min_received_at: int | None = None,
    ) -> int:
        """Apply the current age and per-conversation retention limits."""
        removed = 0
        limit = max(1, int(limit_per_conversation))
        async with self.db.transaction(label="message_cache_prune") as conn:
            if min_received_at is not None:
                cursor = await conn.execute(
                    "DELETE FROM message_cache WHERE received_at < ?",
                    (int(min_received_at),),
                )
                removed += max(0, int(cursor.rowcount or 0))
            cursor = await conn.execute(
                """
                DELETE FROM message_cache
                WHERE id IN (
                    SELECT id
                    FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY conversation
                                   ORDER BY id DESC
                               ) AS row_number
                        FROM message_cache
                    )
                    WHERE row_number > ?
                )
                """,
                (limit,),
            )
            removed += max(0, int(cursor.rowcount or 0))
        return removed

    async def load_recent(
        self,
        limit_per_conversation: int,
        *,
        min_received_at: int | None = None,
    ) -> list[dict[str, Any]]:
        """Load the retained rows in stable conversation/message order."""
        limit = max(1, int(limit_per_conversation))
        cutoff = 0 if min_received_at is None else int(min_received_at)
        rows = await self.db.fetch_all(
            """
            SELECT id, cache_key, conversation, stanza_id, sender_nick,
                   sender_jid, body, message_type, received_at
            FROM (
                SELECT id, cache_key, conversation, stanza_id, sender_nick,
                       sender_jid, body, message_type, received_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY conversation
                           ORDER BY id DESC
                       ) AS row_number
                FROM message_cache
                WHERE received_at >= ?
            )
            WHERE row_number <= ?
            ORDER BY conversation ASC, id ASC
            """,
            (cutoff, limit),
        )
        return [dict(row) for row in rows]

    async def save_batch(
        self,
        entries: Iterable[Mapping[str, Any]],
        *,
        limit_per_conversation: int,
        min_received_at: int | None = None,
    ) -> None:
        """Persist an idempotent batch and prune each touched conversation."""
        rows = [
            (
                str(entry["cache_key"]),
                str(entry["conversation"]),
                entry.get("stanza_id"),
                entry.get("nick"),
                entry.get("sender_jid"),
                str(entry["body"]),
                str(entry.get("message_type") or "unknown"),
                int(entry["received_at"]),
            )
            for entry in entries
        ]
        if not rows:
            return

        limit = max(1, int(limit_per_conversation))
        conversations = sorted({row[1] for row in rows})
        async with self.db.transaction(label="message_cache_save_batch") as conn:
            if min_received_at is not None:
                await conn.execute(
                    "DELETE FROM message_cache WHERE received_at < ?",
                    (int(min_received_at),),
                )
            await conn.executemany(
                """
                INSERT OR IGNORE INTO message_cache (
                    cache_key, conversation, stanza_id, sender_nick,
                    sender_jid, body, message_type, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            for conversation in conversations:
                await conn.execute(
                    """
                    DELETE FROM message_cache
                    WHERE conversation = ?
                      AND id NOT IN (
                          SELECT id
                          FROM message_cache
                          WHERE conversation = ?
                          ORDER BY id DESC
                          LIMIT ?
                      )
                    """,
                    (conversation, conversation, limit),
                )

    async def clear_conversation(self, conversation: str) -> int:
        """Delete all persisted rows for one conversation."""
        cursor = await self.db.write(
            "DELETE FROM message_cache WHERE conversation = ?",
            (str(conversation),),
            label="message_cache_clear",
        )
        return max(0, int(cursor.rowcount or 0))

    async def count(self) -> int:
        """Return the number of retained persistent rows."""
        row = await self.db.fetch_one("SELECT COUNT(*) AS count FROM message_cache")
        return int(row["count"] if row else 0)
