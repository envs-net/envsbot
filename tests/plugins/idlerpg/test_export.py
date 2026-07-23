import json

from .helpers import (
    DummyBot,
    DummyTask,
    idlerpg,
    pytest,
)


@pytest.mark.asyncio
async def test_cleanup_room_state_removes_data_and_task():
    bot = DummyBot()
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = {"rooms": {"room@conf": idlerpg._blank_room()}}
    idlerpg.ROOM_TASKS["room@conf"] = DummyTask()

    await idlerpg.cleanup_room_state(bot, "room@conf")

    assert "room@conf" not in bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]
    assert "room@conf" not in idlerpg.ROOM_TASKS


def test_public_rules_include_new_options():
    rules = idlerpg._public_rules()
    assert rules["announce_login"] is True
    assert rules["topic_custom_text"] == idlerpg.TOPIC_CUSTOM_TEXT
    assert "item_damage_event_weight" in rules
    assert "item_steal_event_weight" in rules
    assert rules["manual_duel_max_distance"] == idlerpg.MANUAL_DUEL_MAX_DISTANCE
    assert rules["manual_duel_cooldown_seconds"] == idlerpg.MANUAL_DUEL_COOLDOWN_SECONDS
    assert "season_achievement_gates_enabled" in rules
    assert rules["boss_event_weight"] == idlerpg.BOSS_EVENT_WEIGHT
    assert rules["boss_min_players"] == idlerpg.BOSS_MIN_PLAYERS
    assert rules["boss_max_players"] == idlerpg.BOSS_MAX_PLAYERS
    assert rules["boss_min_level"] == idlerpg.BOSS_MIN_LEVEL
    assert rules["boss_reward_percent"] == idlerpg.BOSS_REWARD_PERCENT
    assert rules["boss_loss_percent"] == idlerpg.BOSS_LOSS_PERCENT


def test_public_player_record_does_not_expose_user_jid():
    player = idlerpg._normalize_player(
        "alice@example.org",
        {
            "jid": "alice@example.org",
            "name": "Alice",
            "class": "sysadmin",
            "level": 3,
            "next": 42,
        },
    )

    record = idlerpg._player_public_record("room@conf", "alice@example.org", player, rank=1)
    payload = json.dumps(record, sort_keys=True)

    assert "alice@example.org" not in payload
    assert record["name"] == "Alice"
    assert record["character"] == "Alice"


def test_public_events_redact_private_jids_from_text_players_and_data():
    room = {"events": []}

    idlerpg._record_event(
        room,
        "debug",
        "alice@example.org defeated bob@example.org",
        players=["Alice", "alice@example.org"],
        data={
            "actor_jid": "alice@example.org",
            "target_jid": "bob@example.org",
            "note": "seen by bob@example.org",
            "values": ["Alice", "alice@example.org", 7],
        },
    )

    event = idlerpg._room_events(room)[0]
    payload = json.dumps(event, sort_keys=True)

    assert "alice@example.org" not in payload
    assert "bob@example.org" not in payload
    assert event["players"] == ["Alice"]
    assert "actor_jid" not in event.get("data", {})
    assert "target_jid" not in event.get("data", {})
    assert "[redacted-jid]" in payload


def test_active_quest_export_omits_stale_private_jids(tmp_path):
    room = idlerpg._blank_room()
    room["players"] = {
        "alice@example.org": idlerpg._normalize_player(
            "alice@example.org",
            {
                "jid": "alice@example.org",
                "name": "Alice",
                "class": "sysadmin",
                "level": 42,
                "next": 123,
            },
        )
    }
    room["quest"] = {
        "active": True,
        "type": "time",
        "text": "defeat the stale JID leak",
        "started_at": 100,
        "complete_at": 200,
        "questers": ["alice@example.org", "stale@example.org"],
        "route": [],
        "route_index": 0,
    }

    _summary, payload = idlerpg._export_room_state(tmp_path, "room@conf", room, 1234)
    exported = json.dumps(payload, sort_keys=True)

    assert payload["quest"]["questers"] == ["Alice"]
    assert "alice@example.org" not in exported
    assert "stale@example.org" not in exported


def test_website_public_base_url_is_exported_by_config_module():
    from plugins.idlerpg import config as idlerpg_config

    assert "WEBSITE_PUBLIC_BASE_URL" in idlerpg_config.__all__
    assert hasattr(idlerpg_config, "WEBSITE_PUBLIC_BASE_URL")
