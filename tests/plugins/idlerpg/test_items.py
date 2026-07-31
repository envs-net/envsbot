from .helpers import (
    DummyBot,
    DummyMsg,
    idlerpg,
    pytest,
)
import random
from plugins.idlerpg import config as idlerpg_config
from plugins.idlerpg import items as idlerpg_items


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
    monkeypatch.setattr(random, "random", lambda: 1.0)

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
    monkeypatch.setattr(random, "random", lambda: 0.0)
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(random, "randint", lambda low, high: high)

    unique = idlerpg._roll_unique_item(player)
    assert unique is not None
    assert unique["name"] == idlerpg.UNIQUE_ITEMS[0]["name"]
    assert unique["level"] == idlerpg.UNIQUE_ITEMS[0]["max_item_level"]

    monkeypatch.setattr(
        idlerpg_items,
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


def test_unique_items_are_bound_to_players_and_protected_from_random_item_events(monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {
            "name": "Alice",
            "level": 70,
            "next": 1000,
            "items": {"weapon": 180, "ring": 20},
            "unique_items": {"weapon": "The Great Hammer of /bin/sh"},
        },
    )
    other = idlerpg._normalize_player(
        "bob@envs.net",
        {
            "name": "Bob",
            "level": 70,
            "next": 1000,
            "items": {"weapon": 300, "ring": 40},
        },
    )

    # Occupied unique slots may roll a strictly higher catalog tier, but the
    # roll itself never mutates the player's bound item.
    monkeypatch.setattr(idlerpg_config, "UNIQUE_ITEMS_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "UNIQUE_ITEM_MIN_LEVEL", 25)
    monkeypatch.setattr(idlerpg_config, "UNIQUE_ITEM_CHANCE", 1.0)
    monkeypatch.setattr(random, "random", lambda: 0.0)
    monkeypatch.setattr(
        random,
        "choice",
        lambda seq: next(
            entry
            for entry in seq
            if entry[0]["name"] == "The Starforged Blade of Patience"
        ),
    )
    monkeypatch.setattr(random, "randint", lambda low, high: low)
    rolled_unique = idlerpg._roll_unique_item(player)
    assert rolled_unique is not None
    assert rolled_unique["slot"] == "weapon"
    assert rolled_unique["tier"] == 3
    assert rolled_unique["level"] > player["items"]["weapon"]
    assert rolled_unique["upgrade_from"] == "The Great Hammer of /bin/sh"
    assert player["unique_items"]["weapon"] == "The Great Hammer of /bin/sh"

    # Ordinary loot in a unique slot is ignored instead of replacing/removing the
    # unique item marker.
    monkeypatch.setattr(idlerpg_items, "_roll_unique_item", lambda _player: None)
    monkeypatch.setattr(random, "choice", lambda seq: "weapon")
    monkeypatch.setattr(idlerpg_items, "_roll_weighted_item_level", lambda _level: 999)
    text = idlerpg._grant_level_item(player)
    assert "keeps The Great Hammer of /bin/sh" in text
    assert player["items"]["weapon"] == 180
    assert player["unique_items"]["weapon"] == "The Great Hammer of /bin/sh"

    # Damage events skip unique slots and can still affect ordinary gear.
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    messages: list[str] = []
    idlerpg._run_item_damage([("alice@envs.net", player)], messages)
    assert player["items"]["weapon"] == 180
    assert player["unique_items"]["weapon"] == "The Great Hammer of /bin/sh"
    assert player["items"]["ring"] == 18
    assert messages and "damaged their ring" in messages[0]

    # Battle drops and item swaps must not transfer or remove unique items from
    # either participant.
    messages.clear()
    monkeypatch.setattr(idlerpg_config, "ITEM_DROP_CHANCE", 1.0)
    idlerpg._maybe_battle_item_drop(player, other, messages)
    assert player["items"]["weapon"] == 180
    assert other["items"]["weapon"] == 300
    assert player["unique_items"]["weapon"] == "The Great Hammer of /bin/sh"
    assert all("weapon" not in message for message in messages)

    messages.clear()
    idlerpg._run_item_swap([("alice@envs.net", player), ("bob@envs.net", other)], messages)
    assert player["items"]["weapon"] == 180
    assert other["items"]["weapon"] == 300
    assert player["unique_items"]["weapon"] == "The Great Hammer of /bin/sh"
    assert all("weapon" not in message for message in messages)


def test_item_blessing_normalizes_bad_item_level_and_records(monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": 21, "next": 1000, "items": {"ring": "bad"}, "x": 300, "y": 230},
    )
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])

    messages: list[str] = []
    idlerpg._run_item_blessing([("alice@envs.net", player)], messages)

    assert player["items"][idlerpg.ITEMS[0]] == 2
    assert player["stats"]["item_blessings"] == 1
    assert messages and "wandering enchanter" in messages[0]
    assert "Velbragh" in messages[0]


