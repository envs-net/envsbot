from .helpers import *  # noqa: F401,F403


@pytest.mark.asyncio
async def test_tick_levels_up_and_can_show_items(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        msg,
        True,
    )
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    player = room["players"]["alice@envs.net"]
    player["next"] = 1
    room["last_tick"] = idlerpg._now() - 2
    monkeypatch.setattr(idlerpg.random, "random", lambda: 1.0)

    await idlerpg._tick_room(bot, "room@conf", announce=True)

    assert player["level"] >= 1
    assert any("reached level" in text for text, _ in bot.replies)

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["items"], msg, True)
    assert "Items for Alice" in bot.replies[-1][0]


def test_unique_item_level_gating_bonuses_and_grant(monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": idlerpg.UNIQUE_ITEM_MIN_LEVEL - 1, "next": 1000},
    )
    assert idlerpg._roll_unique_item(player) is None

    player["level"] = 50
    monkeypatch.setattr(idlerpg.random, "random", lambda: 0.0)
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(idlerpg.random, "randint", lambda low, high: high)

    unique = idlerpg._roll_unique_item(player)
    assert unique is not None
    assert unique["name"] == idlerpg.UNIQUE_ITEMS[0]["name"]
    assert unique["level"] == idlerpg.UNIQUE_ITEMS[0]["max_item_level"]

    monkeypatch.setattr(
        idlerpg,
        "_roll_unique_item",
        lambda _player: {
            "name": "The Great Hammer of /bin/sh",
            "slot": "weapon",
            "level": 155,
            "bonus": "battle_bonus",
            "bonus_percent": 5,
        },
    )
    text = idlerpg._grant_level_item(player)
    assert "The Great Hammer of /bin/sh" in text
    assert player["items"]["weapon"] == 155
    assert player["unique_items"]["weapon"] == "The Great Hammer of /bin/sh"
    assert "unique_item" in player["achievements"]
    assert idlerpg._stats(player)["unique_items_found"] == 1
    assert idlerpg._unique_bonus_percent(player, "battle_bonus") == 5
    assert idlerpg._adjust_percent_amount(100, player, "battle_bonus", increase=True) == 105

    player["unique_items"] = {
        "weapon": "The Great Hammer of /bin/sh",
        "tunic": "The Cluehammer of Good Documentation",
        "shield": "not a real unique item",
    }
    assert idlerpg._unique_bonus_percent(player, "battle_bonus") == 13
    assert idlerpg._unique_bonus_percent(player, "missing_bonus") == 0


def test_item_blessing_normalizes_bad_item_level_and_records(monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": 21, "next": 1000, "items": {"ring": "bad"}, "x": 300, "y": 230},
    )
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[0])

    messages: list[str] = []
    idlerpg._run_item_blessing([("alice@envs.net", player)], messages)

    assert player["items"][idlerpg.ITEMS[0]] == 2
    assert player["stats"]["item_blessings"] == 1
    assert messages and "wandering enchanter" in messages[0]
    assert "Velbragh" in messages[0]
