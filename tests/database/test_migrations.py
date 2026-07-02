from types import SimpleNamespace

import pytest

from database.migrations import available_migrations


@pytest.mark.asyncio
async def test_room_invites_migration_creates_table_and_index():
    statements = []

    class Conn:
        async def execute(self, sql):
            statements.append(" ".join(sql.split()))

    migration = next(
        item for item in available_migrations()
        if item.version == "0003_room_invites"
    )

    await migration.run(SimpleNamespace(conn=Conn()))

    joined = "\n".join(statements)
    assert "CREATE TABLE IF NOT EXISTS room_invites" in joined
    assert "UNIQUE(room_jid, inviter)" in joined
    assert "CREATE INDEX IF NOT EXISTS idx_room_invites_created_at" in joined
    assert "ON room_invites(created_at)" in joined
