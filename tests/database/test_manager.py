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
    assert "idlerpg_rooms" in table_names
    assert "idlerpg_players" in table_names
    assert "idlerpg_seasons" in table_names
    assert "idlerpg_events" in table_names
    assert "outbox_messages" in table_names
    assert "command_usage" in table_names
    assert "schema_migrations" in table_names

    applied = await db.applied_migration_versions()
    assert applied == {
        "0001_initial_runtime_tables",
        "0002_audit_log",
        "0003_room_invites",
        "0004_message_cache",
        "0005_idlerpg_state",
        "0006_outbox",
        "0007_command_usage",
        "0008_outbox_dead_timestamp",
        "0009_outbox_origin_id",
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
async def test_applied_versions_and_run_migrations_skip_existing(tmp_path, monkeypatch):
    manager_mod = sys.modules[DatabaseManager.__module__]
    calls = []

    class Migration:
        def __init__(self, version):
            self.version = version
            self.description = f"description {version}"

        async def run(self, db_arg):
            calls.append(("run", self.version))
            await db_arg.conn.execute(
                f"CREATE TABLE migrated_{self.version} (value INTEGER)"
            )

    def fake_available_migrations():
        return (Migration("0001"), Migration("0002"), Migration("0003"))

    monkeypatch.setattr(manager_mod, "available_migrations", fake_available_migrations)
    db = DatabaseManager(str(tmp_path / "migrations.db"), flush_interval=999)
    await db.connect(run_migrations=False, start_background=False)
    try:
        await db.mark_migration_applied("0001")
        assert await db.applied_migration_versions() == {"0001"}

        applied = await db.run_migrations(backup_before=False)

        assert applied == ["0002", "0003"]
        assert calls == [("run", "0002"), ("run", "0003")]
        assert await db.applied_migration_versions() == {"0001", "0002", "0003"}
        history = await db.migration_history(limit=10)
        assert [row["version"] for row in history] == ["0003", "0002"]
        assert all(row["status"] == "applied" for row in history)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_failed_migration_rolls_back_savepoint_and_records_failure(tmp_path, monkeypatch):
    manager_mod = sys.modules[DatabaseManager.__module__]

    class BrokenMigration:
        version = "9000_broken"
        description = "create then fail"

        async def run(self, db_arg):
            await db_arg.conn.execute("CREATE TABLE must_rollback (value INTEGER)")
            raise RuntimeError("migration exploded")

    monkeypatch.setattr(manager_mod, "available_migrations", lambda: (BrokenMigration(),))
    db = DatabaseManager(str(tmp_path / "broken-migration.db"), flush_interval=999)
    await db.connect(run_migrations=False, start_background=False)
    try:
        with pytest.raises(RuntimeError, match="migration exploded"):
            await db.run_migrations(backup_before=False)

        assert await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE name='must_rollback'"
        ) is None
        assert "9000_broken" not in await db.applied_migration_versions()
        history = await db.migration_history(limit=1)
        assert history[0]["version"] == "9000_broken"
        assert history[0]["status"] == "failed"
        assert "migration exploded" in str(history[0]["error"])
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_database_refuses_unknown_newer_migration(tmp_path):
    from database.manager import DatabaseSchemaTooNewError

    db = DatabaseManager(str(tmp_path / "newer-schema.db"), flush_interval=999)
    await db.connect(run_migrations=False, start_background=False)
    try:
        await db.mark_migration_applied("9999_future_schema")
        with pytest.raises(DatabaseSchemaTooNewError, match="newer than this envsbot build"):
            await db.assert_schema_compatible()
    finally:
        await db.close()


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
    assert db.conn.queries == ["PRAGMA integrity_check;", "PRAGMA optimize;"]


