from .helpers import JOINED_ROOMS, idlerpg
from plugins.idlerpg import quests
from plugins.idlerpg import config as idlerpg_config


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
        {"active": True, "type": "grid", "questers": ["alice@envs.net", "bob@envs.net"]},
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

    quests._complete_quest(room, {"active": True, "type": "grid", "questers": ["missing@envs.net"]}, 55, messages)

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

    room["quest"] = {"active": True, "type": "grid", "route": [[1, 2]], "questers": ["alice@envs.net"]}

    quests._fail_quest(room, "room@conf", 42, messages)

    assert messages == ["🧭 The quest failed before the route was completed."]
    assert room["quest"] == {"active": False, "next_at": 42 + idlerpg.QUEST_INTERVAL}


def test_maybe_advance_grid_quest_without_route_waits_or_completes():
    room = idlerpg._blank_room()
    alice = _online_player("alice@envs.net", "Alice", next_ttl=1000)
    room["players"] = {"alice@envs.net": alice}
    quest = {"active": True, "type": "grid", "questers": ["alice@envs.net"], "complete_at": 500, "route": []}
    room["quest"] = quest
    messages: list[str] = []

    assert quests._maybe_advance_grid_quest(room, "room@conf", quest, 499, messages) is True
    assert messages == []
    assert room["quest"] is quest
    assert quest["active"] is True

    assert quests._maybe_advance_grid_quest(room, "room@conf", quest, 500, messages) is True
    assert room["quest"] == {"active": False, "next_at": 500 + idlerpg.QUEST_INTERVAL}
    assert messages[0] == "🧭 The grid quest had no route to complete. Alice receive a p15 penalty."


def test_maybe_advance_grid_quest_advances_route_then_completes():
    room = idlerpg._blank_room()
    alice = _online_player("alice@envs.net", "Alice", next_ttl=1000, x=1, y=2)
    bob = _online_player("bob@envs.net", "Bob", next_ttl=900, x=1, y=2)
    room["players"] = {"alice@envs.net": alice, "bob@envs.net": bob}
    quest = {
        "active": True,
        "type": "grid",
        "questers": ["alice@envs.net", "bob@envs.net"],
        "complete_at": 9999,
        "route": [[1, 2], [3, 4]],
        "route_index": 0,
    }
    room["quest"] = quest
    messages: list[str] = []

    assert quests._maybe_advance_grid_quest(room, "room@conf", quest, 100, messages) is True
    assert quest["route_index"] == 1
    assert messages == ["🧭 The quest party reached [1,2] and now heads for [3,4]."]
    assert room["quest"] is quest
    assert room["quest"]["active"] is True

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
        "type": "grid",
        "questers": ["alice@envs.net"],
        "complete_at": 50,
        "route": [[9, 9]],
        "route_index": 0,
    }
    room["quest"] = quest
    messages: list[str] = []

    assert quests._maybe_advance_grid_quest(room, "room@conf", quest, 50, messages) is True

    assert room["quest"] == {"active": False, "next_at": 50 + idlerpg.QUEST_INTERVAL}
    assert alice["next"] > 100
    assert messages == [
        "🧭 The quest failed before the route was completed. Alice receive a p15 penalty."
    ]


def test_quest_type_weights_and_selection(monkeypatch):
    monkeypatch.setattr(idlerpg_config, "QUEST_GRID_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "QUEST_TIME_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "QUEST_GRID_WEIGHT", 0.25)
    monkeypatch.setattr(idlerpg_config, "QUEST_TIME_WEIGHT", 0.75)

    assert quests._quest_type({"active": True, "type": "time"}) == "time"
    assert quests._quest_type({"active": True, "route": [[1, 2]]}) == "grid"
    assert quests._quest_type_weights() == [("grid", 0.25), ("time", 0.75)]

    monkeypatch.setattr(quests.random, "random", lambda: 0.9)
    assert quests._choose_quest_type() == "time"
    monkeypatch.setattr(quests.random, "random", lambda: 0.1)
    assert quests._choose_quest_type() == "grid"


def test_quest_type_weights_disable_all(monkeypatch):
    monkeypatch.setattr(idlerpg_config, "QUEST_GRID_ENABLED", False)
    monkeypatch.setattr(idlerpg_config, "QUEST_TIME_ENABLED", False)

    assert quests._quest_type_weights() == []
    assert quests._choose_quest_type() is None


