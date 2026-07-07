import core_plugins.rooms as rooms
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import types
import plugins.rss as rss_plugin
import plugins.xkcd as xkcd_plugin
import plugins.pin as pin_plugin
import plugins.poll as poll_plugin
from tests.helpers import PresenceStub, make_presence_stub
import logging


logging.getLogger("core_plugins.rooms").setLevel(logging.CRITICAL)


ROOM_JID = "room@conference.test"


BOT_JID = "bot@domain"


BOT_NICK = "BotNick"


USER_NICK = "Nick"


USER_JID = "user@jid"


def make_presence(
    nick: str,
    *,
    room: str = ROOM_JID,
    role: str = "participant",
    jid: str = USER_JID,
    affiliation: str = "member",
    type_: str = "available",
) -> PresenceStub:
    return make_presence_stub(
        room,
        nick,
        role=role,
        jid=jid,
        affiliation=affiliation,
        type_=type_,
    )


def patch_reply_methods(bot):
    """Attach the reply helpers used by room command tests."""
    for name in ("reply_error", "reply_usage", "reply_warn", "reply_info", "reply_ok"):
        setattr(bot, name, MagicMock())


@pytest.fixture(autouse=True)
def cleanup_joined_rooms():
    """Ensure room runtime globals are clean for each test."""
    orig = dict(rooms.JOINED_ROOMS)
    orig_leaving = set(rooms._LEAVING_ROOMS)
    rooms.JOINED_ROOMS.clear()
    rooms._LEAVING_ROOMS.clear()
    yield
    rooms.JOINED_ROOMS.clear()
    rooms.JOINED_ROOMS.update(orig)
    rooms._LEAVING_ROOMS.clear()
    rooms._LEAVING_ROOMS.update(orig_leaving)


@pytest.fixture
def fake_bot():
    bot = MagicMock()
    bot.boundjid.bare = "bot@domain"
    bot.boundjid.resource = "BotNick"
    bot.presence.status = {'show': 'chat', 'status': 'online'}
    bot.presence.joined_rooms = {}
    # plugins registry, used by on_load
    bot.bot_plugins = MagicMock()
    bot.bot_plugins.cleanup_room_state = AsyncMock(return_value={})
    # plugin system
    bot.plugin = {"xep_0045": MagicMock()}
    # DB interface
    bot.db = MagicMock()
    bot.db.rooms = MagicMock()
    bot.db.rooms.get = AsyncMock(return_value=(ROOM_JID, BOT_NICK, True, None))
    bot.db.users = MagicMock()
    bot.get_user_role = AsyncMock(return_value=rooms.Role.MODERATOR)
    bot.prefix = "!"
    bot.reply = MagicMock()
    patch_reply_methods(bot)
    bot.presence.broadcast = MagicMock()
    return bot


@pytest.fixture
def fake_msg():
    msg = {
        "from": MagicMock(),
        "type": "groupchat",
        "to": MagicMock(),
    }
    msg["from"].bare = "room@conference.test"
    msg["from"].resource = "Nick"
    msg["to"].bare = "bot@domain"
    return msg


class DummyPluginStore(dict):
    async def get_global(self, key, default=None):
        return self.get(key, default)

    async def set_global(self, key, value):
        self[key] = value


class InviteMessage(dict):
    """Small message double with XML payload for room invite tests."""

    def __init__(self, from_jid: str, xml):
        super().__init__()
        self["from"] = types.SimpleNamespace(
            bare=from_jid.split("/", 1)[0],
            resource=from_jid.split("/", 1)[1] if "/" in from_jid else None,
        )
        self["type"] = "chat"
        self.xml = xml

    def __eq__(self, other):
        return (
            dict.__eq__(self, other)
            and getattr(other, "xml", None) == self.xml
        )


class PluginStanza(dict):
    """Small stanza double that exposes Slixmpp-style get_plugin."""

    def __init__(self, from_jid="inviter@example.org", plugins=None, msg_type="chat"):
        super().__init__()
        self["from"] = types.SimpleNamespace(
            bare=from_jid.split("/", 1)[0],
            resource=from_jid.split("/", 1)[1] if "/" in from_jid else None,
        )
        self["type"] = msg_type
        self._plugins = plugins or {}
        self.xml = None

    def __eq__(self, other):
        return (
            dict.__eq__(self, other)
            and getattr(other, "_plugins", None) == self._plugins
            and getattr(other, "xml", None) == self.xml
        )

    def get_plugin(self, name, check=True):
        plugin = self._plugins.get(name)
        if isinstance(plugin, BaseException):
            raise plugin
        return plugin


class FallbackPluginStanza(dict):
    """Stanza double where get_plugin does not accept check=."""

    def __init__(self, plugin):
        super().__init__()
        self._plugin = plugin

    def __eq__(self, other):
        return (
            dict.__eq__(self, other)
            and getattr(other, "_plugin", None) == self._plugin
        )

    def get_plugin(self, name):
        return self._plugin if name == "muc" else None


class MappingOnlyPlugin:
    """Plugin double that only supports __getitem__."""

    def __init__(self, values):
        self.values = dict(values)

    def get(self, key):
        raise RuntimeError("get failed")

    def __getitem__(self, key):
        return self.values[key]


class ExplodingMappingPlugin:
    def get(self, key):
        raise RuntimeError("get failed")

    def __getitem__(self, key):
        raise KeyError(key)


__all__ = [
    "rooms",
    "pytest",
    "MagicMock",
    "AsyncMock",
    "patch",
    "types",
    "rss_plugin",
    "xkcd_plugin",
    "pin_plugin",
    "poll_plugin",
    "PresenceStub",
    "make_presence_stub",
    "logging",
    "ROOM_JID",
    "BOT_JID",
    "BOT_NICK",
    "USER_NICK",
    "USER_JID",
    "make_presence",
    "patch_reply_methods",
    "cleanup_joined_rooms",
    "fake_bot",
    "fake_msg",
    "DummyPluginStore",
    "InviteMessage",
    "PluginStanza",
    "FallbackPluginStanza",
    "MappingOnlyPlugin",
    "ExplodingMappingPlugin",
]
