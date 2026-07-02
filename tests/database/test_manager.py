import sys

import pytest
import aiosqlite
from unittest.mock import AsyncMock

from database.manager import DatabaseManager


@pytest.mark.asyncio
async def test_database_manager_init_and_connect(tmp_db_path):
    db = DatabaseManager(tmp_db_path)
    await db.connect()
    # Check tables exist by querying PRAGMA
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table';"
    )
    table_names = {row['name'] for row in tables}
    assert "users" in table_names
    assert "users_runtime" in table_names
    assert "rooms" in table_names
    assert "audit_log" in table_names
    assert "room_invites" in table_names
    assert "schema_migrations" in table_names

    applied = await db.applied_migration_versions()
    assert applied == {
        "0001_initial_runtime_tables",
        "0002_audit_log",
        "0003_room_invites",
    }
    await db.close()


@pytest.mark.asyncio
async def test_database_manager_execute_fetch(tmp_db_path):
    db = DatabaseManager(tmp_db_path)
    await db.connect()
    # Insert a test row using execute
    await db.execute("INSERT INTO rooms (room_jid, nick) VALUES (?, ?)",
                     ("testroom@chat", "RoomBot"))
    # Fetch it back
    row = await db.fetch_one("SELECT * FROM rooms WHERE room_jid = ?",
                             ("testroom@chat",))
    assert row["room_jid"] == "testroom@chat"
    assert row["nick"] == "RoomBot"
    await db.close()


@pytest.mark.asyncio
async def test_database_manager_flush(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=0.1)
    await db.connect()
    # Add a user, triggers dirty cache in users manager
    await db.users.create("jid1@example.com", nickname="user1")
    await db.flush()
    row = await db.fetch_one("SELECT * FROM users WHERE jid=?",
                             ("jid1@example.com",))
    assert row["nickname"] == "user1"
    await db.close()


@pytest.mark.asyncio
async def test_database_manager_close_flushes(tmp_db_path):
    db = DatabaseManager(tmp_db_path)
    await db.connect()
    await db.users.create("jid2@example.com", nickname="test2")
    await db.close()
    # Assert data persisted after close
    async with aiosqlite.connect(tmp_db_path) as check_db:
        check_db.row_factory = aiosqlite.Row
        row = await check_db.execute("SELECT * FROM users WHERE jid=?",
                                     ("jid2@example.com",))
        result = await row.fetchone()
        assert result is not None
        assert result["nickname"] == "test2"


@pytest.mark.asyncio
async def test_database_manager_list_migrations():
    class Conn:
        async def execute(self, sql):
            assert "schema_migrations" in sql

            class Cursor:
                async def fetchall(self):
                    return [("0001", "now")]

            return Cursor()

    db = DatabaseManager(":memory:")
    db.conn = Conn()

    assert await db.list_migrations() == [("0001", "now")]


@pytest.mark.asyncio
async def test_applied_versions_and_run_migrations_skip_existing(monkeypatch):
    manager_mod = sys.modules[DatabaseManager.__module__]

    db = DatabaseManager(":memory:")
    db.list_migrations = AsyncMock(return_value=[{"version": "0001"}])
    assert await db.applied_migration_versions() == {"0001"}

    calls = []

    class Migration:
        def __init__(self, version):
            self.version = version
            self.description = f"description {version}"

        async def run(self, db_arg):
            assert db_arg is db
            calls.append(("run", self.version))

    db.applied_migration_versions = AsyncMock(return_value={"0001"})
    async def mark_applied(version):
        calls.append(("mark", version))

    db.mark_migration_applied = AsyncMock(side_effect=mark_applied)
    def fake_available_migrations():
        return (Migration("0001"), Migration("0002"), Migration("0003"))

    monkeypatch.setattr(
        manager_mod,
        "available_migrations",
        fake_available_migrations,
    )

    await db.run_migrations()

    assert calls == [
        ("run", "0002"),
        ("mark", "0002"),
        ("run", "0003"),
        ("mark", "0003"),
    ]