def test_unique_catalog_covers_all_slots_and_high_level_tiers():
    slots = {str(item["slot"]) for item in idlerpg.UNIQUE_ITEMS}
    assert slots == set(idlerpg.ITEMS)
    unlock_levels = {int(item["min_level"]) for item in idlerpg.UNIQUE_ITEMS}
    assert {75, 85, 100, 125}.issubset(unlock_levels)
    assert any(item["slot"] == "pair of gloves" for item in idlerpg.UNIQUE_ITEMS)
    assert any(item["slot"] == "set of leggings" for item in idlerpg.UNIQUE_ITEMS)


def test_unique_upgrade_replaces_only_strictly_stronger_artifact(monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {
            "name": "Alice",
            "level": 125,
            "next": 1000,
            "items": {"pair of gloves": 120},
            "unique_items": {"pair of gloves": "The Gloves of Quiet Keystrokes"},
        },
    )
    stronger = {
        "name": "The Gauntlets of Graceful Restarts",
        "slot": "pair of gloves",
        "tier": 2,
        "level": 560,
        "bonus": "battle_bonus",
        "bonus_percent": 9,
    }
    monkeypatch.setattr(idlerpg_items, "_roll_unique_item", lambda _player: dict(stronger))

    result = idlerpg._grant_level_item(player)

    assert "upgraded The Gloves of Quiet Keystrokes" in result
    assert player["unique_items"]["pair of gloves"] == stronger["name"]
    assert player["items"]["pair of gloves"] == 560
    assert idlerpg._stats(player)["unique_item_upgrades"] == 1
    assert idlerpg._stats(player)["unique_items_found"] == 1

    weaker = {
        "name": "The Gloves of Quiet Keystrokes",
        "slot": "pair of gloves",
        "tier": 1,
        "level": 999,
        "bonus": "message_penalty_reduction",
        "bonus_percent": 5,
    }
    monkeypatch.setattr(idlerpg_items, "_roll_unique_item", lambda _player: dict(weaker))

    result = idlerpg._grant_level_item(player)

    assert "but keeps The Gauntlets of Graceful Restarts" in result
    assert player["unique_items"]["pair of gloves"] == stronger["name"]
    assert player["items"]["pair of gloves"] == 560
    assert idlerpg._stats(player)["unique_item_upgrades"] == 1


def test_unique_upgrade_never_replaces_unknown_or_higher_numeric_item(monkeypatch):
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {
            "name": "Alice",
            "level": 125,
            "next": 1000,
            "items": {"shield": 5000},
            "unique_items": {"shield": "The Ancient Shell of envs.net"},
        },
    )
    monkeypatch.setattr(idlerpg_config, "UNIQUE_ITEMS_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "UNIQUE_ITEM_MIN_LEVEL", 25)
    monkeypatch.setattr(idlerpg_config, "UNIQUE_ITEM_CHANCE", 1.0)
    monkeypatch.setattr(random, "random", lambda: 0.0)

    def choose_without_shield(seq):
        assert all(entry[0]["slot"] != "shield" for entry in seq)
        return seq[0]

    monkeypatch.setattr(random, "choice", choose_without_shield)
    rolled = idlerpg._roll_unique_item(player)
    assert rolled is not None
    assert rolled["slot"] != "shield"
    assert player["unique_items"]["shield"] == "The Ancient Shell of envs.net"
    assert player["items"]["shield"] == 5000

    player["unique_items"]["shield"] = "A private operator relic"
    candidate = {
        "name": "The Bastion of Immutable State",
        "slot": "shield",
        "tier": 4,
        "level": 6000,
        "bonus": "godsend_bonus",
        "bonus_percent": 14,
    }
    monkeypatch.setattr(idlerpg_items, "_roll_unique_item", lambda _player: dict(candidate))

    result = idlerpg._grant_level_item(player)

    assert "but keeps A private operator relic" in result
    assert player["unique_items"]["shield"] == "A private operator relic"
    assert player["items"]["shield"] == 5000


def test_unique_bonus_export_includes_tier_and_next_upgrade_level():
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {
            "name": "Alice",
            "items": {"pair of gloves": 120},
            "unique_items": {"pair of gloves": "The Gloves of Quiet Keystrokes"},
        },
    )

    [bonus] = idlerpg._unique_bonuses(player)

    assert bonus["tier"] == 1
    assert bonus["item_level"] == 120
    assert bonus["min_level"] == 35
    assert bonus["next_upgrade_level"] == 75


@pytest.mark.asyncio
async def test_items_command_shows_unique_tier_and_next_upgrade():
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
    player["items"]["pair of gloves"] = 120
    player["unique_items"]["pair of gloves"] = "The Gloves of Quiet Keystrokes"

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["items"], msg, True)

    output = bot.replies[-1][0]
    assert "The Gloves of Quiet Keystrokes [tier 1]" in output
    assert "next tier from level 75" in output
