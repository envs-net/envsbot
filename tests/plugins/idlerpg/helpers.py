import asyncio
import itertools
import types
import pytest
import plugins.idlerpg as idlerpg
from core_plugins.rooms import JOINED_ROOMS
from core_plugins import _core
from utils.command import Role


class DummyStore:
    def __init__(self):
        self.globals = {idlerpg.IDLERPG_ENABLED_KEY: {"room@conf": True}}

    async def get_global(self, key, default=None):
        return self.globals.get(key, default)

    async def set_global(self, key, value):
        self.globals[key] = value

    async def delete_global(self, key):
        self.globals.pop(key, None)


class DummyBot:
    def __init__(self):
        self.store = DummyStore()
        self.flush_count = 0

        async def flush():
            self.flush_count += 1

        self.db = types.SimpleNamespace(
            users=types.SimpleNamespace(plugin=lambda name: self.store),
            flush=flush,
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
        if str(jid).startswith("admin@"):
            return Role.ADMIN
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
    def __init__(self, body=",idlerpg", bare="room@conf", resource="Alice", mtype="groupchat", stanza_id=None):
        self.data = {
            "from": types.SimpleNamespace(bare=bare, resource=resource),
            "to": types.SimpleNamespace(bare="bot@envs.net"),
            "type": mtype,
            "body": body,
            "mucnick": resource,
        }
        if stanza_id is not None:
            self.data["id"] = stanza_id

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)


@pytest.fixture(autouse=True)
def clear_idlerpg_state():
    idlerpg.ROOM_TASKS.clear()
    getattr(idlerpg, "_MESSAGE_PENALTY_SEEN", {}).clear()
    getattr(idlerpg, "_ROOM_TASK_LOCKS", {}).clear()
    getattr(idlerpg, "_ROOM_TICK_LOCKS", {}).clear()
    reset_export_schedule = getattr(idlerpg, "_reset_public_export_schedule", None)
    if callable(reset_export_schedule):
        reset_export_schedule()
    JOINED_ROOMS.clear()
    _core.JOINED_ROOMS = JOINED_ROOMS
    JOINED_ROOMS["room@conf"] = {
        "nicks": {
            "Alice": {"jid": "alice@envs.net", "affiliation": "member"},
            "Mod": {"jid": "mod@envs.net", "affiliation": "member"},
            "Admin": {"jid": "admin@envs.net", "affiliation": "admin"},
        }
    }
    yield
    idlerpg.ROOM_TASKS.clear()
    getattr(idlerpg, "_MESSAGE_PENALTY_SEEN", {}).clear()
    getattr(idlerpg, "_ROOM_TASK_LOCKS", {}).clear()
    getattr(idlerpg, "_ROOM_TICK_LOCKS", {}).clear()
    reset_export_schedule = getattr(idlerpg, "_reset_public_export_schedule", None)
    if callable(reset_export_schedule):
        reset_export_schedule()
    JOINED_ROOMS.clear()


async def _register_alice(bot, msg):
    await idlerpg._handle_register(
        bot,
        "alice@envs.net",
        ["register", "Alice", "sysadmin"],
        msg,
        True,
    )


__all__ = [
    "asyncio",
    "itertools",
    "types",
    "pytest",
    "idlerpg",
    "JOINED_ROOMS",
    "Role",
    "DummyStore",
    "DummyBot",
    "DummyTask",
    "DummyMsg",
    "clear_idlerpg_state",
    "_register_alice",
]
