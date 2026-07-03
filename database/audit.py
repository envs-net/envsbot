"""Small SQLite-backed audit log for administrative actions."""

from __future__ import annotations

import json
from typing import Any


class AuditLog:
    """Persist and read admin/security-relevant bot events."""

    def __init__(self, conn):
        self.conn = conn

    async def init(self):
        """Create the audit_log table if it does not exist."""
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                event TEXT NOT NULL,
                actor TEXT,
                target TEXT,
                details TEXT DEFAULT '{}' NOT NULL
            )
            """
        )
        await self.conn.commit()

    async def append(
        self,
        event: str,
        *,
        actor: str | None = None,
        target: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append one audit event."""
        await self.conn.execute(
            """
            INSERT INTO audit_log (event, actor, target, details)
            VALUES (?, ?, ?, ?)
            """,
            (event, actor, target, json.dumps(details or {}, sort_keys=True)),
        )
        await self.conn.commit()

    async def list(
        self,
        *,
        limit: int = 20,
        actor: str | None = None,
        target: str | None = None,
        event: str | None = None,
    ):
        """Return latest audit events, optionally filtered."""
        limit = max(1, min(int(limit), 100))
        where = []
        params = []
        if actor:
            where.append("actor = ?")
            params.append(actor)
        if target:
            where.append("target = ?")
            params.append(target)
        if event:
            where.append("event = ?")
            params.append(event)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit)
        cursor = await self.conn.execute(
            f"""
            SELECT id, created_at, event, actor, target, details
            FROM audit_log
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return await cursor.fetchall()
