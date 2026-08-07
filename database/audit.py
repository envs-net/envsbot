"""Small SQLite-backed audit log for administrative actions."""

from __future__ import annotations

import asyncio
import json
from typing import Any


class AuditLog:
    """Persist and read admin/security-relevant bot events."""

    def __init__(self, conn, transaction_lock=None):
        self.conn = conn
        self._transaction_lock = transaction_lock or asyncio.Lock()

    async def init(self, *, commit: bool = True):
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
        if commit:
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
        async with self._transaction_lock:
            await self.conn.execute(
                """
                INSERT INTO audit_log (event, actor, target, details)
                VALUES (?, ?, ?, ?)
                """,
                (event, actor, target, json.dumps(details or {}, sort_keys=True)),
            )
            await self.conn.commit()

    def _filter_sql(
        self,
        *,
        actor: str | None = None,
        target: str | None = None,
        event: str | None = None,
    ) -> tuple[str, list[str]]:
        """Build a WHERE clause and params for audit filters."""
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
        return (f"WHERE {' AND '.join(where)}" if where else "", params)

    async def count(
        self,
        *,
        actor: str | None = None,
        target: str | None = None,
        event: str | None = None,
    ) -> int:
        """Return the number of audit events matching optional filters."""
        where_sql, params = self._filter_sql(actor=actor, target=target, event=event)
        cursor = await self.conn.execute(
            f"SELECT COUNT(*) AS count FROM audit_log {where_sql}",
            tuple(params),
        )
        row = await cursor.fetchone()
        return int(row["count"] if hasattr(row, "keys") else row[0])

    async def list(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        actor: str | None = None,
        target: str | None = None,
        event: str | None = None,
    ):
        """Return latest audit events, optionally filtered."""
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))
        where_sql, params = self._filter_sql(actor=actor, target=target, event=event)
        params.extend([limit, offset])
        cursor = await self.conn.execute(
            f"""
            SELECT id, created_at, event, actor, target, details
            FROM audit_log
            {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        )
        return await cursor.fetchall()


    async def summary_since(self, *, hours: int = 24, limit: int = 8) -> dict[str, Any]:
        """Return aggregate audit statistics for recent events."""
        hours = max(1, int(hours))
        limit = max(1, min(int(limit), 25))
        since_modifier = f"-{hours} hours"
        since_params = (since_modifier,)

        async def scalar(sql: str, params: tuple[object, ...] = since_params) -> int:
            cursor = await self.conn.execute(sql, params)
            row = await cursor.fetchone()
            if row is None:
                return 0
            return int(row[0])

        async def grouped(sql: str) -> list[dict[str, Any]]:
            cursor = await self.conn.execute(sql, (since_modifier, limit))
            rows = await cursor.fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                try:
                    name = row["name"]
                    count = row["count"]
                except Exception:
                    name, count = row[0], row[1]
                result.append({"name": str(name), "count": int(count)})
            return result

        total = await scalar(
            "SELECT COUNT(*) FROM audit_log "
            "WHERE created_at >= datetime('now', ?)"
        )
        errors = await scalar(
            """
            SELECT COUNT(*)
            FROM audit_log
            WHERE created_at >= datetime('now', ?)
              AND (
                lower(event) LIKE '%error%'
                OR lower(event) LIKE '%failed%'
                OR lower(event) LIKE '%failure%'
                OR lower(details) LIKE '%"error"%'
                OR lower(details) LIKE '%"exception"%'
                OR lower(details) LIKE '%"traceback"%'
                OR lower(details) LIKE '%"status": "error"%'
                OR lower(details) LIKE '%"status":"error"%'
                OR lower(details) LIKE '%"status": "failed"%'
                OR lower(details) LIKE '%"status":"failed"%'
                OR lower(details) LIKE '%"result": "error"%'
                OR lower(details) LIKE '%"result":"error"%'
                OR lower(details) LIKE '%"result": "failed"%'
                OR lower(details) LIKE '%"result":"failed"%'
              )
            """
        )
        unique_actors = await scalar(
            "SELECT COUNT(DISTINCT actor) FROM audit_log "
            "WHERE created_at >= datetime('now', ?) "
            "AND actor IS NOT NULL AND actor != ''"
        )
        unique_targets = await scalar(
            "SELECT COUNT(DISTINCT target) FROM audit_log "
            "WHERE created_at >= datetime('now', ?) "
            "AND target IS NOT NULL AND target != ''"
        )

        return {
            "hours": hours,
            "total": total,
            "errors": errors,
            "unique_actors": unique_actors,
            "unique_targets": unique_targets,
            "events": await grouped(
                """
                SELECT COALESCE(NULLIF(event, ''), '—') AS name, COUNT(*) AS count
                FROM audit_log
                WHERE created_at >= datetime('now', ?)
                GROUP BY name
                ORDER BY count DESC, name ASC
                LIMIT ?
                """
            ),
            "actors": await grouped(
                """
                SELECT COALESCE(NULLIF(actor, ''), '—') AS name, COUNT(*) AS count
                FROM audit_log
                WHERE created_at >= datetime('now', ?)
                GROUP BY name
                ORDER BY count DESC, name ASC
                LIMIT ?
                """
            ),
            "targets": await grouped(
                """
                SELECT COALESCE(NULLIF(target, ''), '—') AS name, COUNT(*) AS count
                FROM audit_log
                WHERE created_at >= datetime('now', ?)
                GROUP BY name
                ORDER BY count DESC, name ASC
                LIMIT ?
                """
            ),
        }

    async def export_jsonl(
        self,
        *,
        limit: int = 100,
        actor: str | None = None,
        target: str | None = None,
        event: str | None = None,
    ) -> str:
        """Return recent audit events as JSON Lines."""
        rows = await self.list(limit=limit, actor=actor, target=target, event=event)
        lines = []
        for row in reversed(rows):
            try:
                details = json.loads(row["details"] or "{}")
            except Exception:
                details = {}
            lines.append(json.dumps({
                "id": row["id"],
                "created_at": row["created_at"],
                "event": row["event"],
                "actor": row["actor"],
                "target": row["target"],
                "details": details,
            }, sort_keys=True))
        return "\n".join(lines)

    async def prune_older_than(self, days: int, *, dry_run: bool = False) -> int:
        """Delete audit events older than *days* and return affected count."""
        days = max(1, int(days))
        cursor = await self.conn.execute(
            "SELECT COUNT(*) AS count FROM audit_log "
            "WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        row = await cursor.fetchone()
        count = int(row["count"] if hasattr(row, "keys") else row[0])
        if dry_run or count == 0:
            return count
        async with self._transaction_lock:
            await self.conn.execute(
                "DELETE FROM audit_log WHERE created_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            await self.conn.commit()
        return count
