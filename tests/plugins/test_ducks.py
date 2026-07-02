import pytest
import types
from unittest.mock import AsyncMock

import plugins.ducks as ducks


class DummyMsg:
    def __init__(self, bare="room@conf", resource="testnick", groupchat=True):
        self.from_ = types.SimpleNamespace(bare=bare, resource=resource)
        self.type = "groupchat" if groupchat else "chat"
        self.mucnick = resource

    def __getitem__(
        self, key): return self.from_ if key == "from" else self.type

    def get(self, key, default=None):
        if key == "from":
            return self.from_
        if key == "type":
            return self.type
        if key == "body":
            return "dummy body"
        if key == "mucnick":
            return self.mucnick
        return default


class DummyStore:
    def __init__(self, user_stats=None, global_index=None):
        self._globals = {}
        self._user = {}
        if user_stats:
            for jid, stats in user_stats.items():
                self._user[jid] = {"stats": stats}
        if global_index:
            self._globals[ducks.DUCKS_INDEX_KEY] = global_index

    async def get_global(
        self, key, default=None): return self._globals.get(key, default)

    async def set_global(self, key, value): self._globals[key] = value

    async def get(self, jid, field=None):
        if field:
            return self._user.get(jid, {}).get(field)
        return self._user.get(jid)

    async def set(self, jid, field, value): self._user.setdefault(
        jid, {})[field] = value


class DummyBot:
    def __init__(self, user_stats=None, global_index=None):
        self._replies = []
        self.ducks_store = DummyStore(user_stats, global_index)
        self.db = types.SimpleNamespace(users=types.SimpleNamespace(
            plugin=lambda name: self.ducks_store))
        self.reply = lambda msg, text, * \
            a, **k: self._replies.append((text, msg, k))
        self.presence = types.SimpleNamespace(joined_rooms={})
        self.bot_plugins = types.SimpleNamespace(
            register_event=lambda *a, **k: None)
        self.boundjid = "jid/testbot"
        self.plugin = {}


@pytest.fixture(autouse=True)
def clear_ducks_state():
    ducks.ACTIVE_DUCKS.clear()
    ducks.PENDING_DUCKS.clear()
    ducks.MESSAGE_COUNTS.clear()
    ducks.NEXT_DUCK_THRESHOLDS.clear()
    ducks.SPAWN_TASKS.clear()
    ducks.EXPIRE_TASKS.clear()
    yield
    ducks.ACTIVE_DUCKS.clear()
    ducks.PENDING_DUCKS.clear()
    ducks.MESSAGE_COUNTS.clear()
    ducks.NEXT_DUCK_THRESHOLDS.clear()
    ducks.SPAWN_TASKS.clear()
    ducks.EXPIRE_TASKS.clear()




def true_func(*a, **k):
    return True


def false_func(*a, **k):
    return False


async def true_async(*a, **k):
    return True


async def false_async(*a, **k):
    return False


async def fake_jid(*a, **k):
    return ("jid/alice", None, None)


async def ensure_user(*a, **k):
    return None

def patch_ducks(monkeypatch, **kw):
    for k, v in kw.items():
        monkeypatch.setattr(ducks, k, v)


