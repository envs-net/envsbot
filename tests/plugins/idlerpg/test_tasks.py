import asyncio
import copy

from .helpers import (
    DummyBot,
    DummyMsg,
    DummyTask,
    JOINED_ROOMS,
    idlerpg,
    pytest,
)
import random
from core_plugins import _core
from plugins.idlerpg import config as idlerpg_config
from plugins.idlerpg import events as idlerpg_events
from plugins.idlerpg import export as idlerpg_export
from plugins.idlerpg import formatting as idlerpg_formatting
from plugins.idlerpg import state as idlerpg_state
from plugins.idlerpg import tasks as idlerpg_tasks
from utils.task_supervisor import TaskSupervisor


@pytest.mark.asyncio
async def test_enabled_rooms_and_task_sync_lifecycle(monkeypatch):
    bot = DummyBot()
    bot.store.globals[idlerpg.IDLERPG_ENABLED_KEY] = {
        "room@conf": True,
        "off@conf": False,
        123: True,
    }
    ensured: list[str] = []
    cancelled: list[str] = []

    async def fake_ensure(_bot, room_jid):
        ensured.append(room_jid)
        idlerpg.ROOM_TASKS[room_jid] = DummyTask(name=room_jid)
        return idlerpg.ROOM_TASKS[room_jid]

    async def fake_cancel(room_jid):
        cancelled.append(room_jid)
        idlerpg.ROOM_TASKS.pop(room_jid, None)

    monkeypatch.setattr(idlerpg_tasks, "_ensure_game_task", fake_ensure)
    monkeypatch.setattr(idlerpg_tasks, "_cancel_room_task", fake_cancel)

    assert await idlerpg._enabled_rooms(bot) == {"room@conf": True}
    await idlerpg._start_enabled_room_tasks(bot)
    assert ensured == ["room@conf"]

    idlerpg.ROOM_TASKS["old@conf"] = DummyTask(name="old")
    ensured.clear()
    await idlerpg._sync_tasks_to_enabled_rooms(bot)
    assert ensured == ["room@conf"]
    assert cancelled == ["old@conf"]

    bot.store.globals[idlerpg.IDLERPG_ENABLED_KEY] = "broken"
    assert await idlerpg._enabled_rooms(bot) == {}

    bot.store.globals[idlerpg.IDLERPG_ENABLED_KEY] = None
    assert await idlerpg._enabled_rooms(bot) == {}


@pytest.mark.asyncio
async def test_ensure_game_task_cleans_duplicate_supervised_room_tasks():
    bot = DummyBot()
    bot.tasks = TaskSupervisor()

    def create_task(plugin, coro, name=None):
        return bot.tasks.create(plugin, coro, name=name)

    bot.bot_plugins.create_task = create_task

    async def legacy_loop():
        await asyncio.sleep(3600)

    legacy = bot.tasks.create(
        idlerpg.PLUGIN_NAME,
        legacy_loop(),
        name="idlerpg-room@conf",
    )

    task = await idlerpg._ensure_game_task(bot, "room@conf")
    snapshot = bot.tasks.snapshot()

    assert legacy.cancelled()
    assert idlerpg.ROOM_TASKS["room@conf"] is task
    assert [(item.plugin, item.name, item.status) for item in snapshot] == [
        (idlerpg.PLUGIN_NAME, "room@conf", "running")
    ]

    await idlerpg._ensure_game_task(bot, "room@conf")
    assert [(item.plugin, item.name, item.status) for item in bot.tasks.snapshot()] == [
        (idlerpg.PLUGIN_NAME, "room@conf", "running")
    ]
    await idlerpg._cancel_room_task("room@conf")


@pytest.mark.asyncio
async def test_ensure_game_task_serializes_concurrent_start(monkeypatch):
    bot = DummyBot()
    bot.tasks = TaskSupervisor()

    def create_task(plugin, coro, name=None):
        return bot.tasks.create(plugin, coro, name=name)

    bot.bot_plugins.create_task = create_task
    checkpoint_calls = 0

    async def slow_checkpoint(_bot, _room_jid, *, flush=False):
        nonlocal checkpoint_calls
        checkpoint_calls += 1
        await asyncio.sleep(0.01)
        return 0

    monkeypatch.setattr(idlerpg_tasks, "_checkpoint_room_clock", slow_checkpoint)

    first, second = await asyncio.gather(
        idlerpg._ensure_game_task(bot, "room@conf"),
        idlerpg._ensure_game_task(bot, "room@conf"),
    )

    assert first is second
    assert checkpoint_calls == 1
    assert [(item.plugin, item.name, item.status) for item in bot.tasks.snapshot()] == [
        (idlerpg.PLUGIN_NAME, "room@conf", "running")
    ]

    await idlerpg._cancel_room_task("room@conf")


