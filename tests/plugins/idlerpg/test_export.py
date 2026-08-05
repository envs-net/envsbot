import json
import os
import stat

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
    assert rules["export_interval_seconds"] == idlerpg.EXPORT_INTERVAL_SECONDS
    assert rules["export_full_season_events"] == idlerpg.EXPORT_FULL_SEASON_EVENTS
    assert rules["quest_max_per_day"] == idlerpg.QUEST_MAX_PER_DAY
    assert rules["quest_grid_min_points"] == idlerpg.QUEST_GRID_MIN_POINTS
    assert rules["quest_grid_max_points"] == idlerpg.QUEST_GRID_MAX_POINTS
    assert rules["count_command_messages"] == idlerpg.COUNT_COMMAND_MESSAGES
    assert rules["battle_win_min_percent"] == idlerpg.BATTLE_WIN_MIN_PERCENT
    assert rules["battle_loss_min_percent"] == idlerpg.BATTLE_LOSS_MIN_PERCENT
    assert rules["critical_min_percent"] == idlerpg.CRITICAL_MIN_PERCENT
    assert rules["critical_max_percent"] == idlerpg.CRITICAL_MAX_PERCENT
    assert rules["godsend_min_percent"] == idlerpg.GODSEND_MIN_PERCENT
    assert rules["godsend_max_percent"] == idlerpg.GODSEND_MAX_PERCENT
    assert rules["calamity_min_percent"] == idlerpg.CALAMITY_MIN_PERCENT
    assert rules["calamity_max_percent"] == idlerpg.CALAMITY_MAX_PERCENT
    assert rules["alignment_bonus_percent"] == idlerpg.ALIGNMENT_BONUS_PERCENT
    assert rules["quest_reward_percent"] == idlerpg.QUEST_REWARD_PERCENT
    assert rules["team_battle_percent"] == idlerpg.TEAM_BATTLE_PERCENT
    assert rules["unique_bonus_cap_percent"] == idlerpg.UNIQUE_BONUS_CAP_PERCENT
    assert rules["alignment_item_power_factors"] == idlerpg.ALIGNMENT_ITEM_POWER_FACTORS


def test_public_artifact_catalog_covers_every_equipment_slot():
    catalog = idlerpg._public_artifact_catalog()

    assert len(catalog) == len(idlerpg.UNIQUE_ITEMS)
    assert {item["slot"] for item in catalog} == set(idlerpg.ITEMS)
    assert all(item["name"] for item in catalog)
    assert all(item["tier"] >= 1 for item in catalog)
    assert all(item["effective_min_level"] >= idlerpg.UNIQUE_ITEM_MIN_LEVEL for item in catalog)
    assert all(item["min_item_level"] <= item["max_item_level"] for item in catalog)
    assert all(item["bonus"] and item["bonus_percent"] > 0 for item in catalog)

    gloves = next(item for item in catalog if item["name"] == "The Gloves of Quiet Keystrokes")
    assert gloves == {
        "name": "The Gloves of Quiet Keystrokes",
        "slot": "pair of gloves",
        "tier": 1,
        "min_level": 35,
        "effective_min_level": 35,
        "min_item_level": 100,
        "max_item_level": 140,
        "next_upgrade_level": 75,
        "bonus": "message_penalty_reduction",
        "bonus_percent": 5,
    }


