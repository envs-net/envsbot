import pytest
import asyncio
import logging
from unittest.mock import AsyncMock
from types import SimpleNamespace
import plugins.rss as rss

import core_plugins.rooms
from utils.command import Role
from utils.task_supervisor import TaskSupervisor
from plugins.rss import commands as rss_commands


def patch_config(monkeypatch):
    monkeypatch.setattr(rss_commands, "config", {"prefix": ","})


def _reply_text(reply):
    text = reply[1]
    if isinstance(text, (list, tuple)):
        return "\n".join(str(part) for part in text)
    return str(text)


class Entry(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get(self, key, default=None):
        if hasattr(self, key):
            return getattr(self, key)
        if key in self:
            return self[key]
        return default


@pytest.fixture
def make_bot():
    """
    Return a fake bot object with pluggable bot.reply and db.users.plugin().
    """

    class DummyStore(dict):
        async def get_global(self, key, default=None):
            return self.get(key, default)

        async def set_global(self, key, value):
            self[key] = value

    class DummyBot:
        def __init__(self):
            self.replies = []
            self.flush_count = 0

            async def flush_all():
                self.flush_count += 1

            self.db = SimpleNamespace(
                users=SimpleNamespace(
                    plugin=lambda name: self.plugin_store,
                    flush_all=flush_all,
                )
            )
            self.plugin_store = DummyStore()

        async def get_user_role(self, jid, room=None):
            return Role.MODERATOR

        def reply(self, msg, text, **kwargs):
            self.replies.append((msg, text, kwargs))

    return DummyBot


class _RssPendingTask:
    def done(self):
        return False


class _RssDoneTask:
    def done(self):
        return True


@pytest.fixture(autouse=True)
def clear_rss_runtime_state():
    rss.CHECK_TASKS.clear()
    yield
    rss.CHECK_TASKS.clear()


__all__ = [
    "pytest",
    "asyncio",
    "logging",
    "AsyncMock",
    "SimpleNamespace",
    "rss",
    "core_plugins",
    "Role",
    "TaskSupervisor",
    "patch_config",
    "_reply_text",
    "Entry",
    "make_bot",
    "_RssPendingTask",
    "_RssDoneTask",
    "clear_rss_runtime_state",
]
