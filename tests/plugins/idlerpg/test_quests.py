from .helpers import JOINED_ROOMS, idlerpg
from plugins.idlerpg import quests


def _online_player(jid: str, name: str, *, level: int = 40, next_ttl: int = 1000, x: int = 0, y: int = 0):
    JOINED_ROOMS.setdefault("room@conf", {"nicks": {}})["nicks"][name] = {"jid": jid, "affiliation": "member"}
    return idlerpg._normalize_player(
        jid,
        {
            "name": name,
            "class": "idler",
            "level": level,
            "next": next_ttl,
            "x": x,
            "y": y,
            "idled": idlerpg.QUEST_MIN_ONLINE_SECONDS,
        },
    )


def test_quest_reward_players_skips_missing_and_applies_unique_bonus():
    room = idlerpg._blank_room()
    alice = _online_player("alice@envs.net", "Alice", next_ttl=1000)
    bob = _online_player("bob@envs.net", "Bob", next_ttl=800)
    alice["unique_items"] = {"pair of boots": "The Boots of Silent Idling"}
    room["players"] = {
        "alice@envs.net": alice,
        "bob@envs.net": bob,
        "broken@envs.net": "not-a-player",
    }
    quest = {"questers": ["alice@envs.net", "missing@envs.net", "broken@envs.net", "bob@envs.net"]}

    completed, names, rewards = quests._quest_reward_players(room, quest)

    assert completed == [alice, bob]
    assert names == ["Alice", "Bob"]
    assert [(player["name"], percent) for player, percent in rewards] == [
        ("Alice", idlerpg.QUEST_REWARD_PERCENT + 5),
        ("Bob", idlerpg.QUEST_REWARD_PERCENT),
    ]
    assert alice["next"] == 700
    assert bob["next"] == 600
    assert alice["stats"]["quests_completed"] == 1
    assert bob["stats"]["quests_completed"] == 1
    assert "quest_hero" in alice["achievements"]
    assert "quest_hero" in bob["achievements"]


def test_complete_quest_reports_reward_range_and_resets_next_time():
    room = idlerpg._blank_room()
    alice = _online_player("alice@envs.net", "Alice", next_ttl=1000)
    bob = _online_player("bob@envs.net", "Bob", next_ttl=1000)
    alice["unique_items"] = {"pair of boots": "The Boots of Silent Idling"}
    room["players"] = {"alice@envs.net": alice, "bob@envs.net": bob}
    messages: list[str] = []

    quests._complete_quest(
        room,
        {"active": True, "questers": ["alice@envs.net", "bob@envs.net"]},
        1234,
        messages,
    )

    assert room["quest"] == {"active": False, "next_at": 1234 + idlerpg.QUEST_INTERVAL}
    assert messages[0] == "🧭 Alice, Bob completed their quest! 25-30% of their burden is removed."
    assert messages[1:] == [
        "Alice reaches next level in 0 days, 00:11:40.",
        "Bob reaches next level in 0 days, 00:12:30.",
    ]
    assert alice["next"] == 700
    assert bob["next"] == 750


def test_complete_quest_without_valid_questers_still_resets_state():
    room = idlerpg._blank_room()
    messages: list[str] = []

    quests._complete_quest(room, {"active": True, "questers": ["missing@envs.net"]}, 55, messages)

    assert messages == []
    assert room["quest"] == {"active": False, "next_at": 55 + idlerpg.QUEST_INTERVAL}


def test_fail_quest_penalizes_only_online_players_and_records_stats():
    room = idlerpg._blank_room()
    alice = _online_player("alice@envs.net", "Alice", level=1, next_ttl=100)
    bob = idlerpg._normalize_player(
        "bob@envs.net",
        {"name": "Bob", "level": 1, "next": 100, "logged_out": True},
    )
    room["players"] = {
        "alice@envs.net": alice,
        "bob@envs.net": bob,
        "broken@envs.net": object(),
    }
    messages: list[str] = []

    quests._fail_quest(room, "room@conf", 2000, messages)

    assert room["quest"] == {"active": False, "next_at": 2000 + idlerpg.QUEST_INTERVAL}
    assert alice["next"] > 100
    assert alice["penalties"]["quest"] == alice["next"] - 100
    assert alice["stats"]["quest_failures"] == 1
    assert "Alice receive a p15 penalty" in messages[0]
    assert bob["next"] == 100
    assert "quest" not in bob.get("penalties", {})


