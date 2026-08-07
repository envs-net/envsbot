import asyncio
import json
import os
import stat
import threading
import time

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
    assert rules["export_season_event_chunk_size"] == idlerpg.EXPORT_SEASON_EVENT_CHUNK_SIZE
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


def test_record_event_keeps_only_bounded_recent_history_in_memory(monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import formatting as idlerpg_formatting

    now = 1_000
    room = idlerpg._blank_room()
    room["season"] = {"id": "season-a", "started_at": now, "ends_at": 0}
    room["events"] = []
    monkeypatch.setattr(idlerpg_config, "EVENT_LOG_LIMIT", 2)
    monkeypatch.setattr(idlerpg_config, "EVENT_RETENTION_DAYS", 0)

    for offset in range(4):
        monkeypatch.setattr(idlerpg_formatting, "_now", lambda value=now + offset: value)
        idlerpg._record_event(room, "game", f"event-{offset}")

    assert [event["text"] for event in room["events"]] == ["event-2", "event-3"]
    assert "season_events" not in room
    assert [event["text"] for event in idlerpg._current_season_events(room)] == [
        "event-2",
        "event-3",
    ]


def test_room_bucket_does_not_create_full_season_event_cache():
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

    assert "season_events" not in room
    assert "season_events_started_at" not in room


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
    chunk_dir = room_dir / "season-events"
    chunk_dir.mkdir()
    (chunk_dir / "000001.json").write_text("{}", encoding="utf-8")
    (tmp_path / "season_events.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(idlerpg_config, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_FULL_SEASON_EVENTS", False)

    idlerpg._export_public_state({"rooms": {room_jid: room}}, {room_jid: True})

    assert (room_dir / "events.json").exists()
    assert not (room_dir / "season_events.json").exists()
    assert not (room_dir / "season-events").exists()
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


@pytest.mark.asyncio
async def test_normalized_store_migrates_legacy_blob_and_clears_it():
    from plugins.idlerpg import state as idlerpg_state

    class NormalizedStore:
        def __init__(self):
            self.saved = []

        async def load_state(self):
            return {"rooms": {}}

        async def save_state(self, data):
            self.saved.append(data)

    bot = DummyBot()
    normalized = NormalizedStore()
    bot.db.idlerpg = normalized
    legacy = {"rooms": {"room@conf": idlerpg._blank_room()}}
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = legacy

    loaded = await idlerpg_state._get_data(bot)

    assert loaded is legacy
    assert normalized.saved == [legacy]
    assert idlerpg.IDLERPG_DATA_KEY not in bot.store.globals
    assert bot.flush_count == 1
    assert await idlerpg_state._get_data(bot) is legacy


@pytest.mark.asyncio
async def test_public_export_runs_in_worker_thread_and_records_metrics(monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import export as idlerpg_export
    from plugins.idlerpg import state as idlerpg_state

    main_thread = threading.get_ident()
    worker_threads = []

    async def enabled_rooms(_bot, room_jids=()):
        return {str(room): True for room in room_jids}

    def export_state(_data, _enabled):
        worker_threads.append(threading.get_ident())
        return {
            "ok": True,
            "rooms": 1,
            "players": 2,
            "events": 3,
            "files": 4,
            "bytes": 5,
        }

    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_state, "_enabled_rooms", enabled_rooms)
    monkeypatch.setattr(idlerpg_export, "_export_public_state", export_state)
    idlerpg_state._reset_public_export_schedule()

    data = {"rooms": {"room@conf": idlerpg._blank_room()}}
    assert await idlerpg_state._refresh_public_export(
        DummyBot(), data, force=True
    ) is True

    assert worker_threads and worker_threads[0] != main_thread
    metrics = idlerpg_state._public_export_runtime()
    assert metrics["successes"] == 1
    assert metrics["failures"] == 0
    assert metrics["rooms"] == 1
    assert metrics["players"] == 2
    assert metrics["events"] == 3
    assert metrics["files"] == 4
    assert metrics["bytes"] == 5


@pytest.mark.asyncio
async def test_concurrent_automatic_exports_are_coalesced(monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import export as idlerpg_export
    from plugins.idlerpg import formatting as idlerpg_formatting
    from plugins.idlerpg import state as idlerpg_state

    calls = []

    async def enabled_rooms(_bot, room_jids=()):
        return {str(room): True for room in room_jids}

    def export_state(_data, _enabled):
        calls.append(1)
        time.sleep(0.05)
        return {"ok": True}

    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_INTERVAL_SECONDS", 300)
    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: 1_000)
    monkeypatch.setattr(idlerpg_state, "_enabled_rooms", enabled_rooms)
    monkeypatch.setattr(idlerpg_export, "_export_public_state", export_state)
    idlerpg_state._reset_public_export_schedule()

    data = {"rooms": {"room@conf": idlerpg._blank_room()}}
    first, second = await asyncio.gather(
        idlerpg_state._refresh_public_export(DummyBot(), data, force=False),
        idlerpg_state._refresh_public_export(DummyBot(), data, force=False),
    )

    assert sorted([first, second]) == [False, True]
    assert len(calls) == 1


def test_public_export_skips_semantically_unchanged_json(tmp_path, monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import export as idlerpg_export
    from plugins.idlerpg import formatting as idlerpg_formatting

    monkeypatch.setattr(idlerpg_config, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_FULL_SEASON_EVENTS", False)
    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: 1234)

    calls = []
    real_write = idlerpg_export._atomic_write_json

    def tracked_write(path, payload):
        calls.append(path)
        return real_write(path, payload)

    monkeypatch.setattr(idlerpg_export, "_atomic_write_json", tracked_write)
    data = {"rooms": {"room@conf": idlerpg._blank_room()}}

    first = idlerpg._export_public_state(data, {"room@conf": True})
    assert first["ok"] is True
    assert first["files_changed"] > 0
    assert calls

    calls.clear()
    second = idlerpg._export_public_state(data, {"room@conf": True})
    assert second["ok"] is True
    assert second["files_changed"] == 0
    assert second["files_skipped"] > 0
    assert second["files_deleted"] == 0
    assert calls == []


def test_public_export_prunes_stale_profile_as_delta(tmp_path, monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import formatting as idlerpg_formatting

    monkeypatch.setattr(idlerpg_config, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_FULL_SEASON_EVENTS", False)
    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: 1234)

    room = idlerpg._blank_room()
    room["players"] = {
        "alice@example.org": idlerpg._normalize_player(
            "alice@example.org",
            {"name": "Alice", "created_at": 100, "x": 1, "y": 2},
        )
    }
    data = {"rooms": {"room@conf": room}}
    first = idlerpg._export_public_state(data, {"room@conf": True})
    assert first["ok"] is True
    profile = tmp_path / idlerpg._room_slug("room@conf") / "profiles" / "Alice.json"
    assert profile.exists()

    room["players"] = {}
    second = idlerpg._export_public_state(data, {"room@conf": True})
    assert second["ok"] is True
    assert second["files_deleted"] >= 1
    assert not profile.exists()


@pytest.mark.asyncio
async def test_automatic_full_season_export_reuses_unchanged_sqlite_revision(monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import export as idlerpg_export
    from plugins.idlerpg import state as idlerpg_state

    room_jid = "room@conf"
    room = idlerpg._blank_room()
    room["season"] = {"id": "season-a", "started_at": 100, "ends_at": 0}
    data = {"rooms": {room_jid: room}}
    loads = []
    exports = []
    revision = [2, 22]

    class Normalized:
        async def load_state(self):
            return data

        async def save_state(self, _data, *, room_jids=None):
            return None

        async def season_event_revision(self, requested_room, started_at):
            assert requested_room == room_jid
            assert started_at == 100
            return tuple(revision)

        async def load_season_events(self, requested_room, started_at, *, after_rowid=0):
            loads.append((requested_room, started_at, after_rowid))
            if after_rowid > 0:
                return [
                    {
                        "ts": 130,
                        "kind": "game",
                        "text": "three",
                        "_storage_rowid": 23,
                    }
                ]
            return [
                {"ts": 110, "kind": "game", "text": "one", "_storage_rowid": 21},
                {"ts": 120, "kind": "game", "text": "two", "_storage_rowid": 22},
            ]

    async def enabled_rooms(_bot, room_jids=()):
        return {str(room): True for room in room_jids}

    def export_state(_data, _enabled, events, counts, append):
        exports.append((events, counts, append))
        return {"ok": True}

    bot = DummyBot()
    bot.db.idlerpg = Normalized()
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_FULL_SEASON_EVENTS", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(idlerpg_state, "_enabled_rooms", enabled_rooms)
    monkeypatch.setattr(idlerpg_export, "_export_public_state", export_state)
    idlerpg_state._reset_public_export_schedule()

    assert await idlerpg_state._refresh_public_export(bot, data, force=False) is True
    assert loads == [(room_jid, 100, 0)]
    assert exports[0][0][room_jid][1]["text"] == "two"
    assert exports[0][1] == {room_jid: 2}
    assert exports[0][2] == {room_jid: False}

    assert await idlerpg_state._refresh_public_export(bot, data, force=False) is True
    assert loads == [(room_jid, 100, 0)]
    assert exports[1][0] == {room_jid: None}
    assert exports[1][1] == {room_jid: 2}
    assert exports[1][2] == {room_jid: False}

    revision[:] = [3, 23]
    assert await idlerpg_state._refresh_public_export(bot, data, force=False) is True
    assert loads[-1] == (room_jid, 100, 22)
    assert exports[2][0][room_jid][0]["text"] == "three"
    assert exports[2][1] == {room_jid: 3}
    assert exports[2][2] == {room_jid: True}


def test_chunked_season_export_appends_without_rewriting_old_chunks(tmp_path, monkeypatch):
    from plugins.idlerpg import config as idlerpg_config

    room_jid = "room@conf"
    room = idlerpg._blank_room()
    room["season"] = {"id": "season-a", "started_at": 100, "ends_at": 0}
    monkeypatch.setattr(idlerpg_config, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_FULL_SEASON_EVENTS", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_SEASON_EVENT_CHUNK_SIZE", 2)

    full = [
        {"ts": 101, "kind": "game", "text": "one", "_storage_rowid": 11},
        {"ts": 102, "kind": "game", "text": "two", "_storage_rowid": 12},
        {"ts": 103, "kind": "game", "text": "three", "_storage_rowid": 13},
    ]
    first = idlerpg._export_public_state(
        {"rooms": {room_jid: room}},
        {room_jid: True},
        {room_jid: full},
        {room_jid: 3},
        {room_jid: False},
    )
    assert first["ok"] is True
    room_dir = tmp_path / "room_at_conf"
    chunk1 = room_dir / "season-events" / "000001.json"
    chunk2 = room_dir / "season-events" / "000002.json"
    before_chunk1 = chunk1.read_bytes()
    before_chunk2 = chunk2.read_bytes()

    delta = [
        {"ts": 104, "kind": "game", "text": "four", "_storage_rowid": 14},
        {"ts": 105, "kind": "game", "text": "five", "_storage_rowid": 15},
    ]
    second = idlerpg._export_public_state(
        {"rooms": {room_jid: room}},
        {room_jid: True},
        {room_jid: delta},
        {room_jid: 5},
        {room_jid: True},
    )
    assert second["ok"] is True
    assert chunk1.read_bytes() == before_chunk1
    assert chunk2.read_bytes() != before_chunk2
    chunk3 = room_dir / "season-events" / "000003.json"
    assert chunk3.exists()

    manifest = json.loads((room_dir / "season_events.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "chunked-v1"
    assert manifest["events_total"] == 5
    assert manifest["last_rowid"] == 15
    assert [chunk["events"] for chunk in manifest["chunks"]] == [2, 2, 1]
    assert second["files_skipped"] > 0


def _assert_generation_hashes(directory):
    import hashlib

    manifest = json.loads((directory / "generation.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "envsbot-generation-v1"
    assert len(manifest["generation_id"]) == 64
    assert manifest["files"]
    for relative, expected in manifest["files"].items():
        path = directory / relative
        assert path.is_file(), relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    return manifest


def test_delta_writer_bootstraps_generation_for_existing_legacy_tree(tmp_path):
    from plugins.idlerpg import export as idlerpg_export

    room_dir = tmp_path / "room_at_conf"
    room_dir.mkdir(parents=True)
    (tmp_path / "index.json").write_text('{"rooms": []}', encoding="utf-8")
    (room_dir / "room.json").write_text('{"room": "room@conf"}', encoding="utf-8")
    (room_dir / "players.json").write_text('{"players": []}', encoding="utf-8")

    idlerpg_export._DeltaExportWriter(tmp_path)

    root_manifest = _assert_generation_hashes(tmp_path)
    room_manifest = _assert_generation_hashes(room_dir)
    assert "index.json" in root_manifest["files"]
    assert "room_at_conf/room.json" in root_manifest["files"]
    assert set(room_manifest["files"]) == {"players.json", "room.json"}


def test_public_export_commits_root_and_room_generation_manifests(tmp_path, monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import formatting as idlerpg_formatting

    monkeypatch.setattr(idlerpg_config, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_FULL_SEASON_EVENTS", False)
    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: 1234)

    room_jid = "room@conf"
    room = idlerpg._blank_room()
    room["players"] = {
        "alice@example.org": idlerpg._normalize_player(
            "alice@example.org",
            {"name": "Alice", "created_at": 100, "x": 1, "y": 2},
        )
    }
    result = idlerpg._export_public_state(
        {"rooms": {room_jid: room}},
        {room_jid: True},
    )

    assert result["ok"] is True
    root_manifest = _assert_generation_hashes(tmp_path)
    room_dir = tmp_path / idlerpg._room_slug(room_jid)
    room_manifest = _assert_generation_hashes(room_dir)
    assert "index.json" in root_manifest["files"]
    assert "room.json" in room_manifest["files"]
    assert "profiles/Alice.json" in room_manifest["files"]


def test_delta_export_rewrites_corrupted_unchanged_file_before_commit(tmp_path, monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import formatting as idlerpg_formatting

    monkeypatch.setattr(idlerpg_config, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_FULL_SEASON_EVENTS", False)
    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: 1234)

    room_jid = "room@conf"
    room = idlerpg._blank_room()
    data = {"rooms": {room_jid: room}}
    first = idlerpg._export_public_state(data, {room_jid: True})
    assert first["ok"] is True

    room_dir = tmp_path / idlerpg._room_slug(room_jid)
    players_path = room_dir / "players.json"
    expected = players_path.read_bytes()
    players_path.write_text('{"corrupted": true}', encoding="utf-8")

    second = idlerpg._export_public_state(data, {room_jid: True})

    assert second["ok"] is True
    assert players_path.read_bytes() == expected
    assert second["files_changed"] >= 1
    _assert_generation_hashes(room_dir)


def test_generation_id_changes_only_when_export_content_changes(tmp_path, monkeypatch):
    from plugins.idlerpg import config as idlerpg_config
    from plugins.idlerpg import formatting as idlerpg_formatting

    monkeypatch.setattr(idlerpg_config, "EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(idlerpg_config, "EXPORT_ENABLED", True)
    monkeypatch.setattr(idlerpg_config, "EXPORT_FULL_SEASON_EVENTS", False)
    now = [1000]
    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: now[0])

    room_jid = "room@conf"
    room = idlerpg._blank_room()
    data = {"rooms": {room_jid: room}}
    idlerpg._export_public_state(data, {room_jid: True})
    room_dir = tmp_path / idlerpg._room_slug(room_jid)
    first = _assert_generation_hashes(room_dir)["generation_id"]

    now[0] = 2000
    idlerpg._export_public_state(data, {room_jid: True})
    second = _assert_generation_hashes(room_dir)["generation_id"]
    assert second == first

    room["players"]["alice@example.org"] = idlerpg._normalize_player(
        "alice@example.org",
        {"name": "Alice", "created_at": 100, "x": 1, "y": 2},
    )
    idlerpg._export_public_state(data, {room_jid: True})
    third = _assert_generation_hashes(room_dir)["generation_id"]
    assert third != second
