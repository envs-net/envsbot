import copy

import pytest

from database.manager import DatabaseManager


def _state():
    return {
        "rooms": {
            "room@conf": {
                "name_index": {"alice": "alice@example.org"},
                "quest": {"active": False, "next_at": 200},
                "last_tick": 123,
                "created_at": 100,
                "season": {
                    "id": "season-current",
                    "started_at": 100,
                    "ends_at": 0,
                },
                "hall_of_fame": [
                    {
                        "id": "season-old",
                        "started_at": 1,
                        "ended_at": 99,
                        "winner": "Old",
                    }
                ],
                "players": {
                    "alice@example.org": {
                        "jid": "alice@example.org",
                        "name": "Alice",
                        "class": "sysadmin",
                        "level": 4,
                        "next": 120,
                    }
                },
                "events": [
                    {
                        "ts": 95,
                        "kind": "old",
                        "text": "retained recent event",
                    },
                    {
                        "ts": 110,
                        "kind": "game",
                        "text": "current event",
                    },
                ],
                "season_events": [
                    {
                        "ts": 110,
                        "kind": "game",
                        "text": "current event",
                    }
                ],
                "season_events_started_at": 100,
            }
        }
    }


@pytest.mark.asyncio
async def test_idlerpg_state_store_roundtrip_and_incremental_events(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        state = _state()
        await db.idlerpg.save_state(state)

        loaded = await db.idlerpg.load_state()
        room = loaded["rooms"]["room@conf"]
        assert room["players"]["alice@example.org"]["name"] == "Alice"
        assert room["season"]["id"] == "season-current"
        assert [season["id"] for season in room["hall_of_fame"]] == [
            "season-old"
        ]
        assert [event["text"] for event in room["events"]] == [
            "retained recent event",
            "current event",
        ]
        assert "season_events" not in room
        season_events = await db.idlerpg.load_season_events("room@conf", 100)
        assert [event["text"] for event in season_events] == ["current event"]

        # Re-saving the same state must not duplicate immutable event rows.
        await db.idlerpg.save_state(loaded)
        assert (await db.idlerpg.stats())["events"] == 2

        changed = copy.deepcopy(loaded)
        changed_room = changed["rooms"]["room@conf"]
        changed_room["players"]["alice@example.org"]["level"] = 5
        new_event = {"ts": 120, "kind": "game", "text": "new event"}
        changed_room["events"].append(new_event)
        await db.idlerpg.save_state(changed, room_jids={"room@conf"})

        reloaded = await db.idlerpg.load_state()
        reloaded_room = reloaded["rooms"]["room@conf"]
        assert reloaded_room["players"]["alice@example.org"]["level"] == 5
        assert "season_events" not in reloaded_room
        season_events = await db.idlerpg.load_season_events("room@conf", 100)
        assert [event["text"] for event in season_events] == [
            "current event",
            "new event",
        ]
        assert (await db.idlerpg.stats())["events"] == 3
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_idlerpg_state_store_removes_rooms_with_cascade(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        await db.idlerpg.save_state(_state())
        await db.idlerpg.save_state({"rooms": {}})

        assert await db.idlerpg.load_state() == {"rooms": {}}
        assert await db.idlerpg.stats() == {
            "rooms": 0,
            "players": 0,
            "seasons": 0,
            "events": 0,
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_idlerpg_save_state_is_safe_inside_existing_sqlite_transaction(tmp_db_path):
    """Regression for `cannot start a transaction within a transaction`."""
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        await db.conn.execute("BEGIN")
        assert db.conn.in_transaction is True

        await db.idlerpg.save_state(_state())

        # The store uses a nested savepoint and must leave the caller's outer
        # transaction intact instead of issuing another BEGIN.
        assert db.conn.in_transaction is True
        await db.conn.commit()
        loaded = await db.idlerpg.load_state()
        assert loaded["rooms"]["room@conf"]["players"]["alice@example.org"]["name"] == "Alice"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_idlerpg_pending_events_persist_full_history_without_ram_history(tmp_db_path):
    """Events pruned from the recent cache before save must still reach SQLite."""
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        state = _state()
        room = state["rooms"]["room@conf"]
        room.pop("season_events", None)
        room.pop("season_events_started_at", None)
        pending = [
            {
                "ts": ts,
                "kind": "game",
                "text": f"event {ts}",
                "_season_started_at": 100,
            }
            for ts in (101, 102, 103, 104)
        ]
        room["_pending_events"] = copy.deepcopy(pending)
        room["events"] = copy.deepcopy(pending[-2:])

        await db.idlerpg.save_state(state, room_jids={"room@conf"})

        assert "_pending_events" not in room
        history = await db.idlerpg.load_season_events("room@conf", 100)
        assert [event["text"] for event in history] == [
            "event 101",
            "event 102",
            "event 103",
            "event 104",
        ]
        reloaded = await db.idlerpg.load_state()
        assert [event["text"] for event in reloaded["rooms"]["room@conf"]["events"]] == [
            "event 103",
            "event 104",
        ]
        assert "season_events" not in reloaded["rooms"]["room@conf"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_idlerpg_pending_event_keeps_original_season_across_rollover(tmp_db_path):
    """A queued event must stay attached to the season in which it occurred."""
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        state = _state()
        room = state["rooms"]["room@conf"]
        room.pop("season_events", None)
        room.pop("season_events_started_at", None)
        room["season"] = {
            "id": "season-new",
            "started_at": 200,
            "ends_at": 0,
        }
        old_event = {
            "ts": 199,
            "kind": "season",
            "text": "old season finale",
            "_season_started_at": 100,
        }
        room["_pending_events"] = [copy.deepcopy(old_event)]
        room["events"] = [copy.deepcopy(old_event)]

        await db.idlerpg.save_state(state, room_jids={"room@conf"})

        old_history = await db.idlerpg.load_season_events("room@conf", 100)
        new_history = await db.idlerpg.load_season_events("room@conf", 200)
        assert [event["text"] for event in old_history] == ["old season finale"]
        assert new_history == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_idlerpg_partial_save_does_not_remove_other_rooms(tmp_db_path):
    db = DatabaseManager(tmp_db_path, flush_interval=999)
    await db.connect()
    try:
        state = _state()
        second = copy.deepcopy(state["rooms"]["room@conf"])
        second["players"] = {}
        second["name_index"] = {}
        state["rooms"]["other@conf"] = second
        await db.idlerpg.save_state(state)

        partial = copy.deepcopy(state)
        partial["rooms"].pop("other@conf")
        partial["rooms"]["room@conf"]["last_tick"] = 999
        await db.idlerpg.save_state(partial, room_jids={"room@conf"})

        loaded = await db.idlerpg.load_state()
        assert set(loaded["rooms"]) == {"room@conf", "other@conf"}
        assert loaded["rooms"]["room@conf"]["last_tick"] == 999
    finally:
        await db.close()
