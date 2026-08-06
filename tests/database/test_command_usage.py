import time

import pytest

from database.manager import DatabaseManager


@pytest.mark.asyncio
async def test_command_usage_aggregates_without_actor_data(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        now = int(time.time())
        await db.command_usage.record(
            "rss list", context="room", success=True, duration_ms=10, timestamp=now
        )
        await db.command_usage.record(
            "rss list", context="direct", success=False, duration_ms=30, timestamp=now
        )
        rows = await db.command_usage.summary(days=1)
        assert rows == [
            {
                "command_name": "rss list",
                "uses": 2,
                "failures": 1,
                "total_duration_ms": 40,
                "max_duration_ms": 30,
                "last_used_at": now,
            }
        ]
        assert await db.command_usage.all_time_commands() == {"rss list"}
        assert await db.command_usage.totals_since(now - 1) == {
            "uses": 2,
            "failures": 1,
        }
        columns = await db.fetch_all("PRAGMA table_info(command_usage)")
        assert {row["name"] for row in columns}.isdisjoint({"jid", "actor", "body"})
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_command_usage_prune(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        old = int(time.time()) - 10 * 86400
        await db.command_usage.record(
            "old", context="direct", success=True, duration_ms=1, timestamp=old
        )
        assert await db.command_usage.prune(retention_days=1) == 1
        assert await db.command_usage.all_time_commands() == set()
        assert await db.command_usage.prune(retention_days=0) == 0
    finally:
        await db.close()
