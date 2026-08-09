import asyncio
import itertools
import types
from importlib import import_module

import pytest

from core_plugins import _core
from core_plugins.rooms import JOINED_ROOMS
from plugins.idlerpg import commands as idlerpg_commands
from plugins.idlerpg import config as idlerpg_config
from plugins.idlerpg import constants as idlerpg_constants
from plugins.idlerpg import handlers as idlerpg_handlers
from plugins.idlerpg import state as idlerpg_state
from plugins.idlerpg import tasks as idlerpg_tasks
from utils.command import Role

idlerpg = import_module("plugins.idlerpg")


class DummyStore:
    def __init__(self):
        self.globals = {idlerpg_constants.IDLERPG_ENABLED_KEY: {"room@conf": True}}

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
        def create_task(plugin, coro, name=None):
            return DummyTask(coro, name)

        self.bot_plugins = types.SimpleNamespace(
            register_event=lambda *a, **k: None,
            create_task=create_task,
        )
        self.audit_events = []
        self.tasks = types.SimpleNamespace(create=create_task)

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


def _cancel_room_tasks():
    for task in tuple(idlerpg_config.ROOM_TASKS.values()):
        done = getattr(task, "done", None)
        if callable(done) and done():
            continue
        cancel = getattr(task, "cancel", None)
        if callable(cancel):
            cancel()
    idlerpg_config.ROOM_TASKS.clear()


def _reset_idlerpg_runtime_state():
    _cancel_room_tasks()
    idlerpg_handlers._MESSAGE_PENALTY_SEEN.clear()
    idlerpg_tasks._ROOM_TASK_LOCKS.clear()
    idlerpg_tasks._ROOM_TICK_LOCKS.clear()
    idlerpg_state._reset_public_export_schedule()


@pytest.fixture(autouse=True)
def clear_idlerpg_state():
    _reset_idlerpg_runtime_state()
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
    _reset_idlerpg_runtime_state()
    JOINED_ROOMS.clear()


async def _register_alice(bot, msg):
    await idlerpg_commands._handle_register(
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
