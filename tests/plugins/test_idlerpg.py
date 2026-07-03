import types

import pytest

import plugins.idlerpg as idlerpg
from core_plugins.rooms import JOINED_ROOMS
from utils.command import Role


class DummyStore:
    def __init__(self):
        self.globals = {idlerpg.IDLERPG_ENABLED_KEY: {"room@conf": True}}

    async def get_global(self, key, default=None):
        return self.globals.get(key, default)

    async def set_global(self, key, value):
        self.globals[key] = value


class DummyBot:
    def __init__(self):
        self.store = DummyStore()
        self.db = types.SimpleNamespace(
            users=types.SimpleNamespace(plugin=lambda name: self.store)
        )
        self.replies = []
        self.reply = lambda msg, text, **kwargs: self.replies.append((text, kwargs))
        self.prefix = ","
        self.boundjid = types.SimpleNamespace(bare="bot@envs.net")
        self.plugin = {"xep_0045": object()}
        self.presence = types.SimpleNamespace(joined_rooms={"room@conf": "envsbot"})
        self.bot_plugins = types.SimpleNamespace(register_event=lambda *a, **k: None)
        self.audit_events = []
        self.tasks = types.SimpleNamespace(
            create=lambda plugin, coro, name=None: DummyTask(coro, name)
        )

    async def get_user_role(self, jid, room=None):
        if str(jid).startswith("mod@"):
            return Role.MODERATOR
        return Role.USER

    async def audit(self, event, actor=None, target=None, details=None):
        self.audit_events.append((event, actor, target, details or {}))


class DummyTask:
    def __init__(self, coro=None, name=None):
        self.coro = coro
        self.name = name
        self.cancelled = False
        if coro is not None:
            coro.close()

    def done(self):
        return False

    def cancel(self):
        self.cancelled = True

    def __await__(self):
        async def _done():
            return None
        return _done().__await__()


class DummyMsg:
    def __init__(self, body=",idlerpg", bare="room@conf", resource="Alice", mtype="groupchat"):
        self.data = {
            "from": types.SimpleNamespace(bare=bare, resource=resource),
            "to": types.SimpleNamespace(bare="bot@envs.net"),
            "type": mtype,
            "body": body,
            "mucnick": resource,
        }

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)


@pytest.fixture(autouse=True)
def clear_idlerpg_state():
    idlerpg.ROOM_TASKS.clear()
    JOINED_ROOMS.clear()
    idlerpg._core.JOINED_ROOMS = JOINED_ROOMS
    JOINED_ROOMS["room@conf"] = {
        "nicks": {
            "Alice": {"jid": "alice@envs.net", "affiliation": "member"},
            "Mod": {"jid": "mod@envs.net", "affiliation": "admin"},
        }
    }
    yield
    idlerpg.ROOM_TASKS.clear()
    JOINED_ROOMS.clear()


@pytest.mark.asyncio
async def test_register_status_and_lists():
    bot = DummyBot()
    msg = DummyMsg()

    await idlerpg.idlerpg_command(
        bot,
        "alice@envs.net",
        "Alice",
        ["register", "Alice", "sysadmin"],
        msg,
        True,
    )
    assert "Welcome Alice" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["status"], msg, True)
    assert "level 0 sysadmin" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["top"], msg, True)
    assert "IdleRPG Top Players" in bot.replies[-1][0]

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["players"], msg, True)
    assert "Alice" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_message_penalty_and_logout_login(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        msg,
        True,
    )

    before = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]["players"]["alice@envs.net"]["next"]
    await idlerpg.on_message(bot, DummyMsg(body="hello world"))
    after = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]["players"]["alice@envs.net"]["next"]
    assert after > before

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["logout"], msg, True)
    player = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]["players"]["alice@envs.net"]
    assert player["logged_out"] is True

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["login"], msg, True)
    assert player["logged_out"] is False


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


@pytest.mark.asyncio
async def test_admin_push_setlevel_reset_delete():
    bot = DummyBot()
    msg = DummyMsg(resource="Mod")
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        DummyMsg(),
        True,
    )

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["setlevel", "Alice", "5"], msg, True)
    room = bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]["room@conf"]
    assert room["players"]["alice@envs.net"]["level"] == 5

    before = room["players"]["alice@envs.net"]["next"]
    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["push", "Alice", "1m"], msg, True)
    assert room["players"]["alice@envs.net"]["next"] < before

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["reset", "Alice"], msg, True)
    assert room["players"]["alice@envs.net"]["level"] == 0

    await idlerpg.idlerpg_command(bot, "mod@envs.net", "Mod", ["delete", "Alice"], msg, True)
    assert "alice@envs.net" not in room["players"]


@pytest.mark.asyncio
async def test_quest_and_runtime_state(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    data = {"rooms": {"room@conf": {"players": {}, "name_index": {}, "quest": {"active": False, "next_at": idlerpg._now()}, "last_tick": idlerpg._now()}}}
    room = data["rooms"]["room@conf"]
    for idx in range(4):
        jid = f"u{idx}@envs.net"
        room["players"][jid] = idlerpg._normalize_player(jid, {"name": f"U{idx}", "class": "idler", "level": 40, "next": 100})
        JOINED_ROOMS["room@conf"]["nicks"][f"U{idx}"] = {"jid": jid, "affiliation": "member"}
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = data
    monkeypatch.setattr(idlerpg.random, "choice", lambda seq: seq[0])

    await idlerpg._maybe_run_quest(room, "room@conf", messages := [])
    assert room["quest"]["active"] is True
    assert messages

    state = await idlerpg.get_runtime_state(bot, "room@conf")
    assert state["players"] == 4
    assert state["active_quests"] == 1

    await idlerpg.idlerpg_command(bot, "alice@envs.net", "Alice", ["quest"], msg, True)
    assert "are on a quest" in bot.replies[-1][0]


@pytest.mark.asyncio
async def test_cleanup_room_state_removes_data_and_task():
    bot = DummyBot()
    bot.store.globals[idlerpg.IDLERPG_DATA_KEY] = {"rooms": {"room@conf": idlerpg._blank_room()}}
    idlerpg.ROOM_TASKS["room@conf"] = DummyTask()

    await idlerpg.cleanup_room_state(bot, "room@conf")

    assert "room@conf" not in bot.store.globals[idlerpg.IDLERPG_DATA_KEY]["rooms"]
    assert "room@conf" not in idlerpg.ROOM_TASKS
