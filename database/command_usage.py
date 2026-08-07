"""Persistent command execution statistics."""

from __future__ import annotations

import time
from typing import Any


class CommandUsageStore:
    """Aggregate command usage without retaining message bodies or JIDs."""

    def __init__(self, db):
        self.db = db

    async def init(self, *, commit: bool = True) -> None:
        await self.db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS command_usage (
                command_name TEXT NOT NULL,
                context TEXT NOT NULL,
                day TEXT NOT NULL,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                total_duration_ms INTEGER NOT NULL DEFAULT 0,
                max_duration_ms INTEGER NOT NULL DEFAULT 0,
                last_used_at INTEGER NOT NULL,
                PRIMARY KEY (command_name, context, day)
            )
            """
        )
        await self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_command_usage_last_used "
            "ON command_usage(last_used_at)"
        )
        if commit:
            await self.db.conn.commit()

    async def record(
        self,
        command_name: str,
        *,
        context: str,
        success: bool,
        duration_ms: int,
        timestamp: int | None = None,
    ) -> None:
        ts = int(time.time() if timestamp is None else timestamp)
        day = time.strftime("%Y-%m-%d", time.gmtime(ts))
        success_count = 1 if success else 0
        failure_count = 0 if success else 1
        duration = max(0, int(duration_ms))
        async with self.db.transaction_lock:
            await self.db.conn.execute(
                """
                INSERT INTO command_usage (
                    command_name, context, day, success_count, failure_count,
                    total_duration_ms, max_duration_ms, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(command_name, context, day) DO UPDATE SET
                    success_count=command_usage.success_count + excluded.success_count,
                    failure_count=command_usage.failure_count + excluded.failure_count,
                    total_duration_ms=command_usage.total_duration_ms + excluded.total_duration_ms,
                    max_duration_ms=MAX(command_usage.max_duration_ms, excluded.max_duration_ms),
                    last_used_at=MAX(command_usage.last_used_at, excluded.last_used_at)
                """,
                (
                    str(command_name),
                    str(context),
                    day,
                    success_count,
                    failure_count,
                    duration,
                    duration,
                    ts,
                ),
            )
            await self.db.conn.commit()

    async def summary(self, *, days: int = 30, limit: int = 30) -> list[dict[str, Any]]:
        cutoff = int(time.time()) - max(1, int(days)) * 86400
        rows = await self.db.fetch_all(
            """
            SELECT command_name,
                   SUM(success_count + failure_count) AS uses,
                   SUM(failure_count) AS failures,
                   SUM(total_duration_ms) AS total_duration_ms,
                   MAX(max_duration_ms) AS max_duration_ms,
                   MAX(last_used_at) AS last_used_at
              FROM command_usage
             WHERE last_used_at >= ?
             GROUP BY command_name
             ORDER BY uses DESC, command_name
             LIMIT ?
            """,
            (cutoff, max(1, min(500, int(limit)))),
        )
        return [dict(row) for row in rows]

    async def all_time_commands(self) -> set[str]:
        rows = await self.db.fetch_all("SELECT DISTINCT command_name FROM command_usage")
        return {str(row["command_name"]) for row in rows}

    async def totals_since(self, timestamp: int) -> dict[str, int]:
        row = await self.db.fetch_one(
            """
            SELECT COALESCE(SUM(success_count + failure_count), 0) AS uses,
                   COALESCE(SUM(failure_count), 0) AS failures
              FROM command_usage
             WHERE last_used_at >= ?
            """,
            (int(timestamp),),
        )
        return {
            "uses": int(row["uses"] if row else 0),
            "failures": int(row["failures"] if row else 0),
        }

    async def prune(self, *, retention_days: int) -> int:
        if int(retention_days) <= 0:
            return 0
        cutoff_day = time.strftime(
            "%Y-%m-%d",
            time.gmtime(time.time() - int(retention_days) * 86400),
        )
        async with self.db.transaction_lock:
            cursor = await self.db.conn.execute(
                "DELETE FROM command_usage WHERE day < ?",
                (cutoff_day,),
            )
            await self.db.conn.commit()
            return max(0, int(cursor.rowcount or 0))
