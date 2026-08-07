from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any


class SqliteDbAdapter:
    """Minimal DatabaseManager-shaped adapter for isolated store unit tests."""

    def __init__(self, conn: Any):
        self.conn = conn
        self._counter = 0

    @asynccontextmanager
    async def transaction(self, *, label: str = "test"):
        self._counter += 1
        savepoint = f"test_{self._counter}"
        await self.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            yield self.conn
        except BaseException:
            await self.conn.execute(f"ROLLBACK TO {savepoint}")
            await self.conn.execute(f"RELEASE {savepoint}")
            raise
        else:
            await self.conn.execute(f"RELEASE {savepoint}")

    async def write(self, query: str, params=(), *, label: str = "write"):
        async with self.transaction(label=label) as conn:
            return await conn.execute(query, params)

    async def write_many(self, query: str, rows, *, label: str = "write_many"):
        async with self.transaction(label=label) as conn:
            return await conn.executemany(query, rows)

    async def fetch_one(self, query: str, params=()):
        cursor = await self.conn.execute(query, params)
        return await cursor.fetchone()

    async def fetch_all(self, query: str, params=()):
        cursor = await self.conn.execute(query, params)
        return await cursor.fetchall()