def test_maybe_complete_time_quest_waits_completes_or_fails_when_offline():
    JOINED_ROOMS["room@conf"] = {"nicks": {}}
    room = idlerpg._blank_room()
    alice = _online_player("alice@envs.net", "Alice", next_ttl=1000)
    bob = _online_player("bob@envs.net", "Bob", next_ttl=800)
    room["players"] = {"alice@envs.net": alice, "bob@envs.net": bob}
    quest = {
        "active": True,
        "type": "time",
        "questers": ["alice@envs.net", "bob@envs.net"],
        "complete_at": 500,
    }
    room["quest"] = quest
    messages: list[str] = []

    assert quests._maybe_complete_time_quest(room, "room@conf", quest, 499, messages) is True
    assert messages == []
    assert room["quest"] is quest

    assert quests._maybe_complete_time_quest(room, "room@conf", quest, 500, messages) is True
    assert room["quest"] == {"active": False, "next_at": 500 + idlerpg.QUEST_INTERVAL}
    assert messages[0] == "🧭 Alice, Bob completed their time-based quest! 25% of their burden is removed."

    room = idlerpg._blank_room()
    alice = _online_player("alice@envs.net", "Alice", level=1, next_ttl=100)
    room["players"] = {"alice@envs.net": alice}
    JOINED_ROOMS["room@conf"] = {"nicks": {}}
    quest = {"active": True, "type": "time", "questers": ["alice@envs.net"], "complete_at": 10}
    room["quest"] = quest
    messages = []

    assert quests._maybe_complete_time_quest(room, "room@conf", quest, 10, messages) is True
    assert "not all questers were still online" in messages[0]


def test_maybe_fail_time_quest_for_penalty_only_affects_time_questers():
    room = idlerpg._blank_room()
    alice = _online_player("alice@envs.net", "Alice", level=1, next_ttl=100)
    bob = _online_player("bob@envs.net", "Bob", level=1, next_ttl=100)
    room["players"] = {"alice@envs.net": alice, "bob@envs.net": bob}
    room["quest"] = {
        "active": True,
        "type": "time",
        "questers": ["alice@envs.net"],
        "complete_at": 999,
    }
    messages: list[str] = []

    assert quests._maybe_fail_time_quest_for_penalty(
        room, "room@conf", "bob@envs.net", 100, messages, reason="message"
    ) is False
    assert room["quest"]["active"] is True

    assert quests._maybe_fail_time_quest_for_penalty(
        room, "room@conf", "alice@envs.net", 101, messages, reason="message"
    ) is True
    assert room["quest"] == {"active": False, "next_at": 101 + idlerpg.QUEST_INTERVAL}
    assert "Alice received a message penalty" in messages[0]
    assert alice["penalties"]["quest"] > 0
    assert bob["penalties"]["quest"] > 0


def test_start_time_and_grid_quests_build_expected_state(monkeypatch):
    room = idlerpg._blank_room()
    players = {
        f"p{i}@envs.net": _online_player(f"p{i}@envs.net", f"P{i}", x=10, y=10)
        for i in range(4)
    }
    room["players"] = players
    questers = list(players)
    messages: list[str] = []

    monkeypatch.setattr(idlerpg_config, "WEBSITE_PUBLIC_BASE_URL", "https://envs.net/idlerpg")
    monkeypatch.setattr(quests.random, "randint", lambda low, high: low)
    quests._start_time_quest(room, "room@conf", questers, "save the realm", 100, messages)

    assert room["quest"]["type"] == "time"
    assert room["quest"]["complete_at"] == 100 + idlerpg.QUEST_TIME_MIN_DURATION
    assert "time-based quest" in messages[0]
    assert "https://envs.net/idlerpg/?view=quest" in messages[0]

    values = iter([11, 12, 13, 14])
    monkeypatch.setattr(quests.random, "randint", lambda low, high: next(values) if high == idlerpg.MAP_X or high == idlerpg.MAP_Y else low)
    messages.clear()
    quests._start_grid_quest(room, "room@conf", questers, "map the world", 200, messages)

    assert room["quest"]["type"] == "grid"
    assert room["quest"]["route"] == [[11, 12], [13, 14]]
    assert "grid-based quest" in messages[0]
    assert "https://envs.net/idlerpg/?view=quest" in messages[0]
