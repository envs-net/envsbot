from .helpers import *  # noqa: F401,F403


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