@pytest.mark.asyncio
async def test_tick_room_serializes_concurrent_announcements(monkeypatch):
    class CopyingStore(type(DummyBot().store)):
        async def get_global(self, key, default=None):
            return copy.deepcopy(self.globals.get(key, default))

        async def set_global(self, key, value):
            await asyncio.sleep(0)
            self.globals[key] = copy.deepcopy(value)

    bot = DummyBot()
    bot.store = CopyingStore()
    now = 3_000_000
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {
            "name": "Alice",
            "class": "sysadmin",
            "level": 0,
            "next": 60,
            "idled": 0,
            "x": 1,
            "y": 1,
        },
    )
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = {
        "rooms": {
            "room@conf": {
                "players": {"alice@envs.net": player},
                "last_tick": now - 60,
                "next_top_announce_at": now + 3600,
                "next_topic_update_at": now + 3600,
                "events": [],
            }
        }
    }

    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: now)
    monkeypatch.setattr(random, "random", lambda: 1.0)
    monkeypatch.setattr(idlerpg_export, "_export_public_state", lambda _data, _enabled_rooms=None: None)

    await asyncio.gather(
        idlerpg._tick_room(bot, "room@conf", announce=True),
        idlerpg._tick_room(bot, "room@conf", announce=True),
    )

    replies = [text for text, _kwargs in bot.replies if "has reached level" in text]
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    stored_player = room["players"]["alice@envs.net"]

    assert replies == [
        "🏆 Alice has reached level 1! Next level in 0 days, 00:11:36."
    ]
    assert stored_player["level"] == 1
    assert stored_player["idled"] == 60
    assert room["last_tick"] == now
    assert len(room["events"]) == 1


@pytest.mark.asyncio
async def test_tick_announces_new_achievements(monkeypatch):
    bot = DummyBot()
    now = 5_000_000
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {
            "name": "Alice",
            "class": "sysadmin",
            "level": 9,
            "next": 60,
            "idled": 0,
            "created_at": now - 86400,
            "x": 1,
            "y": 1,
        },
    )
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = {
        "rooms": {
            "room@conf": {
                "players": {"alice@envs.net": player},
                "last_tick": now - 60,
                "next_top_announce_at": now + 3600,
                "next_topic_update_at": now + 3600,
                "events": [],
            }
        }
    }

    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: now)
    monkeypatch.setattr(idlerpg_config, "ITEM_CHANCE", 0.0)
    monkeypatch.setattr(idlerpg_config, "GRID_BATTLE_ENABLED", False)
    monkeypatch.setattr(idlerpg_config, "EVENT_CHANCE", 0.0)
    monkeypatch.setattr(random, "random", lambda: 1.0)
    monkeypatch.setattr(idlerpg_export, "_export_public_state", lambda _data, _enabled_rooms=None: None)

    await idlerpg._tick_room(bot, "room@conf", announce=True)

    replies = [text for text, _kwargs in bot.replies]
    assert any("has reached level 10" in text for text in replies)
    assert any("unlocked achievement: Novice Idler" in text for text in replies)
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    assert any("Novice Idler" in event["text"] for event in room["events"])


