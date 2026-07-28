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


def test_public_export_removes_disabled_room_directory(tmp_path, monkeypatch):
    from plugins.idlerpg import config as idlerpg_config

    monkeypatch.setattr(idlerpg_config, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    active_jid = "idlerpg@conference.envs.net"
    disabled_jid = "lounge@conference.envs.net"
    active_slug = idlerpg._room_slug(active_jid)
    disabled_slug = idlerpg._room_slug(disabled_jid)
    data = {
        "rooms": {
            active_jid: idlerpg._blank_room(),
            disabled_jid: idlerpg._blank_room(),
        }
    }

    idlerpg._export_public_state(data)
    assert (tmp_path / active_slug).is_dir()
    assert (tmp_path / disabled_slug).is_dir()

    idlerpg._export_public_state(
        data,
        {active_jid: True, disabled_jid: False},
    )

    assert (tmp_path / active_slug).is_dir()
    assert not (tmp_path / disabled_slug).exists()
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert [entry["room"] for entry in index["rooms"]] == [active_jid]
    assert json.loads((tmp_path / "leaderboard.json").read_text(encoding="utf-8"))["room"] == active_jid


def test_public_export_cleans_stale_index_rooms_and_root_copies(tmp_path, monkeypatch):
    from plugins.idlerpg import config as idlerpg_config

    monkeypatch.setattr(idlerpg_config, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    stale_slug = "lounge_at_conference.envs.net"
    stale_dir = tmp_path / stale_slug
    stale_dir.mkdir()
    (stale_dir / "room.json").write_text("{}", encoding="utf-8")
    (tmp_path / "index.json").write_text(
        json.dumps({"rooms": [{"room": "lounge@conference.envs.net", "slug": stale_slug}]}),
        encoding="utf-8",
    )
    for filename in (
        "leaderboard.json",
        "map.json",
        "players.json",
        "hall_of_fame.json",
        "events.json",
        "achievements.json",
    ):
        (tmp_path / filename).write_text("{}", encoding="utf-8")
    unrelated = tmp_path / "assets"
    unrelated.mkdir()

    idlerpg._export_public_state({"rooms": {}}, {})

    assert not stale_dir.exists()
    assert unrelated.is_dir()
    assert json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))["rooms"] == []
    for filename in (
        "leaderboard.json",
        "map.json",
        "players.json",
        "hall_of_fame.json",
        "events.json",
        "achievements.json",
    ):
        assert not (tmp_path / filename).exists()


@pytest.mark.asyncio
async def test_refresh_public_export_uses_effective_enabled_rooms(tmp_path, monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import state as idlerpg_state

    monkeypatch.setattr(idlerpg_config, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    bot = DummyBot()
    active_jid = "room@conf"
    disabled_jid = "lounge@conf"
    bot.store.globals[idlerpg.IDLERPG_ENABLED_KEY] = {
        active_jid: True,
        disabled_jid: False,
    }
    data = {
        "rooms": {
            active_jid: idlerpg._blank_room(),
            disabled_jid: idlerpg._blank_room(),
        }
    }
    (tmp_path / idlerpg._room_slug(disabled_jid)).mkdir()

    await idlerpg_state._refresh_public_export(bot, data)

    assert (tmp_path / idlerpg._room_slug(active_jid)).is_dir()
    assert not (tmp_path / idlerpg._room_slug(disabled_jid)).exists()
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert [entry["room"] for entry in index["rooms"]] == [active_jid]
