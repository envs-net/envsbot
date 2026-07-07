from .helpers import (
    DummyBot,
    DummyMsg,
    DummyTask,
    idlerpg,
    pytest,
)


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
    assert ensured == ["room@conf", "123"]

    idlerpg.ROOM_TASKS["old@conf"] = DummyTask(name="old")
    ensured.clear()
    await idlerpg._sync_tasks_to_enabled_rooms(bot)
    assert ensured == ["123", "room@conf"]
    assert cancelled == ["old@conf"]

    bot.store.globals[idlerpg.IDLERPG_ENABLED_KEY] = "broken"
    assert await idlerpg._enabled_rooms(bot) == {}


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
    assert cancelled == ["a@conf", "b@conf"]
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