@pytest.mark.asyncio
async def test_boss_achievement_is_announced_and_recorded_once(monkeypatch):
    bot = DummyBot()
    now = 6_000_000
    players = {}
    for index, name in enumerate(("Alice", "Bob", "Carol")):
        jid = f"{name.lower()}@envs.net"
        player = idlerpg._normalize_player(
            jid,
            {
                "name": name,
                "class": "idler",
                "level": idlerpg.BOSS_MIN_LEVEL,
                "next": 10_000,
                "items": {"weapon": 50},
                "achievements": [] if name == "Alice" else ["boss_slayer"],
                "x": index,
                "y": index,
            },
        )
        players[jid] = player
        JOINED_ROOMS["room@conf"]["nicks"][name] = {
            "jid": jid,
            "affiliation": "member",
        }

    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = {
        "rooms": {
            "room@conf": {
                "players": players,
                "last_tick": now - 60,
                "next_top_announce_at": now + 3600,
                "next_topic_update_at": now + 3600,
                "quest": {"active": False, "next_at": now + 3600},
                "events": [],
            }
        }
    }

    async def run_boss(room, _room_jid, messages):
        idlerpg_events._run_boss_event(
            list(room["players"].items()),
            messages,
            room,
        )

    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: now)
    monkeypatch.setattr(idlerpg_config, "ITEM_CHANCE", 0.0)
    monkeypatch.setattr(idlerpg_config, "GRID_BATTLE_ENABLED", False)
    monkeypatch.setattr(idlerpg_events, "_maybe_run_random_event", run_boss)
    monkeypatch.setattr(idlerpg_events.random, "sample", lambda seq, count: list(seq)[:count])
    monkeypatch.setattr(idlerpg_events.random, "uniform", lambda _start, _stop: 1.0)
    rolls = iter([10_000, 0])
    monkeypatch.setattr(idlerpg_events.random, "randint", lambda _start, _stop: next(rolls))
    monkeypatch.setattr(idlerpg_events.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(idlerpg_export, "_export_public_state", lambda _data, _enabled_rooms=None: None)

    await idlerpg._tick_room(bot, "room@conf", announce=True)

    announcement = "🏅 Alice unlocked achievement: Boss Slayer — helped defeat a room boss."
    replies = [text for text, _kwargs in bot.replies]
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]

    assert replies.count(announcement) == 1
    assert [event["text"] for event in room["events"]].count(announcement) == 1
    assert "boss_slayer" in room["players"]["alice@envs.net"]["achievements"]


@pytest.mark.asyncio
async def test_level_up_triggers_original_level_battle(monkeypatch):
    bot = DummyBot()
    now = 4_000_000
    alice = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "level": 24, "next": 60, "x": 1, "y": 1},
    )
    bob = idlerpg._normalize_player(
        "bob@envs.net",
        {"name": "Bob", "level": 24, "next": 1000, "x": 2, "y": 2},
    )
    JOINED_ROOMS["room@conf"]["nicks"]["Bob"] = {"jid": "bob@envs.net"}
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = {
        "rooms": {
            "room@conf": {
                "players": {"alice@envs.net": alice, "bob@envs.net": bob},
                "last_tick": now - 60,
                "next_top_announce_at": now + 3600,
                "next_topic_update_at": now + 3600,
                "events": [],
            }
        }
    }

    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: now)
    monkeypatch.setattr(idlerpg_config, "ITEM_CHANCE", 0.0)
    monkeypatch.setattr(idlerpg_config, "GRID_BATTLE_ENABLED", False)
    monkeypatch.setattr(idlerpg_config, "EVENT_CHANCE", 0.0)
    monkeypatch.setattr(idlerpg_config, "LEVEL_BATTLE_CHANCE_AT_25", 1.0)
    monkeypatch.setattr(random, "random", lambda: 0.99)
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    rolls = iter([9999, 0])
    monkeypatch.setattr(random, "randint", lambda _start, _stop: next(rolls))
    monkeypatch.setattr(idlerpg_export, "_export_public_state", lambda _data, _enabled_rooms=None: None)

    await idlerpg._tick_room(bot, "room@conf", announce=False)

    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    assert room["players"]["alice@envs.net"]["level"] == 25
    assert any("has challenged Bob" in event["text"] for event in room["events"])


def test_room_jid_from_task_name_ignores_topic_tasks():
    assert idlerpg._room_jid_from_task_name("idlerpg-room@conf") == "room@conf"
    assert idlerpg._room_jid_from_task_name("room@conf") == "room@conf"
    assert idlerpg._room_jid_from_task_name("idlerpg-topic-room@conf") is None
    assert idlerpg._room_jid_from_task_name("idlerpg-index") is None


