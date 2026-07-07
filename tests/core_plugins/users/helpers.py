import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import types
import core_plugins.users as users_mod
import core_plugins.rooms


def _make_mock_bot(*, include_audit: bool = False):
    bot = MagicMock()
    bot.db = MagicMock()
    bot.db.users = MagicMock()
    bot.db.users.plugin = MagicMock()
    bot.bot_plugins = MagicMock()
    bot.bot_plugins.plugins = {}
    bot.reply = MagicMock()
    bot.get_user_role = AsyncMock(return_value=users_mod.Role.USER)
    bot.audit = AsyncMock() if include_audit else None
    return bot


def assert_reply_contains(bot_reply, substring: str):
    expected = substring.lower()
    for call in bot_reply.call_args_list:
        for arg in call.args:
            if expected in str(arg).lower():
                return
    assert False, f"Expected reply to contain {substring!r}"


class FakeUserManager:
    def __init__(self, *, plugin_store, nick_index):
        self._plugin_store = plugin_store
        self.nick_index = nick_index
        self.nick_index_lock = asyncio.Lock()
        self.get = AsyncMock(return_value=None)
        self.create = AsyncMock()

    def plugin(self, name):
        assert name == "users"
        return self._plugin_store

    @property
    def _nick_index(self):
        return self.nick_index

    @property
    def _nick_index_lock(self):
        return self.nick_index_lock



@pytest.fixture
def mock_bot():
    return _make_mock_bot(include_audit=True)



@pytest.fixture
def mock_msg():
    m = MagicMock()
    m.get = MagicMock()
    m.__getitem__.side_effect = lambda k: m.__dict__.get(k, None)
    m.__setitem__.side_effect = lambda k, v: m.__dict__.__setitem__(k, v)
    m.body = ""
    m['from'] = MagicMock()
    m['from'].bare = "room@conference.server"
    m['from'].resource = "nick"
    m['muc'] = {"room": "room@conference.server", "nick": "nick"}
    m['type'] = "groupchat"
    return m



@pytest.fixture(autouse=True)
def patch_joined_rooms():
    with patch.object(users_mod, "JOINED_ROOMS", {}, create=True):
        yield



@pytest.fixture
def build_mock_bot():
    def factory():
        return _make_mock_bot()
    return factory


__all__ = [
    "pytest",
    "asyncio",
    "AsyncMock",
    "MagicMock",
    "patch",
    "types",
    "users_mod",
    "core_plugins",
    "_make_mock_bot",
    "assert_reply_contains",
    "FakeUserManager",
    "mock_bot",
    "mock_msg",
    "patch_joined_rooms",
    "build_mock_bot",
]
