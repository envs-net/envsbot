from .helpers import (
    asyncio,
    idlerpg,
    itertools,
)
import random
from plugins.idlerpg import config as idlerpg_config
from plugins.idlerpg import events as idlerpg_events
from plugins.idlerpg import items as idlerpg_items


def test_original_alignment_battle_power_and_critical_chances(monkeypatch):
    base_items = {"weapon": 100}
    neutral = idlerpg._normalize_player("n@envs.net", {"name": "Neutral", "level": 1, "alignment": "n", "items": base_items})
    good = idlerpg._normalize_player("g@envs.net", {"name": "Good", "level": 1, "alignment": "g", "items": base_items})
    evil = idlerpg._normalize_player("e@envs.net", {"name": "Evil", "level": 1, "alignment": "e", "items": base_items})

    assert idlerpg._battle_power(good) == idlerpg._battle_power(neutral) + 10
    assert idlerpg._battle_power(evil) == idlerpg._battle_power(neutral) - 10
    assert idlerpg._critical_strike_chance(neutral) == idlerpg.CRITICAL_STRIKE_CHANCE
    assert idlerpg._critical_strike_chance(good) == idlerpg.CRITICAL_STRIKE_CHANCE_GOOD
    assert idlerpg._critical_strike_chance(evil) == idlerpg.CRITICAL_STRIKE_CHANCE_EVIL

    loser = idlerpg._normalize_player("l@envs.net", {"name": "Loser", "next": 1000})
    messages: list[str] = []
    monkeypatch.setattr(random, "random", lambda: idlerpg.CRITICAL_STRIKE_CHANCE_GOOD + 0.001)
    idlerpg._maybe_critical_strike(good, loser, messages)
    assert messages == []
    monkeypatch.setattr(random, "random", lambda: idlerpg.CRITICAL_STRIKE_CHANCE_EVIL - 0.001)
    monkeypatch.setattr(random, "randint", lambda low, high: low)
    idlerpg._maybe_critical_strike(evil, loser, messages)
    assert any("Critical Strike" in line for line in messages)


def test_pvp_battle_can_crit_and_drop_item(monkeypatch):
    alice = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "sysadmin", "level": 10, "next": 10000, "items": {"weapon": 1}},
    )
    bob = idlerpg._normalize_player(
        "bob@envs.net",
        {"name": "Bob", "class": "wizard", "level": 10, "next": 10000, "items": {"weapon": 20}},
    )
    players = [("alice@envs.net", alice), ("bob@envs.net", bob)]

    def choice(seq):
        return seq[0]

    monkeypatch.setattr(random, "choice", choice)
    monkeypatch.setattr(random, "random", lambda: 0.0)
    # Values are consumed in order by successive random.randint calls in
    # _run_pvp_battle: attacker_roll, defender_roll, critical_strike_amount,
    # dropped_item_level.
    attacker_roll = 999
    defender_roll = 0
    critical_strike_amount = 120
    dropped_item_level = 30
    battle_randint_values = iter(
        [attacker_roll, defender_roll, critical_strike_amount, dropped_item_level]
    )
    monkeypatch.setattr(
        random,
        "randint",
        lambda _start, _stop: next(battle_randint_values),
    )

    messages = []
    idlerpg._run_pvp_battle(players, messages)

    assert alice["next"] < 10000
    assert bob["next"] > 10000
    assert alice["items"]["weapon"] == 20
    assert bob["items"]["weapon"] == 1
    assert any("has challenged Bob" in line and "won" in line for line in messages)
    assert any("Critical Strike" in line for line in messages)
    assert any("dropped their level 20 weapon" in line for line in messages)
    assert any("Bob reaches next level in" in line for line in messages)
    assert alice["stats"]["battles_won"] == 1
    assert bob["stats"]["battles_lost"] == 1


def test_losing_attacker_records_battle_loss(monkeypatch):
    alice = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": 10, "next": 10000, "items": {"weapon": 1}},
    )
    bob = idlerpg._normalize_player(
        "bob@envs.net",
        {"name": "Bob", "level": 10, "next": 10000, "items": {"weapon": 20}},
    )
    rolls = iter([0, 999])
    monkeypatch.setattr(random, "randint", lambda _start, _stop: next(rolls))
    monkeypatch.setattr(random, "random", lambda: 1.0)

    messages: list[str] = []
    winner, loser = idlerpg._run_duel_between(alice, bob, messages)

    assert winner is bob
    assert loser is alice
    assert bob["stats"]["battles_won"] == 1
    assert alice["stats"]["battles_lost"] == 1


