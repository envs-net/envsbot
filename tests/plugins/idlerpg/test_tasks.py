from .helpers import (
    DummyBot,
    DummyMsg,
    DummyTask,
    idlerpg,
    pytest,
)
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

    monkeypatch.setattr(idlerpg, "_ensure_game_task", fake_ensure)
    monkeypatch.setattr(idlerpg, "_cancel_room_task", fake_cancel)

    assert await idlerpg._enabled_rooms(bot) == {"room@conf": True, "off@conf": False, "123": True}
    await idlerpg._start_enabled_room_tasks(bot)
    assert set(ensured) == {"room@conf", "123"}
    assert len(ensured) == 2

    idlerpg.ROOM_TASKS["old@conf"] = DummyTask(name="old")
    ensured.clear()
    await idlerpg._sync_tasks_to_enabled_rooms(bot)
    assert set(ensured) == {"room@conf", "123"}
    assert len(ensured) == 2
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


def test_room_jid_from_task_name_ignores_topic_tasks():
    assert idlerpg._room_jid_from_task_name("idlerpg-room@conf") == "room@conf"
    assert idlerpg._room_jid_from_task_name("room@conf") == "room@conf"
    assert idlerpg._room_jid_from_task_name("idlerpg-topic-room@conf") is None
    assert idlerpg._room_jid_from_task_name("idlerpg-index") is None


@pytest.mark.asyncio
async def test_ready_restart_unload_delegate_to_task_helpers(monkeypatch):
    bot = DummyBot()
    started = 0
    cancelled: list[str] = []

    async def fake_start(_bot):
        nonlocal started
        started += 1

    async def fake_cancel(room_jid):
        cancelled.append(room_jid)
        idlerpg.ROOM_TASKS.pop(room_jid, None)

    monkeypatch.setattr(idlerpg, "_start_enabled_room_tasks", fake_start)
    monkeypatch.setattr(idlerpg, "_cancel_room_task", fake_cancel)

    await idlerpg.on_ready(bot)
    assert started == 1

    idlerpg.ROOM_TASKS["a@conf"] = DummyTask(name="a")
    idlerpg.ROOM_TASKS["b@conf"] = DummyTask(name="b")
    await idlerpg.restart_tasks(bot)
    assert set(cancelled) == {"a@conf", "b@conf"}
    assert len(cancelled) == 2
    assert started == 2

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

    monkeypatch.setattr(idlerpg._core, "_is_enabled_for_room", fake_enabled)
    monkeypatch.setattr(idlerpg, "_ensure_game_task", fake_ensure)

    await idlerpg.on_muc_presence(bot, pres)
    assert ensured == ["room@conf"]

    await idlerpg.on_muc_presence(bot, DummyMsg(bare="other@conf", resource="Alice"))
    assert ensured == ["room@conf"]

    async def raising_enabled(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(idlerpg._core, "_is_enabled_for_room", raising_enabled)
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

    monkeypatch.setattr(idlerpg, "_now", lambda: now)
    monkeypatch.setattr(
        idlerpg,
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
    monkeypatch.setattr(idlerpg, "_now", lambda: now)

    await idlerpg.on_unload(bot)

    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    assert room["last_tick"] == now
    assert room["last_task_checkpoint_at"] == now
    assert "room@conf" not in idlerpg.ROOM_TASKS
    assert bot.flush_count == 1
