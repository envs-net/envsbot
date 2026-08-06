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
        assert [event["text"] for event in room["season_events"]] == [
            "current event"
        ]

        # Re-saving the same state must not duplicate immutable event rows.
        await db.idlerpg.save_state(loaded)
        assert (await db.idlerpg.stats())["events"] == 2

        changed = copy.deepcopy(loaded)
        changed_room = changed["rooms"]["room@conf"]
        changed_room["players"]["alice@example.org"]["level"] = 5
        new_event = {"ts": 120, "kind": "game", "text": "new event"}
        changed_room["events"].append(new_event)
        changed_room["season_events"].append(dict(new_event))
        await db.idlerpg.save_state(changed)

        reloaded = await db.idlerpg.load_state()
        reloaded_room = reloaded["rooms"]["room@conf"]
        assert reloaded_room["players"]["alice@example.org"]["level"] == 5
        assert [event["text"] for event in reloaded_room["season_events"]] == [
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