def test_team_battle_changes_clocks_and_awards(monkeypatch):
    players = []
    for idx in range(6):
        jid = f"u{idx}@envs.net"
        player = idlerpg._normalize_player(
            jid,
            {"name": f"U{idx}", "class": "idler", "level": 30 + idx, "next": 10000, "items": {"weapon": 10 + idx}},
        )
        players.append((jid, player))

    monkeypatch.setattr(random, "sample", lambda seq, count: seq[:count])
    randint_values = itertools.cycle([9999, 0])
    monkeypatch.setattr(random, "randint", lambda _start, _stop: next(randint_values))

    messages = []
    idlerpg._run_team_battle(players, messages)

    assert any("team battled" in line for line in messages)
    assert players[0][1]["next"] < 10000
    assert players[3][1]["next"] > 10000
    assert "team_battle_winner" in players[0][1]["achievements"]
    assert all(player["stats"]["team_battles_won"] == 1 for _jid, player in players[:3])
    assert all(player["stats"]["team_battles_lost"] == 1 for _jid, player in players[3:])


def test_random_event_uses_only_available_event_weights_for_small_rooms(monkeypatch):
    room = idlerpg._blank_room()
    room["players"]["alice@envs.net"] = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "sysadmin", "online": True},
    )
    monkeypatch.setattr(idlerpg_config, "EVENT_CHANCE", 1.0)
    random_values = itertools.cycle([0.0, 0.70])
    monkeypatch.setattr(random, "random", lambda: next(random_values))
    monkeypatch.setattr(
        idlerpg_items,
        "_run_item_blessing",
        lambda _players, _messages, _room=None: _messages.append("item"),
    )
    monkeypatch.setattr(
        idlerpg_events,
        "_run_godsend_or_calamity",
        lambda _players, _messages, _room=None: _messages.append("fate"),
    )

    messages = []
    asyncio.run(idlerpg._maybe_run_random_event(room, "room@conf", messages))

    assert messages == ["fate"]


def test_original_style_grid_battle_only_when_players_meet(monkeypatch):
    room = idlerpg._blank_room()
    alice = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": 10, "next": 1000, "x": 42, "y": 42},
    )
    bob = idlerpg._normalize_player(
        "bob@envs.net",
        {"name": "Bob", "level": 10, "next": 1000, "x": 42, "y": 42},
    )
    away = idlerpg._normalize_player(
        "away@envs.net",
        {"name": "Away", "level": 10, "next": 1000, "x": 40, "y": 42},
    )
    players = [("alice@envs.net", alice), ("bob@envs.net", bob), ("away@envs.net", away)]
    messages: list[str] = []

    monkeypatch.setattr(random, "random", lambda: 0.0)
    monkeypatch.setattr(random, "sample", lambda seq, count: list(seq)[:count])
    monkeypatch.setattr(random, "randint", lambda start, stop: stop)

    assert idlerpg._maybe_run_grid_battle(players, messages, room) is True
    assert any("has challenged" in message for message in messages)

    messages.clear()
    monkeypatch.setattr(random, "random", lambda: 1.0)
    assert idlerpg._maybe_run_grid_battle(players, messages, room) is False
    assert messages == []


def test_grid_battle_does_not_make_grid_questers_fight_each_other(monkeypatch):
    room = idlerpg._blank_room()
    room["quest"] = {
        "active": True,
        "type": "grid",
        "questers": ["alice@envs.net", "bob@envs.net"],
        "route": [[42, 42], [84, 84]],
    }
    alice = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": 10, "next": 1000, "x": 42, "y": 42},
    )
    bob = idlerpg._normalize_player(
        "bob@envs.net",
        {"name": "Bob", "level": 10, "next": 1000, "x": 42, "y": 42},
    )
    players = [("alice@envs.net", alice), ("bob@envs.net", bob)]
    messages: list[str] = []

    monkeypatch.setattr(random, "random", lambda: 0.0)
    monkeypatch.setattr(random, "randint", lambda start, stop: stop)

    assert idlerpg._maybe_run_grid_battle(players, messages, room) is False
    assert messages == []


