import asyncio
import pytest

from database.manager import DatabaseManager
import database.manager as manager_mod


@pytest.mark.asyncio
async def test_database_manager_connect_execute_fetch_flush_close(monkeypatch):
    """
    Smoke tests for DatabaseManager:
    - connect() sets up connection and table managers
    - execute()/fetch_one()/fetch_all() work with the connection
    - flush() calls users.flush_all()
    - close() triggers final flush via the background task
    """

    class FakeUserManager:
        def __init__(self, conn):
            self.conn = conn
            self.init_called = False
            self.flush_count = 0

        async def init(self):
            self.init_called = True

        async def flush_all(self):
            # simulate some async work
            await asyncio.sleep(0)
            self.flush_count += 1

    class FakeRooms:
        def __init__(self, conn):
            self.conn = conn
            self.init_called = False

        async def init(self):
            self.init_called = True

    # Replace the real managers with fakes so we control flush behavior.
    monkeypatch.setattr(manager_mod, "UserManager", FakeUserManager)
    monkeypatch.setattr(manager_mod, "Rooms", FakeRooms)

    # Use an in-memory database. Set a long flush_interval so the background
    # automatic flush does not run during the short test window.
    db = DatabaseManager(":memory:", flush_interval=10)
    await db.connect()

    assert db.conn is not None
    assert isinstance(db.users, FakeUserManager)
    assert isinstance(db.rooms, FakeRooms)
    assert db.users.init_called is True
    assert db.rooms.init_called is True

    # Basic execute/fetch operations
    await db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
    await db.execute("INSERT INTO test (val) VALUES (?)", ("hello",))

    row = await db.fetch_one("SELECT val FROM test WHERE id=?", (1,))
    assert row is not None
    assert row["val"] == "hello"

    rows = await db.fetch_all("SELECT id, val FROM test")
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["val"] == "hello"

    # Manual flush should call our fake user's flush_all once
    await db.flush()
    assert db.users.flush_count == 1

    # Closing the database signals the background task to stop and guarantees a final flush
    await db.close()
    # final flush should have been called at least once more
    assert db.users.flush_count >= 2