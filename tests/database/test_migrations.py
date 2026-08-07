from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from database.migrations import available_migrations


@pytest.mark.asyncio
async def test_room_invites_migration_creates_table_and_index():
    statements = []

    class Conn:
        async def execute(self, sql):
            statements.append(" ".join(sql.split()))

    @asynccontextmanager
    async def transaction(*, label="transaction"):
        assert label == "migration_room_invites"
        yield Conn()

    migration = next(
        item for item in available_migrations()
        if item.version == "0003_room_invites"
    )

    await migration.run(SimpleNamespace(transaction=transaction))

    joined = "\n".join(statements)
    assert "CREATE TABLE IF NOT EXISTS room_invites" in joined
    assert "UNIQUE(room_jid, inviter)" in joined
    assert "CREATE INDEX IF NOT EXISTS idx_room_invites_created_at" in joined
    assert "ON room_invites(created_at)" in joined

@pytest.mark.asyncio
async def test_outbox_origin_id_migration_backfills_existing_rows(tmp_db_path):
    from database.manager import DatabaseManager

    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect(start_background=False)
    try:
        await db.execute("DROP INDEX IF EXISTS idx_outbox_origin_id")
        async with db.transaction(label="legacy_outbox") as conn:
            # Simulate the pre-0009 table shape while keeping the other current
            # columns so the migration can be tested in isolation.
            await conn.execute(
                "INSERT INTO outbox_messages ("
                "destination, body, message_type, category, dedupe_key, "
                "origin_id, created_at, available_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("user@example.org", "hello", "chat", "message", "legacy:1", "", 10, 10),
            )

        migration = next(
            item for item in available_migrations()
            if item.version == "0009_outbox_origin_id"
        )
        await migration.run(db)
        row = await db.fetch_one(
            "SELECT origin_id FROM outbox_messages WHERE dedupe_key='legacy:1'"
        )
        assert row is not None
        assert len(str(row["origin_id"])) == 32
        indexes = await db.fetch_all("PRAGMA index_list(outbox_messages)")
        assert any(row["name"] == "idx_outbox_origin_id" for row in indexes)
    finally:
        await db.close()
