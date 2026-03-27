import aiosqlite
import pytest

from database.rooms import Rooms


@pytest.mark.asyncio
async def test_rooms_crud():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    try:
        rooms = Rooms(conn)
        await rooms.init()

        # add
        await rooms.add("room1@example", "alice", autojoin=True)

        # get
        row = await rooms.get("room1@example")
        assert row is not None
        assert row["room_jid"] == "room1@example"
        assert row["nick"] == "alice"
        assert int(row["autojoin"]) == 1

        # list
        all_rooms = await rooms.list()
        assert isinstance(all_rooms, list)
        assert len(all_rooms) == 1
        assert all_rooms[0]["room_jid"] == "room1@example"

        # update
        await rooms.update("room1@example", nick="bob", autojoin=0)
        row2 = await rooms.get("room1@example")
        assert row2["nick"] == "bob"
        assert int(row2["autojoin"]) == 0

        # delete
        await rooms.delete("room1@example")
        row3 = await rooms.get("room1@example")
        assert row3 is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_status_get_set_delete_and_nested():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    try:
        rooms = Rooms(conn)
        await rooms.init()

        await rooms.add("room2@example", "carol")

        # initial status is empty dict
        status = await rooms.status_get("room2@example")
        assert status == {}

        # set nested path
        await rooms.status_set("room2@example", "a.b.c", "value123")
        got = await rooms.status_get("room2@example", "a.b.c")
        assert got == "value123"

        # set another nested value and verify top-level dict
        await rooms.status_set("room2@example", "x", 42)
        top = await rooms.status_get("room2@example")
        # keys a and x should exist
        assert top["x"] == 42
        assert top["a"]["b"]["c"] == "value123"

        # delete nested path
        await rooms.status_delete("room2@example", "a.b.c")
        after_del = await rooms.status_get("room2@example", "a.b.c")
        assert after_del is None

        # deleting a missing nested path should be a no-op (no exception)
        await rooms.status_delete("room2@example", "does.not.exist")

        # ensure remaining data persisted
        remaining = await rooms.status_get("room2@example")
        assert "a" in remaining  # 'a' exists but its 'b.c' was removed (b may be empty dict)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_status_ops_on_missing_room():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    try:
        rooms = Rooms(conn)
        await rooms.init()

        # Non-existent room: status_get returns None
        assert await rooms.status_get("nope@example") is None

        # status_set on non-existent room should do nothing (no exception)
        await rooms.status_set("nope@example", "a", 1)
        # still none
        assert await rooms.status_get("nope@example") is None

        # status_delete on non-existent room should do nothing (no exception)
        await rooms.status_delete("nope@example", "a")
    finally:
        await conn.close()
