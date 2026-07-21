import asyncio
import sys
import types

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
    assert "message_cache" in table_names
    assert "schema_migrations" in table_names

    applied = await db.applied_migration_versions()
    assert applied == {
        "0001_initial_runtime_tables",
        "0002_audit_log",
        "0003_room_invites",
        "0004_message_cache",
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
async def test_manual_flush_raises_after_retries(monkeypatch):
    db = DatabaseManager(":memory:")
    db.users = types.SimpleNamespace(
        flush_all=AsyncMock(side_effect=RuntimeError("write failed"))
    )
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    with pytest.raises(RuntimeError, match="write failed"):
        await db.flush()

    assert db.users.flush_all.await_count == 3


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

@pytest.mark.asyncio
async def test_database_manager_integrity_check_and_optimize(tmp_db_path):
    db = DatabaseManager(tmp_db_path)
    await db.connect()

    assert await db.integrity_check() == ["ok"]
    await db.optimize()

    await db.close()


@pytest.mark.asyncio
async def test_database_manager_integrity_check_stringifies_unusual_rows():
    class BadRow:
        def __getitem__(self, _index):
            raise TypeError("bad row")

        def __str__(self):
            return "bad-row"

    class Cursor:
        async def fetchall(self):
            return [("ok",), BadRow()]

    class Conn:
        def __init__(self):
            self.queries = []

        async def execute(self, sql):
            self.queries.append(sql)
            return Cursor()

        async def commit(self):
            self.queries.append("commit")

    db = DatabaseManager(":memory:")
    db.conn = Conn()

    assert await db.integrity_check() == ["ok", "bad-row"]
    await db.optimize()
    assert db.conn.queries == ["PRAGMA integrity_check;", "PRAGMA optimize;", "commit"]



@pytest.mark.asyncio
async def test_database_migration_status_and_read_write_check(tmp_path, monkeypatch):
    migrations = [
        types.SimpleNamespace(version="0001"),
        types.SimpleNamespace(version="0002"),
    ]
    monkeypatch.setattr("database.manager.available_migrations", lambda: migrations)

    db = DatabaseManager(str(tmp_path / "bot.db"), flush_interval=999)
    db.applied_migration_versions = AsyncMock(return_value={"0001"})
    assert await db.pending_migration_versions() == ["0002"]
    assert await db.migration_status() == {
        "known": ["0001", "0002"],
        "applied": ["0001"],
        "pending": ["0002"],
    }

    from database.migrations import available_migrations as real_available_migrations

    monkeypatch.setattr("database.manager.available_migrations", real_available_migrations)
    live_db = DatabaseManager(str(tmp_path / "live.db"), flush_interval=999)
    await live_db.connect()
    try:
        await live_db.verify_read_write()
        assert await live_db.fetch_one(
            "SELECT name FROM sqlite_temp_master WHERE name = ?",
            ("envsbot_preflight_check",),
        ) is None
        assert dict(await live_db.fetch_one("SELECT 1 AS ok")) == {"ok": 1}
    finally:
        await live_db.close()


@pytest.mark.asyncio
async def test_close_before_connect_and_repeated_close_are_safe(tmp_path):
    db = DatabaseManager(str(tmp_path / "never-opened.db"))
    await db.close()
    await db.close()
    assert db.conn is None


@pytest.mark.asyncio
async def test_connect_failure_closes_partial_connection(tmp_path, monkeypatch):
    db = DatabaseManager(str(tmp_path / "broken.db"))

    async def fail_migrations():
        raise RuntimeError("migration failed")

    monkeypatch.setattr(db, "run_migrations", fail_migrations)
    with pytest.raises(RuntimeError, match="migration failed"):
        await db.connect()

    assert db.conn is None
    await db.close()


@pytest.mark.asyncio
async def test_database_file_is_owner_only(tmp_path):
    path = tmp_path / "private.db"
    db = DatabaseManager(str(path))
    await db.connect()
    try:
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_close_continues_when_background_flush_task_failed(tmp_path):
    db = DatabaseManager(str(tmp_path / "flush-failed.db"))
    await db.connect()

    original_task = db._flush_task
    db._stop_event.set()
    await original_task

    async def fail_flush():
        raise RuntimeError("flush task failed")

    db._flush_task = asyncio.create_task(fail_flush())
    await asyncio.sleep(0)
    await db.close()

    assert db.conn is None
    assert db.users is None