@pytest.mark.asyncio
async def test_duck_command_handles_room_toggle(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    patch_ducks(
        monkeypatch,
        handle_room_toggle_command=true_async,
        _is_muc_pm=true_func,
        _is_enabled_for_room=true_async,
        _ensure_user_exists=ensure_user,
        get_real_jid=fake_jid,
    )
    args = ["off"]
    ducks.ACTIVE_DUCKS["room@conf"] = 123
    ducks.PENDING_DUCKS.add("room@conf")

    class CancelObj:
        called = False
        def cancel(self): type(self).called = True
    c1 = CancelObj()
    c2 = CancelObj()
    ducks.SPAWN_TASKS["room@conf"] = c1
    ducks.EXPIRE_TASKS["room@conf"] = c2
    await ducks.duck_command(bot, "sender", "nick", args, msg, True)
    assert c1.called and c2.called


@pytest.mark.asyncio
async def test_duck_command_usage(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    patch_ducks(
        monkeypatch,
        handle_room_toggle_command=false_async,
        _is_muc_pm=false_func,
        _is_public_muc=true_func,
        _is_enabled_for_room=true_async,
    )
    await ducks.duck_command(bot, "jid", "nick", [], msg, True)
    assert any("usage" in t[0].lower() for t in bot._replies)


@pytest.mark.asyncio
async def test_duck_command_subcommands(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    room = msg.from_.bare
    patch_ducks(
        monkeypatch,
        handle_room_toggle_command=false_async,
        _is_muc_pm=false_func,
        _is_public_muc=true_func,
        _is_enabled_for_room=true_async,
        get_real_jid=fake_jid,
        _ensure_user_exists=ensure_user,
    )
    ducks.ACTIVE_DUCKS[room] = time0 = 1000.0
    import time as rtime
    monkeypatch.setattr(rtime, "time", lambda: time0 + 2)
    await ducks.duck_command(bot, "jid", "nick", ["befriend"], msg, True)
    assert any("befriend" in t[0].lower() for t in bot._replies)
    ducks.ACTIVE_DUCKS[room] = time0
    await ducks.duck_command(bot, "jid", "nick", ["trap"], msg, True)
    assert any("trap" in t[0].lower() for t in bot._replies)
    await ducks.duck_command(bot, "jid", "nick", ["foobar"], msg, True)
    assert any("unknown" in t[0].lower() for t in bot._replies)


@pytest.mark.asyncio
async def test_duck_command_friends_and_enemies(monkeypatch):
    global_index = {
        "room@conf": {"jid/alice": {"display_name": "Alice",
                                    "befriended": 2, "trapped": 3}}}
    bot = DummyBot(global_index=global_index)
    msg = DummyMsg()
    patch_ducks(
        monkeypatch,
        handle_room_toggle_command=false_async,
        _is_muc_pm=false_func,
        _is_public_muc=true_func,
        _is_enabled_for_room=true_async,
    )
    await ducks.duck_command(bot, "jid", "nick", ["friends"], msg, True)
    await ducks.duck_command(bot, "jid", "nick", ["top"], msg, True)
    await ducks.duck_command(bot, "jid", "nick", ["enemies"], msg, True)
    history = " ".join(x[0].lower() for x in bot._replies)
    assert "top duck friends" in history or "top duck enemies" in history


@pytest.mark.asyncio
async def test_duck_command_stats_path(monkeypatch):
    userstats = {
        "jid/alice": {
            "display_name": "Alice",
            "befriended": 5,
            "trapped": 2,
            "rooms": {"room@conf": {"befriended": 3, "trapped": 1}},
        }
    }
    bot = DummyBot(user_stats=userstats)
    msg = DummyMsg()
    patch_ducks(
        monkeypatch,
        handle_room_toggle_command=false_async,
        _is_muc_pm=false_func,
        _is_public_muc=true_func,
        _is_enabled_for_room=true_async,
        get_real_jid=fake_jid,
    )
    await ducks.duck_command(bot, "jid", "nick", ["stats", "jid/alice"],
                             msg, True)
    assert any("befriend" in t[0].lower(
    ) or "no duck stats found" in t[0].lower() for t in bot._replies)
    # Now test with get_real_jid returning None
    async def fake_none_jid(*a, **k): return (None, None, None)
    patch_ducks(monkeypatch, get_real_jid=fake_none_jid)
    await ducks.duck_command(bot, "jid", "nick", ["stats"], msg, True)
    assert any("could not determine" in t[0].lower() for t in bot._replies)


@pytest.mark.asyncio
async def test_bef_and_trap_commands(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    room = msg.from_.bare
    patch_ducks(
        monkeypatch,
        _is_public_muc=true_func,
        _is_enabled_for_room=true_async,
        get_real_jid=fake_jid,
        _ensure_user_exists=ensure_user,
    )
    ducks.ACTIVE_DUCKS[room] = 1000.0
    await ducks.bef_command(bot, "jid", "nick", [], msg, True)
    ducks.ACTIVE_DUCKS[room] = 1000.0
    await ducks.trap_command(bot, "jid", "nick", [], msg, True)
    texts = [x[0].lower() for x in bot._replies]
    assert any("befriend" in t or "trap" in t for t in texts)


@pytest.mark.asyncio
async def test_bef_trap_disabled_and_not_public(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    patch_ducks(monkeypatch, _is_public_muc=false_func,
                _is_enabled_for_room=false_async)
    await ducks.bef_command(bot, "jid", "nick", [], msg, True)
    await ducks.trap_command(bot, "jid", "nick", [], msg, True)
    assert not bot._replies


@pytest.mark.asyncio
async def test_duckstats_command(monkeypatch):
    userstats = {
        "jid/alice": {
            "display_name": "Alice",
            "befriended": 1,
            "trapped": 0,
            "rooms": {"room@conf": {"befriended": 1, "trapped": 0}},
        }
    }
    bot = DummyBot(user_stats=userstats)
    msg = DummyMsg()
    patch_ducks(
        monkeypatch,
        _is_public_muc=true_func,
        _is_enabled_for_room=true_async,
        get_real_jid=fake_jid,
    )
    await ducks.duckstats_command(bot, "jid", "nick", ["jid/alice"], msg, True)
    out = bot._replies and bot._replies[-1][0].lower() or ""
    assert ("befriend" in out or "no duck stats found"
            in out or "could not determine" in out)


@pytest.mark.asyncio
async def test_handle_duck_action_jid_fail(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()

    async def fake_get_real_jid(bot, msg):
        return (None, None, None)
    patch_ducks(monkeypatch, get_real_jid=fake_get_real_jid,
                _ensure_user_exists=fake_get_real_jid)
    await ducks._handle_duck_action(bot, msg, "befriended")
    assert "could not determine" in bot._replies[-1][0].lower()


@pytest.mark.asyncio
async def test_handle_duck_action_no_duck(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()

    async def fake_get_real_jid(bot, msg):
        return ("jid/alice", None, None)
    patch_ducks(monkeypatch, get_real_jid=fake_get_real_jid,
                _ensure_user_exists=fake_get_real_jid)
    await ducks._handle_duck_action(bot, msg, "befriended")
    assert "no duck" in bot._replies[-1][0].lower(
    ) or "❌" in bot._replies[-1][0]


@pytest.mark.asyncio
async def test_handle_duck_action_success(monkeypatch):
    bot = DummyBot()
    msg = DummyMsg()
    room = msg.from_.bare
    ducks.ACTIVE_DUCKS[room] = 1000.0

    async def fake_get_real_jid(bot, msg):
        return ("jid/alice", None, None)

    patch_ducks(monkeypatch, get_real_jid=fake_get_real_jid,
                _ensure_user_exists=ensure_user)
    await ducks._handle_duck_action(bot, msg, "befriended")
    out = bot._replies[-1][0].lower()
    assert "befriend" in out or "trap" in out


@pytest.mark.asyncio
async def test_expire_duck(monkeypatch):
    bot = DummyBot()
    room = "room@conf"
    ducks.ACTIVE_DUCKS[room] = 123.0
    await ducks._expire_duck(bot, room)
    assert room not in ducks.ACTIVE_DUCKS
    assert bot._replies


@pytest.mark.asyncio
async def test_on_message_skips(monkeypatch):
    bot = DummyBot()
    msg_m = DummyMsg()
    msg_m.get = lambda key, default=None: ""
    await ducks.on_message(bot, msg_m)
    msg2 = DummyMsg(groupchat=False)
    await ducks.on_message(bot, msg2)
    msg3 = DummyMsg()
    msg3.get = lambda key, default=None: \
        "jid/testbot" if key == "from" else "test"
    await ducks.on_message(bot, msg3)


@pytest.mark.asyncio
async def test_on_load_and_unload(monkeypatch):
    bot = DummyBot()
    spy = {}
    bot.bot_plugins.register_event = lambda *a, **k: spy.setdefault(
        "registered", True)
    await ducks.on_load(bot)
    assert spy["registered"]
    ducks.NEXT_DUCK_THRESHOLDS["abc"] = 1

    class CancelObj:
        cancelled = False
        def cancel(self): self.cancelled = True
    obj1 = CancelObj()
    obj2 = CancelObj()
    ducks.SPAWN_TASKS["abc"] = obj1
    ducks.EXPIRE_TASKS["abc"] = obj2
    ducks.ACTIVE_DUCKS["abc"] = 1
    ducks.PENDING_DUCKS.add("abc")
    ducks.MESSAGE_COUNTS["abc"] = 1
    await ducks.on_unload(bot)
    assert not ducks.ACTIVE_DUCKS and not ducks.PENDING_DUCKS
    assert obj1.cancelled and obj2.cancelled


@pytest.mark.asyncio
async def test_duck_cycle_state_helpers_persist_and_sanitize(monkeypatch):
    bot = DummyBot()
    room = "room@conf"
    bot.ducks_store._globals[ducks.DUCKS_STATE_KEY] = {
        room: {"message_count": "-1", "next_threshold": "bad"}
    }
    monkeypatch.setattr(ducks, "_get_random_threshold", lambda: 7)

    await ducks._load_room_cycle(bot, room)
    assert ducks.MESSAGE_COUNTS[room] == 0
    assert ducks.NEXT_DUCK_THRESHOLDS[room] == 7

    ducks.MESSAGE_COUNTS[room] = -5
    await ducks._save_room_cycle(bot, room)
    saved = bot.ducks_store._globals[ducks.DUCKS_STATE_KEY][room]
    assert saved["message_count"] == 0
    assert saved["next_threshold"] == 7


@pytest.mark.asyncio
async def test_daily_duck_count_and_increment_reset_by_date(monkeypatch):
    bot = DummyBot()
    room = "room@conf"
    monkeypatch.setattr(ducks, "_today_str", lambda: "2026-06-24")
    bot.ducks_store._globals[ducks.DUCKS_DAILY_KEY] = {
        room: {"date": "2026-06-23", "count": 99}
    }

    assert await ducks._get_daily_duck_count(bot, room) == 0
    assert await ducks._increment_daily_duck_count(bot, room) == 1
    assert await ducks._increment_daily_duck_count(bot, room) == 2
    assert bot.ducks_store._globals[ducks.DUCKS_DAILY_KEY][room] == {
        "date": "2026-06-24",
        "count": 2,
    }


@pytest.mark.asyncio
async def test_maybe_schedule_duck_skips_active_pending_daily_limit_and_scheduled(monkeypatch):
    bot = DummyBot()
    room = "room@conf"
    calls = []

    async def fake_load(bot_arg, room_arg):
        calls.append(("load", room_arg))
        ducks.MESSAGE_COUNTS[room_arg] = 0
        ducks.NEXT_DUCK_THRESHOLDS[room_arg] = 3

    monkeypatch.setattr(ducks, "_load_room_cycle", fake_load)
    monkeypatch.setattr(ducks, "_get_daily_duck_count", AsyncMock(return_value=ducks.MAX_DUCKS_PER_DAY))

    ducks.ACTIVE_DUCKS[room] = 1
    await ducks._maybe_schedule_duck(bot, room)
    assert calls == []

    ducks.ACTIVE_DUCKS.clear()
    ducks.PENDING_DUCKS.add(room)
    await ducks._maybe_schedule_duck(bot, room)
    assert calls == []

    ducks.PENDING_DUCKS.clear()
    await ducks._maybe_schedule_duck(bot, room)
    assert calls == [("load", room)]
    assert room not in ducks.PENDING_DUCKS

    ducks.MESSAGE_COUNTS[room] = -1
    monkeypatch.setattr(ducks, "_get_daily_duck_count", AsyncMock(return_value=0))
    await ducks._maybe_schedule_duck(bot, room)
    assert ducks.MESSAGE_COUNTS[room] == -1


@pytest.mark.asyncio
async def test_maybe_schedule_duck_counts_saves_and_schedules(monkeypatch):
    bot = DummyBot()
    room = "room@conf"
    saved_counts = []
    created = []

    async def fake_save(bot_arg, room_arg):
        saved_counts.append(ducks.MESSAGE_COUNTS[room_arg])

    def fake_create_task(bot_arg, plugin_name, coro, name=None):
        created.append((plugin_name, name))
        coro.close()
        return types.SimpleNamespace(cancel=lambda: None, done=lambda: False)

    monkeypatch.setattr(ducks, "DUCK_STATE_SAVE_EVERY", 2)
    monkeypatch.setattr(ducks, "DUCK_SPAWN_CHANCE", 1)
    monkeypatch.setattr(ducks, "_get_daily_duck_count", AsyncMock(return_value=0))
    monkeypatch.setattr(ducks, "_save_room_cycle", fake_save)
    monkeypatch.setattr(ducks.random, "randint", lambda low, high: 1 if high == 1 else 9)
    monkeypatch.setattr(ducks, "create_plugin_task", fake_create_task)

    ducks.MESSAGE_COUNTS[room] = 0
    ducks.NEXT_DUCK_THRESHOLDS[room] = 2

    await ducks._maybe_schedule_duck(bot, room)
    assert ducks.MESSAGE_COUNTS[room] == 1
    assert saved_counts == []
    assert room not in ducks.PENDING_DUCKS

    await ducks._maybe_schedule_duck(bot, room)
    assert saved_counts == [2, -1]
    assert ducks.MESSAGE_COUNTS[room] == -1
    assert room in ducks.PENDING_DUCKS
    assert ducks.SPAWN_TASKS[room]
    assert created == [("ducks", f"duck-spawn-{room}")]


@pytest.mark.asyncio
async def test_spawn_duck_after_delay_limit_success_and_cleanup(monkeypatch):
    bot = DummyBot()
    room = "room@conf"
    reset_calls = []
    increment_calls = []
    created = []
    old_expire = types.SimpleNamespace(cancelled=False)
    old_expire.cancel = lambda: setattr(old_expire, "cancelled", True)

    async def fake_reset(bot_arg, room_arg):
        reset_calls.append(room_arg)

    async def fake_increment(bot_arg, room_arg):
        increment_calls.append(room_arg)
        return 1

    def fake_create_task(bot_arg, plugin_name, coro, name=None):
        created.append((plugin_name, name))
        coro.close()
        return types.SimpleNamespace(cancel=lambda: None, done=lambda: False)

    monkeypatch.setattr(ducks.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(ducks, "_reset_room_cycle", fake_reset)
    monkeypatch.setattr(ducks, "_increment_daily_duck_count", fake_increment)
    monkeypatch.setattr(ducks, "DUCK_TIMEOUT", 10)
    monkeypatch.setattr(ducks, "create_plugin_task", fake_create_task)
    monkeypatch.setattr(ducks.random, "choice", lambda seq: seq[0])

    monkeypatch.setattr(ducks, "_get_daily_duck_count", AsyncMock(return_value=ducks.MAX_DUCKS_PER_DAY))
    ducks.PENDING_DUCKS.add(room)
    ducks.SPAWN_TASKS[room] = object()
    await ducks._spawn_duck_after_delay(bot, room, 0)
    assert reset_calls == [room]
    assert room not in ducks.ACTIVE_DUCKS
    assert room not in ducks.PENDING_DUCKS
    assert room not in ducks.SPAWN_TASKS

    reset_calls.clear()
    monkeypatch.setattr(ducks, "_get_daily_duck_count", AsyncMock(return_value=0))
    ducks.PENDING_DUCKS.add(room)
    ducks.SPAWN_TASKS[room] = object()
    ducks.EXPIRE_TASKS[room] = old_expire
    await ducks._spawn_duck_after_delay(bot, room, 0)

    assert room in ducks.ACTIVE_DUCKS
    assert reset_calls == [room]
    assert increment_calls == [room]
    assert old_expire.cancelled is True
    assert created == [("ducks", f"duck-expire-{room}")]
    assert bot._replies[-1][0] == ducks.SPAWN_MESSAGES[0]
    assert room not in ducks.PENDING_DUCKS
    assert room not in ducks.SPAWN_TASKS


@pytest.mark.asyncio
async def test_cleanup_room_state_removes_duck_runtime_tasks_and_store():
    bot = DummyBot()
    room = "room@conf"
    other = "other@conf"

    class Task:
        def __init__(self, done=False):
            self.cancelled = False
            self._done = done

        def done(self):
            return self._done

        def cancel(self):
            self.cancelled = True

    spawn_task = Task()
    expire_task = Task(done=True)
    ducks.SPAWN_TASKS[room] = spawn_task
    ducks.EXPIRE_TASKS[room] = expire_task
    ducks.ACTIVE_DUCKS[room] = {"nick": "duck"}
    ducks.PENDING_DUCKS.add(room)
    ducks.MESSAGE_COUNTS[room] = 5
    ducks.NEXT_DUCK_THRESHOLDS[room] = 10
    ducks.MESSAGE_COUNTS[other] = 1

    for key in (ducks.DUCKS_INDEX_KEY, ducks.DUCKS_LAST_KEY,
                ducks.DUCKS_DAILY_KEY, ducks.DUCKS_STATE_KEY):
        bot.ducks_store._globals[key] = {"Room@Conf": {"value": key}, other: {}}

    summary = await ducks.cleanup_room_state(bot, room)

    assert summary == {"data": 4, "tasks": 1, "runtime": 4}
    assert spawn_task.cancelled is True
    assert expire_task.cancelled is False
    assert room not in ducks.SPAWN_TASKS
    assert room not in ducks.EXPIRE_TASKS
    assert room not in ducks.ACTIVE_DUCKS
    assert room not in ducks.PENDING_DUCKS
    assert room not in ducks.MESSAGE_COUNTS
    assert room not in ducks.NEXT_DUCK_THRESHOLDS
    assert ducks.MESSAGE_COUNTS[other] == 1
    for key in (ducks.DUCKS_INDEX_KEY, ducks.DUCKS_LAST_KEY,
                ducks.DUCKS_DAILY_KEY, ducks.DUCKS_STATE_KEY):
        assert bot.ducks_store._globals[key] == {other: {}}