@pytest.mark.asyncio
async def test_database_migration_status_and_read_write_check(tmp_path, monkeypatch):
    migrations = [
        types.SimpleNamespace(version="0001"),
        types.SimpleNamespace(version="0002"),
    ]
    monkeypatch.setattr("database.manager.available_migrations", lambda: migrations)

    db = DatabaseManager(str(tmp_path / "bot.db"), flush_interval=999)
    db.applied_migration_versions = AsyncMock(return_value={"0001"})
    db.migration_history = AsyncMock(return_value=[])
    assert await db.pending_migration_versions() == ["0002"]
    assert await db.migration_status() == {
        "known": ["0001", "0002"],
        "applied": ["0001"],
        "pending": ["0002"],
        "unknown": [],
        "last_run": None,
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
    await asyncio.gather(original_task)

    async def fail_flush():
        raise RuntimeError("flush task failed")

    db._flush_task = asyncio.create_task(fail_flush())
    await asyncio.sleep(0)
    await db.close()

    assert db.conn is None
    assert db.users is None

@pytest.mark.asyncio
async def test_database_maintenance_optimizes_checkpoints_and_prunes(tmp_db_path, monkeypatch):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        monkeypatch.setitem(sys.modules[DatabaseManager.__module__].config, "database_wal_enabled", True)
        monkeypatch.setitem(sys.modules[DatabaseManager.__module__].config, "command_usage_retention_days", 1)
        db.command_usage.prune = AsyncMock(return_value=2)

        state = await db.run_maintenance()

        assert state["runs"] == 1
        assert state["failures"] == 0
        assert state["last_run_at"] > 0
        assert state["last_duration_ms"] >= 0
        assert state["last_wal_checkpoint"] is not None
        db.command_usage.prune.assert_awaited_once_with(retention_days=1)
    finally:
        await db.close()

@pytest.mark.asyncio
async def test_nested_database_transactions_rollback_only_inner_scope(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect(start_background=False)
    try:
        async with db.transaction(label="outer") as conn:
            await conn.execute(
                "INSERT INTO rooms (room_jid, nick) VALUES (?, ?)",
                ("outer@conf", "Outer"),
            )
            with pytest.raises(RuntimeError, match="inner failed"):
                async with db.transaction(label="inner") as inner:
                    await inner.execute(
                        "INSERT INTO rooms (room_jid, nick) VALUES (?, ?)",
                        ("inner@conf", "Inner"),
                    )
                    raise RuntimeError("inner failed")
            await conn.execute(
                "INSERT INTO rooms (room_jid, nick) VALUES (?, ?)",
                ("after@conf", "After"),
            )

        rows = await db.fetch_all("SELECT room_jid FROM rooms ORDER BY room_jid")
        assert [row["room_jid"] for row in rows] == ["after@conf", "outer@conf"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_database_transaction_rolls_back_outer_scope_on_cancelled_error(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect(start_background=False)
    try:
        with pytest.raises(asyncio.CancelledError):
            async with db.transaction(label="cancelled") as conn:
                await conn.execute(
                    "INSERT INTO rooms (room_jid, nick) VALUES (?, ?)",
                    ("cancelled@conf", "Cancelled"),
                )
                raise asyncio.CancelledError

        assert await db.fetch_one(
            "SELECT room_jid FROM rooms WHERE room_jid=?",
            ("cancelled@conf",),
        ) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_database_write_helpers_commit_atomically(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect(start_background=False)
    try:
        await db.write(
            "INSERT INTO rooms (room_jid, nick) VALUES (?, ?)",
            ("write@conf", "Write"),
        )
        await db.write_many(
            "INSERT INTO rooms (room_jid, nick) VALUES (?, ?)",
            (("many-a@conf", "A"), ("many-b@conf", "B")),
        )
        rows = await db.fetch_all("SELECT room_jid FROM rooms ORDER BY room_jid")
        assert [row["room_jid"] for row in rows] == [
            "many-a@conf",
            "many-b@conf",
            "write@conf",
        ]
    finally:
        await db.close()