@pytest.mark.asyncio
async def test_ready_restart_unload_delegate_to_task_helpers(monkeypatch):
    bot = DummyBot()
    started = 0
    refreshed = 0
    cancelled: list[str] = []

    async def fake_start(_bot):
        nonlocal started
        started += 1

    async def fake_refresh(_bot, _data=None, **_kwargs):
        nonlocal refreshed
        refreshed += 1

    async def fake_cancel(room_jid):
        cancelled.append(room_jid)
        idlerpg.ROOM_TASKS.pop(room_jid, None)

    monkeypatch.setattr(idlerpg_tasks, "_start_enabled_room_tasks", fake_start)
    monkeypatch.setattr(idlerpg_tasks, "_cancel_room_task", fake_cancel)
    monkeypatch.setattr(idlerpg_state, "_refresh_public_export", fake_refresh)

    await idlerpg.on_ready(bot)
    assert started == 1
    assert refreshed == 1

    idlerpg.ROOM_TASKS["a@conf"] = DummyTask(name="a")
    idlerpg.ROOM_TASKS["b@conf"] = DummyTask(name="b")
    await idlerpg.restart_tasks(bot)
    assert set(cancelled) == {"a@conf", "b@conf"}
    assert len(cancelled) == 2
    assert started == 2
    assert refreshed == 2

    idlerpg.ROOM_TASKS["c@conf"] = DummyTask(name="c")
    await idlerpg.on_unload(bot)
    assert cancelled[-1] == "c@conf"


@pytest.mark.asyncio
async def test_on_muc_presence_starts_task_only_when_enabled(monkeypatch):
    bot = DummyBot()
    pres = DummyMsg(bare="room@conf", resource="Alice")
    ensured: list[str] = []

    async def fake_enabled(_bot, _key, _plugin, room_jid):
        return room_jid == "room@conf"

    async def fake_ensure(_bot, room_jid):
        ensured.append(room_jid)
        return DummyTask(name=room_jid)

    monkeypatch.setattr(_core, "_is_enabled_for_room", fake_enabled)
    monkeypatch.setattr(idlerpg_tasks, "_ensure_game_task", fake_ensure)

    await idlerpg.on_muc_presence(bot, pres)
    assert ensured == ["room@conf"]

    await idlerpg.on_muc_presence(bot, DummyMsg(bare="other@conf", resource="Alice"))
    assert ensured == ["room@conf"]

    async def raising_enabled(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(_core, "_is_enabled_for_room", raising_enabled)
    await idlerpg.on_muc_presence(bot, pres)
    assert ensured == ["room@conf"]


@pytest.mark.asyncio
async def test_task_start_checkpoints_room_clock_without_catchup(monkeypatch):
    bot = DummyBot()
    now = 2_000_000
    player = idlerpg._normalize_player(
        "alice@envs.net",
        {"name": "Alice", "class": "sysadmin", "next": 1000, "idled": 0},
    )
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = {
        "rooms": {
            "room@conf": {
                "players": {"alice@envs.net": player},
                "last_tick": now - 3600,
            }
        }
    }

    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: now)
    monkeypatch.setattr(
        idlerpg_tasks,
        "create_plugin_task",
        lambda _bot, _plugin, coro, name=None: DummyTask(coro, name),
    )

    task = await idlerpg._ensure_game_task(bot, "room@conf")

    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    assert isinstance(task, DummyTask)
    assert room["last_tick"] == now
    assert room["last_task_checkpoint_at"] == now
    assert room["players"]["alice@envs.net"]["idled"] == 0
    assert room["players"]["alice@envs.net"]["next"] == 1000
    assert bot.flush_count == 1


@pytest.mark.asyncio
async def test_on_unload_checkpoints_active_room_and_flushes(monkeypatch):
    bot = DummyBot()
    now = 2_100_000
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = {
        "rooms": {"room@conf": {"players": {}, "last_tick": now - 120}}
    }
    idlerpg.ROOM_TASKS["room@conf"] = DummyTask(name="room@conf")
    monkeypatch.setattr(idlerpg_formatting, "_now", lambda: now)

    await idlerpg.on_unload(bot)

    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    assert room["last_tick"] == now
    assert room["last_task_checkpoint_at"] == now
    assert "room@conf" not in idlerpg.ROOM_TASKS
    assert bot.flush_count == 1
