from .helpers import (
    JOINED_ROOMS,
    idlerpg,
    types,
)
import random
import time

import pytest
from plugins.idlerpg import config as idlerpg_config
from plugins.idlerpg import formatting as idlerpg_formatting
from plugins.idlerpg import items as idlerpg_items


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
    monkeypatch.setattr(idlerpg_config, "MAX_PENALTY", 10)
    assert idlerpg._penalty_for(50, 100) == 10


def test_idlerpg_config_setting_preserves_explicit_zero(monkeypatch):
    monkeypatch.setattr(idlerpg_config, "_cfg", {"event_chance": 0})
    assert idlerpg_config._setting(
        "event_chance",
        "idlerpg_event_chance",
        0.01,
    ) == 0

    monkeypatch.setattr(idlerpg_config, "_cfg", {"event_chance": None})
    assert idlerpg_config._setting(
        "event_chance",
        "idlerpg_event_chance",
        0.01,
    ) == 0.01


def test_playtime_formatting_helpers_handle_edges(monkeypatch):
    assert idlerpg_formatting._created_at({"created_at": "123"}) == 123
    assert idlerpg_formatting._created_at({"created_at": -5}) == 0
    assert idlerpg_formatting._created_at({"created_at": "bad"}) == 0
    assert idlerpg_formatting._created_at({"created_at": None}) == 0
    assert idlerpg_formatting._created_at({}) == 0

    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: 200)
    assert idlerpg_formatting._played_for({}) == "unknown"
    assert idlerpg_formatting._played_for({"created_at": "bad"}) == "unknown"
    assert idlerpg_formatting._played_for({"created_at": 1}) == "0 days, 00:03:19"
    assert idlerpg_formatting._played_for({"created_at": 100}) == "0 days, 00:01:40"
    assert idlerpg_formatting._played_for({"created_at": 200}) == "0 days, 00:00:00"


def test_playing_since_uses_expected_timestamp_format(monkeypatch):
    sentinel_times = {1: object(), 123: object()}
    calls = []

    def fake_localtime(value):
        assert value in sentinel_times
        calls.append(("localtime", value))
        return sentinel_times[value]

    def fake_strftime(fmt, value):
        assert fmt == "%Y-%m-%d %H:%M:%S %Z"
        assert value in sentinel_times.values()
        calls.append(("strftime", fmt, value))
        return f"formatted-{fmt}-{id(value)}"

    monkeypatch.setattr(time, "localtime", fake_localtime)
    monkeypatch.setattr(time, "strftime", fake_strftime)

    assert idlerpg_formatting._playing_since({}) == "unknown"
    assert idlerpg_formatting._playing_since({"created_at": "bad"}) == "unknown"
    assert idlerpg_formatting._playing_since({"created_at": 1}) == (
        f"formatted-%Y-%m-%d %H:%M:%S %Z-{id(sentinel_times[1])}"
    )
    assert idlerpg_formatting._playing_since({"created_at": 123}) == (
        f"formatted-%Y-%m-%d %H:%M:%S %Z-{id(sentinel_times[123])}"
    )
    assert calls == [
        ("localtime", 1),
        ("strftime", "%Y-%m-%d %H:%M:%S %Z", sentinel_times[1]),
        ("localtime", 123),
        ("strftime", "%Y-%m-%d %H:%M:%S %Z", sentinel_times[123]),
    ]


def test_original_ttl_switches_to_linear_after_level_60():
    level_60 = int(idlerpg.RP_BASE * (idlerpg.RP_STEP ** 60))
    assert idlerpg._ttl_for_level(60) == level_60
    assert idlerpg._ttl_for_level(61) == level_60 + 86400
    assert idlerpg._ttl_for_level(63) == level_60 + (3 * 86400)


def test_original_weighted_item_roll_uses_one_point_five_level_cap(monkeypatch):
    captured = {}

    def fake_choices(population, *, weights, k):
        captured["population"] = list(population)
        captured["weights"] = list(weights)
        captured["k"] = k
        return [captured["population"][-1]]

    monkeypatch.setattr(random, "choices", fake_choices)

    assert idlerpg._roll_weighted_item_level(10) == 15
    assert captured["population"] == list(range(1, 16))
    assert captured["k"] == 1
    assert captured["weights"][0] > captured["weights"][-1]


def test_idlerpg_player_normalization_and_lookup_edges(monkeypatch):
    monkeypatch.setattr(random, "randint", lambda start, stop: stop)
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

    monkeypatch.setattr(random, "randint", fail_randint)
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
    monkeypatch.setattr(idlerpg_config, "MAP_STEP_PER_SECOND", 1)
    monkeypatch.setattr(random, "choice", lambda seq: next(choices))

    idlerpg._move_player(player, 3)
    assert (player["x"], player["y"]) == (10, 12)

    quest = {"active": True, "questers": ["alice@envs.net"], "route": [[14, 16]], "route_index": 0}
    monkeypatch.setattr(idlerpg_config, "QUEST_GRID_STEP_SECONDS", 2)
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


def test_weighted_item_roll_normalizes_low_levels_and_uses_exact_weights(monkeypatch):
    captured = []

    def fake_choices(population, *, weights, k):
        snapshot = (list(population), list(weights), k)
        captured.append(snapshot)
        return [snapshot[0][-1]]

    monkeypatch.setattr(idlerpg_items.random, "choices", fake_choices)

    assert idlerpg_items._roll_weighted_item_level(-50) == 1
    assert idlerpg_items._roll_weighted_item_level(0) == 1
    assert idlerpg_items._roll_weighted_item_level(2) == 3
    assert idlerpg_items._roll_weighted_item_level(3) == 4
    assert idlerpg_items._roll_weighted_item_level(11) == 16

    assert [entry[0] for entry in captured] == [
        [1],
        [1],
        [1, 2, 3],
        [1, 2, 3, 4],
        list(range(1, 17)),
    ]
    assert all(entry[2] == 1 for entry in captured)
    for population, weights, _k in captured:
        assert weights == pytest.approx([1.4 ** -level for level in population])