def test_grid_quester_can_still_meet_non_quest_player(monkeypatch):
    room = idlerpg._blank_room()
    room["quest"] = {
        "active": True,
        "type": "grid",
        "questers": ["alice@envs.net", "bob@envs.net"],
        "route": [[42, 42], [84, 84]],
    }
    alice = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": 10, "next": 1000, "x": 42, "y": 42},
    )
    bob = idlerpg._normalize_player(
        "bob@envs.net",
        {"name": "Bob", "level": 10, "next": 1000, "x": 42, "y": 42},
    )
    outsider = idlerpg._normalize_player(
        "outsider@envs.net",
        {"name": "Outsider", "level": 10, "next": 1000, "x": 42, "y": 42},
    )
    players = [
        ("alice@envs.net", alice),
        ("bob@envs.net", bob),
        ("outsider@envs.net", outsider),
    ]
    messages: list[str] = []

    monkeypatch.setattr(random, "random", lambda: 0.0)
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(random, "randint", lambda start, stop: stop)

    assert idlerpg._maybe_run_grid_battle(players, messages, room) is True
    assert any("Outsider" in message for message in messages)


def test_boss_event_defeat_awards_and_records_event(monkeypatch):
    room = idlerpg._blank_room()
    players = []
    for idx in range(3):
        jid = f"boss{idx}@envs.net"
        player = idlerpg._normalize_player(
            jid,
            {
                "name": f"Boss{idx}",
                "level": idlerpg.BOSS_MIN_LEVEL,
                "next": 10000,
                "items": {"weapon": 50},
            },
        )
        players.append((jid, player))

    monkeypatch.setattr(random, "sample", lambda seq, count: list(seq)[:count])
    monkeypatch.setattr(random, "uniform", lambda _start, _stop: 1.0)
    randint_values = itertools.cycle([9999, 0])
    monkeypatch.setattr(random, "randint", lambda _start, _stop: next(randint_values))
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])

    messages = []
    assert idlerpg._run_boss_event(players, messages, room) is True

    assert any("faced Ancient Root Daemon" in message and "defeated it" in message for message in messages)
    assert all(player["next"] < 10000 for _jid, player in players)
    assert all(player["stats"]["bosses_defeated"] == 1 for _jid, player in players)
    assert all("boss_slayer" in player["achievements"] for _jid, player in players)
    assert room["events"][-1]["kind"] == "boss"
    assert room["events"][-1]["data"]["result"] == "defeated"


def test_boss_event_failure_records_losses(monkeypatch):
    room = idlerpg._blank_room()
    players = []
    for idx in range(3):
        jid = f"boss{idx}@envs.net"
        player = idlerpg._normalize_player(
            jid,
            {
                "name": f"Boss{idx}",
                "level": idlerpg.BOSS_MIN_LEVEL,
                "next": 10000,
                "items": {"weapon": 50},
            },
        )
        players.append((jid, player))

    monkeypatch.setattr(random, "sample", lambda seq, count: list(seq)[:count])
    monkeypatch.setattr(random, "uniform", lambda _start, _stop: 1.0)
    rolls = iter([0, 9999])
    monkeypatch.setattr(random, "randint", lambda _start, _stop: next(rolls))
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])

    messages: list[str] = []
    assert idlerpg._run_boss_event(players, messages, room) is True

    assert any("failed" in message for message in messages)
    assert all(player["stats"]["bosses_failed"] == 1 for _jid, player in players)
    assert room["events"][-1]["data"]["result"] == "failed"


def test_boss_event_requires_enough_eligible_players():
    player = idlerpg._normalize_player(
        "low@envs.net",
        {"name": "Low", "level": max(0, idlerpg.BOSS_MIN_LEVEL - 1), "next": 10000},
    )
    messages = []

    assert idlerpg._run_boss_event([("low@envs.net", player)], messages, idlerpg._blank_room()) is False
    assert messages == []
