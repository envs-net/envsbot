from .helpers import (
    JOINED_ROOMS,
    idlerpg,
    types,
)


def test_duration_clock_and_next_level_line():
    player = {"name": "Alice", "next": 93784}
    assert idlerpg._duration_clock(93784) == "1 days, 02:03:04"
    assert idlerpg._next_level_line(player) == "Alice reaches next level in 1 days, 02:03:04."


def test_idlerpg_small_helper_edges(monkeypatch):
    bot = types.SimpleNamespace(prefix="!")
    assert idlerpg._command_prefix(bot) == "!"
    assert idlerpg._command_prefix(types.SimpleNamespace(prefix="")) == ","
    assert idlerpg._possessive("Chris") == "Chris'"
    assert idlerpg._possessive("Alice") == "Alice's"
    assert idlerpg._duration(None) == "0s"
    assert idlerpg._duration(90061) == "1d 1h 1m 1s"
    assert idlerpg._add_time({"next": -5}, -10) == 0
    player = {"next": 5}
    assert idlerpg._remove_time(player, 10) == 5
    assert player["next"] == 0
    assert idlerpg._safe_name(" Alice !@#_-. 123 ") == "Alice_-.123"
    assert idlerpg._safe_class("sys\n\tadmin   ops") == "sysadmin ops"
    assert idlerpg._ttl_for_level(-10) == idlerpg._ttl_for_level(0)
    monkeypatch.setattr(idlerpg, "MAX_PENALTY", 10)
    assert idlerpg._penalty_for(50, 100) == 10


def test_idlerpg_player_normalization_and_lookup_edges(monkeypatch):
    monkeypatch.setattr(idlerpg.random, "randint", lambda start, stop: stop)
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {
            "name": "Alice!",
            "class": "sys\nadmin",
            "level": "bad",
            "next": "bad",
            "alignment": "x",
            "items": {"weapon": "bad", "shield": 3},
            "unique_items": {"weapon": "The Great Hammer of /bin/sh", "bad": "ignored"},
            "stats": {"wins": "bad", "losses": -5},
            "achievements": "bad",
            "title": "level_10",
            "x": 9999,
            "y": 9999,
        },
    )
    assert player["name"] == "Alice"
    assert player["class"] == "sysadmin"
    assert player["level"] == 0
    assert player["next"] == idlerpg._ttl_for_level(0)
    assert player["alignment"] == "n"
    assert player["items"]["weapon"] == 0
    assert player["items"]["shield"] == 3
    assert player["unique_items"] == {"weapon": "The Great Hammer of /bin/sh"}
    assert player["stats"] == {"wins": 0, "losses": 0}
    assert player["achievements"] == []
    assert player["title"] == ""
    assert 0 <= player["x"] <= idlerpg.MAP_X
    assert 0 <= player["y"] <= idlerpg.MAP_Y

    room = {
        "players": {"alice@envs.net": player, "bad@envs.net": "not-a-player"},
        "name_index": {},
    }
    assert idlerpg._rebuild_name_index(room) == {"alice": "alice@envs.net"}
    assert idlerpg._find_player(room, None) == (None, None)
    assert idlerpg._find_player(room, "alice@envs.net") == ("alice@envs.net", player)
    assert idlerpg._find_player(room, "Alice") == ("alice@envs.net", player)
    assert idlerpg._find_player(room, "missing") == (None, None)


def test_normalize_player_does_not_consume_rng_for_existing_coordinates(monkeypatch):
    def fail_randint(_start, _stop):
        raise AssertionError("coordinate RNG should not be used when coordinates already exist")

    monkeypatch.setattr(idlerpg.random, "randint", fail_randint)
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "sysadmin", "x": 12, "y": 34},
    )

    assert player["x"] == 12
    assert player["y"] == 34


def test_original_style_grid_movement_and_quest_direction(monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "x": 10, "y": 10},
    )
    choices = iter([1, 0, -1, 1, 0, 1])
    monkeypatch.setattr(idlerpg, "MAP_STEP_PER_SECOND", 1)
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: next(choices))

    idlerpg._move_player(player, 3)
    assert (player["x"], player["y"]) == (10, 12)

    quest = {"active": True, "questers": ["alice@envs.net"], "route": [[14, 16]], "route_index": 0}
    monkeypatch.setattr(idlerpg, "QUEST_GRID_STEP_SECONDS", 2)
    idlerpg._move_player(player, 4, quest=quest, jid="alice@envs.net")
    assert (player["x"], player["y"]) == (12, 14)


def test_quest_target_helpers_validate_route_and_online_state():
    quest = {"active": True, "questers": ["alice@envs.net"], "route": [[5, 6], [7, 8]], "route_index": 1}
    player = idlerpg._normalize_player("alice@envs.net", {"name": "Alice", "x": 7, "y": 8})
    room_players = {"alice@envs.net": player}
    JOINED_ROOMS["room@conf"] = {"nicks": {"Alice": {"jid": "alice@envs.net"}}}

    assert idlerpg._active_quest_target(quest) == (7, 8)
    assert idlerpg._questers_at_target(room_players, quest) is True
    assert idlerpg._questers_at_target(room_players, quest, room_jid="room@conf") is True

    JOINED_ROOMS["room@conf"] = {"nicks": {}}
    assert idlerpg._questers_at_target(room_players, quest, room_jid="room@conf") is False
    assert idlerpg._active_quest_target({"active": False, "route": [[1, 2]]}) is None