def test_fail_quest_without_online_players_reports_plain_failure():
    JOINED_ROOMS["room@conf"] = {"nicks": {}}
    room = idlerpg._blank_room()
    room["players"] = {"alice@envs.net": idlerpg._normalize_player("alice@envs.net", {"name": "Alice"})}
    messages: list[str] = []

    quests._fail_quest(room, "room@conf", 42, messages)

    assert messages == ["🧭 The quest failed before the route was completed."]
    assert room["quest"] == {"active": False, "next_at": 42 + idlerpg.QUEST_INTERVAL}


def test_maybe_advance_grid_quest_without_route_waits_or_completes():
    room = idlerpg._blank_room()
    alice = _online_player("alice@envs.net", "Alice", next_ttl=1000)
    room["players"] = {"alice@envs.net": alice}
    quest = {"active": True, "questers": ["alice@envs.net"], "complete_at": 500, "route": []}
    room["quest"] = quest
    messages: list[str] = []

    assert quests._maybe_advance_grid_quest(room, "room@conf", quest, 499, messages) is True
    assert messages == []
    assert room["quest"] is quest
    assert quest["active"] is True

    assert quests._maybe_advance_grid_quest(room, "room@conf", quest, 500, messages) is True
    assert room["quest"] == {"active": False, "next_at": 500 + idlerpg.QUEST_INTERVAL}
    assert messages[0] == "🧭 Alice completed their quest! 25% of their burden is removed."


def test_maybe_advance_grid_quest_advances_route_then_completes():
    room = idlerpg._blank_room()
    alice = _online_player("alice@envs.net", "Alice", next_ttl=1000, x=1, y=2)
    bob = _online_player("bob@envs.net", "Bob", next_ttl=900, x=1, y=2)
    room["players"] = {"alice@envs.net": alice, "bob@envs.net": bob}
    quest = {
        "active": True,
        "questers": ["alice@envs.net", "bob@envs.net"],
        "complete_at": 9999,
        "route": [[1, 2], [3, 4]],
        "route_index": 0,
    }
    messages: list[str] = []

    assert quests._maybe_advance_grid_quest(room, "room@conf", quest, 100, messages) is True
    assert quest["route_index"] == 1
    assert messages == ["🧭 The quest party reached [1,2] and now heads for [3,4]."]
    assert room["quest"]["active"] is False

    messages.clear()
    alice["x"] = bob["x"] = 3
    alice["y"] = bob["y"] = 4
    assert quests._maybe_advance_grid_quest(room, "room@conf", quest, 101, messages) is True
    assert room["quest"] == {"active": False, "next_at": 101 + idlerpg.QUEST_INTERVAL}
    assert messages[0] == "🧭 Alice, Bob completed their quest! 25% of their burden is removed."


def test_maybe_advance_grid_quest_fails_expired_unfinished_route():
    room = idlerpg._blank_room()
    alice = _online_player("alice@envs.net", "Alice", level=1, next_ttl=100, x=0, y=0)
    room["players"] = {"alice@envs.net": alice}
    quest = {
        "active": True,
        "questers": ["alice@envs.net"],
        "complete_at": 50,
        "route": [[9, 9]],
        "route_index": 0,
    }
    messages: list[str] = []

    assert quests._maybe_advance_grid_quest(room, "room@conf", quest, 50, messages) is True

    assert room["quest"] == {"active": False, "next_at": 50 + idlerpg.QUEST_INTERVAL}
    assert alice["next"] > 100
    assert messages == [
        "🧭 The quest failed before the route was completed. Alice receive a p15 penalty."
    ]