def test_atomic_export_is_web_readable_under_restrictive_umask(tmp_path):
    export_path = tmp_path / "room_at_conf" / "players.json"
    previous_umask = os.umask(0o077)
    try:
        idlerpg._atomic_write_json(export_path, {"players": []})
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(export_path.parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(export_path.stat().st_mode) == 0o644


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


def test_current_season_event_store_is_not_capped_by_recent_log(monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import formatting as idlerpg_formatting

    now = 1_000
    room = idlerpg._blank_room()
    room["season"] = {"id": "season-a", "started_at": now, "ends_at": 0}
    room["events"] = []
    room["season_events"] = []
    monkeypatch.setattr(idlerpg_config, "EVENT_LOG_LIMIT", 2)
    monkeypatch.setattr(idlerpg_config, "EVENT_RETENTION_DAYS", 0)

    for offset in range(4):
        monkeypatch.setattr(idlerpg_formatting, "_now", lambda value=now + offset: value)
        idlerpg._record_event(room, "game", f"event-{offset}")

    assert [event["text"] for event in room["events"]] == ["event-2", "event-3"]
    assert [event["text"] for event in room["season_events"]] == [
        "event-0",
        "event-1",
        "event-2",
        "event-3",
    ]
    assert [event["text"] for event in idlerpg._current_season_events(room)] == [
        "event-0",
        "event-1",
        "event-2",
        "event-3",
    ]


def test_room_bucket_migrates_retained_current_season_events():
    data = {
        "rooms": {
            "room@conf": {
                "players": {},
                "season": {"id": "season-a", "started_at": 200, "ends_at": 0},
                "events": [
                    {"ts": 100, "kind": "old", "text": "previous season"},
                    {"ts": 250, "kind": "game", "text": "current season"},
                ],
            }
        }
    }

    room = idlerpg._room_bucket(data, "room@conf")

    assert [event["text"] for event in room["season_events"]] == ["current season"]


def test_full_season_event_export_can_be_disabled_and_removes_stale_files(
    tmp_path,
    monkeypatch,
):
    from plugins.idlerpg import config as idlerpg_config

    room_jid = "room@conf"
    room = idlerpg._blank_room()
    room["season"] = {"id": "season-a", "started_at": 100, "ends_at": 0}
    room["events"] = [{"ts": 101, "kind": "game", "text": "recent"}]
    room["season_events"] = [
        {"ts": 100, "kind": "game", "text": "first"},
        {"ts": 101, "kind": "game", "text": "recent"},
    ]

    room_dir = tmp_path / "room_at_conf"
    room_dir.mkdir()
    (room_dir / "season_events.json").write_text("{}", encoding="utf-8")
    (tmp_path / "season_events.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(idlerpg_config, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_FULL_SEASON_EVENTS", False)

    idlerpg._export_public_state({"rooms": {room_jid: room}}, {room_jid: True})

    assert (room_dir / "events.json").exists()
    assert not (room_dir / "season_events.json").exists()
    assert not (tmp_path / "season_events.json").exists()

    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert "season_events_url" not in index["rooms"][0]

    room_payload = json.loads((room_dir / "room.json").read_text(encoding="utf-8"))
    assert room_payload["rules"]["export_full_season_events"] is False
    assert room_payload["season_events_total"] == 0


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
        "target": [12, 34],
    }

    _summary, payload = idlerpg._export_room_state(tmp_path, "room@conf", room, 1234)
    exported = json.dumps(payload, sort_keys=True)

    assert payload["quest"]["questers"] == ["Alice"]
    assert payload["quest"]["target"] == [12, 34]
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
        "season_events.json",
        "achievements.json",
        "artifacts.json",
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
        "season_events.json",
        "achievements.json",
        "artifacts.json",
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


@pytest.mark.asyncio
async def test_automatic_public_export_respects_independent_interval(monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import export as idlerpg_export
    from plugins.idlerpg import formatting as idlerpg_formatting
    from plugins.idlerpg import state as idlerpg_state

    now = 1_000
    calls = []

    async def enabled_rooms(_bot, room_jids=()):
        return {str(room): True for room in room_jids}

    def export_state(data, enabled):
        calls.append((data, enabled))

    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_INTERVAL_SECONDS", 300)
    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: now)
    monkeypatch.setattr(idlerpg_state, "_enabled_rooms", enabled_rooms)
    monkeypatch.setattr(idlerpg_export, "_export_public_state", export_state)
    idlerpg_state._reset_public_export_schedule()

    data = {"rooms": {"room@conf": idlerpg._blank_room()}}
    assert await idlerpg_state._refresh_public_export(DummyBot(), data, force=False) is True
    assert len(calls) == 1

    now = 1_299
    assert await idlerpg_state._refresh_public_export(DummyBot(), data, force=False) is False
    assert len(calls) == 1

    now = 1_300
    assert await idlerpg_state._refresh_public_export(DummyBot(), data, force=False) is True
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_forced_public_export_bypasses_interval(monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import export as idlerpg_export
    from plugins.idlerpg import formatting as idlerpg_formatting
    from plugins.idlerpg import state as idlerpg_state

    calls = []

    async def enabled_rooms(_bot, room_jids=()):
        return {str(room): True for room in room_jids}

    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_INTERVAL_SECONDS", 300)
    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: 2_000)
    monkeypatch.setattr(idlerpg_state, "_enabled_rooms", enabled_rooms)
    monkeypatch.setattr(idlerpg_export, "_export_public_state", lambda data, enabled: calls.append((data, enabled)))
    idlerpg_state._reset_public_export_schedule()

    data = {"rooms": {"room@conf": idlerpg._blank_room()}}
    assert await idlerpg_state._refresh_public_export(DummyBot(), data, force=False) is True
    assert await idlerpg_state._refresh_public_export(DummyBot(), data, force=False) is False
    assert await idlerpg_state._refresh_public_export(DummyBot(), data, force=True) is True
    assert len(calls) == 2
