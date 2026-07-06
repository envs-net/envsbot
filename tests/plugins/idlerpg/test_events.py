from .helpers import *  # noqa: F401,F403


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

    monkeypatch.setattr(idlerpg.random, "choice", choice)
    monkeypatch.setattr(idlerpg.random, "random", lambda: 0.0)
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
        idlerpg.random,
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


def test_team_battle_changes_clocks_and_awards(monkeypatch):
    players = []
    for idx in range(6):
        jid = f"u{idx}@envs.net"
        player = idlerpg._normalize_player(
            jid,
            {"name": f"U{idx}", "class": "idler", "level": 30 + idx, "next": 10000, "items": {"weapon": 10 + idx}},
        )
        players.append((jid, player))

    monkeypatch.setattr(idlerpg.random, "sample", lambda seq, count: seq[:count])
    randint_values = itertools.cycle([9999, 0])
    monkeypatch.setattr(idlerpg.random, "randint", lambda _start, _stop: next(randint_values))

    messages = []
    idlerpg._run_team_battle(players, messages)

    assert any("team battled" in line for line in messages)
    assert players[0][1]["next"] < 10000
    assert players[3][1]["next"] > 10000
    assert "team_battle_winner" in players[0][1]["achievements"]


def test_random_event_uses_only_available_event_weights_for_small_rooms(monkeypatch):
    room = idlerpg._blank_room()
    room["players"]["alice@envs.net"] = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "sysadmin", "online": True},
    )
    monkeypatch.setattr(idlerpg, "EVENT_CHANCE", 1.0)
    random_values = itertools.cycle([0.0, 0.70])
    monkeypatch.setattr(idlerpg.random, "random", lambda: next(random_values))
    monkeypatch.setattr(
        idlerpg,
        "_run_item_blessing",
        lambda _players, _messages: _messages.append("item"),
    )
    monkeypatch.setattr(
        idlerpg,
        "_run_godsend_or_calamity",
        lambda _players, _messages: _messages.append("fate"),
    )

    messages = []
    asyncio.run(idlerpg._maybe_run_random_event(room, "room@conf", messages))

    assert messages == ["fate"]
