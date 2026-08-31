from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import utils.xmpp_notify as xmpp_notify
from core_plugins import rooms


class AttrInfo:
    """Attribute-like disco response used by notification helper tests."""

    def __init__(self, *, features=None, identities=None):
        self.features = tuple(features or ())
        self.identities = tuple(identities or ())


class StrictStanza:
    """Stanza double that records field access and supports registered plugins."""

    def __init__(self, interfaces, values, *, plugins=None):
        self.interfaces = set(interfaces)
        self.values = dict(values)
        self.plugins = dict(plugins or {})
        self.accessed = []
        self.plugin_accessed = []

    def __getitem__(self, key):
        self.accessed.append(key)
        if key not in self.interfaces:
            raise KeyError(key)
        return self.values.get(key)

    def get_plugin(self, key, check=False):
        self.plugin_accessed.append((key, check))
        return self.plugins.get(key)


class GetItemBot:
    """Bot double exposing plugins through Slixmpp-style item access."""

    plugin = None

    def __init__(self, plugins=None, *, boundjid=None, presence=None):
        self._plugins = plugins or {}
        self.boundjid = boundjid
        self.presence = presence

    def __getitem__(self, key):
        if key in self._plugins:
            return self._plugins[key]
        raise KeyError(key)


@pytest.fixture(autouse=True)
def cleanup_joined_rooms():
    old = dict(rooms.JOINED_ROOMS)
    rooms.JOINED_ROOMS.clear()
    yield
    rooms.JOINED_ROOMS.clear()
    rooms.JOINED_ROOMS.update(old)


def test_target_text_and_room_jid_shape():
    assert xmpp_notify._target_text(" room@conf.test ") == "room@conf.test"
    assert xmpp_notify._target_text(None) == ""
    assert xmpp_notify._looks_like_bare_room_jid("room@conf.test") is True
    assert xmpp_notify._looks_like_bare_room_jid("room@conf.test/nick") is False
    assert xmpp_notify._looks_like_bare_room_jid("room") is False
    assert xmpp_notify._looks_like_bare_room_jid("") is False


def test_joined_room_nick_from_presence_and_runtime_state():
    bot = SimpleNamespace(presence=SimpleNamespace(joined_rooms={"room@conf.test": "Bot"}))
    assert xmpp_notify.joined_room_nick(bot, " room@conf.test ") == "Bot"
    assert xmpp_notify.notification_message_type(bot, "room@conf.test") == "groupchat"
    assert xmpp_notify.notification_message_type(bot, "user@example.org") == "chat"

    rooms.JOINED_ROOMS["fallback@conf.test"] = {"nick": "RuntimeBot"}
    assert xmpp_notify.joined_room_nick(SimpleNamespace(), "fallback@conf.test") == "RuntimeBot"
    assert xmpp_notify.joined_room_nick(SimpleNamespace(), "") is None


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        ({"category": "conference", "type": "text", "name": "Room"}, True),
        (("conference", "text", None, "Room"), True),
        ({"category": "client", "type": "pc", "name": "MUC Helper"}, False),
        (("client", "pc", None, "Conference Browser"), False),
        ({"category": "server", "type": "im", "name": "conference tools"}, False),
        (SimpleNamespace(category="conference", name="Room"), True),
        (SimpleNamespace(category="client", name="MUC Helper"), False),
        ((), False),
    ],
)
def test_identity_is_muc_uses_only_disco_category(identity, expected):
    assert xmpp_notify._identity_is_muc(identity) is expected


@pytest.mark.asyncio
async def test_target_is_muc_room_uses_joined_room_and_stored_room():
    joined = SimpleNamespace(presence=SimpleNamespace(joined_rooms={"room@conf.test": "Bot"}))
    assert await xmpp_notify.target_is_muc_room(joined, "room@conf.test") is True
    assert await xmpp_notify.target_is_muc_room(joined, "not-a-room") is False
    assert await xmpp_notify.target_is_muc_room(joined, "room@conf.test/nick") is False

    stored_rooms = SimpleNamespace(get=AsyncMock(return_value=("stored@conf.test", "Bot", True, None)))
    stored = SimpleNamespace(db=SimpleNamespace(rooms=stored_rooms))
    assert await xmpp_notify.target_is_muc_room(stored, "stored@conf.test") is True
    stored_rooms.get.assert_awaited_once_with("stored@conf.test")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "info",
    [
        {"features": [xmpp_notify._MUC_FEATURE]},
        {"disco_info": {"features": [xmpp_notify._MUC_FEATURE]}},
        {"disco_info": {"identities": [("conference", "text", "muc")]}},
        AttrInfo(features=[xmpp_notify._MUC_FEATURE]),
        AttrInfo(identities=[{"category": "conference", "type": "text"}]),
    ],
)
async def test_target_is_muc_room_uses_disco_shapes(info):
    disco = SimpleNamespace(get_info=AsyncMock(return_value=info))
    bot = SimpleNamespace(plugin={"xep_0030": disco})

    assert await xmpp_notify.target_is_muc_room(bot, "room@conf.test") is True
    disco.get_info.assert_awaited_once_with(jid="room@conf.test")


@pytest.mark.asyncio
async def test_target_is_muc_room_ignores_muc_words_outside_identity_category():
    disco = SimpleNamespace(
        get_info=AsyncMock(
            return_value={
                "identities": [
                    {
                        "category": "client",
                        "type": "pc",
                        "name": "MUC Helper / Conference Browser",
                    }
                ]
            }
        )
    )
    bot = SimpleNamespace(plugin={"xep_0030": disco})

    assert await xmpp_notify.target_is_muc_room(bot, "user@example.org") is False


@pytest.mark.asyncio
async def test_target_is_muc_room_does_not_probe_iq_only_disco_interfaces():
    disco_info = StrictStanza(
        {"features", "identities", "node"},
        {
            "features": {"urn:xmpp:ping"},
            "identities": {("client", "pc", None, "Desktop")},
        },
    )
    iq = StrictStanza(
        {"id", "type", "from", "to"},
        {},
        plugins={"disco_info": disco_info},
    )
    disco = SimpleNamespace(get_info=AsyncMock(return_value=iq))
    bot = SimpleNamespace(plugin={"xep_0030": disco})

    assert await xmpp_notify.target_is_muc_room(bot, "user@example.org") is False
    assert iq.accessed == []
    assert iq.plugin_accessed == [("disco_info", True), ("disco_info", True)]
    assert disco_info.accessed == ["features", "identities"]


@pytest.mark.asyncio
async def test_target_is_muc_room_handles_missing_or_failing_disco():
    assert await xmpp_notify.target_is_muc_room(SimpleNamespace(plugin={}), "room@conf.test") is False

    disco = SimpleNamespace(get_info=AsyncMock(return_value={"features": ["other"]}))
    assert await xmpp_notify.target_is_muc_room(SimpleNamespace(plugin={"xep_0030": disco}), "room@conf.test") is False

    failing = SimpleNamespace(get_info=AsyncMock(side_effect=RuntimeError("boom")))
    assert await xmpp_notify.target_is_muc_room(SimpleNamespace(plugin={"xep_0030": failing}), "room@conf.test") is False

    getitem_bot = GetItemBot(
        {
            "xep_0030": SimpleNamespace(
                get_info=AsyncMock(
                    return_value={"features": [xmpp_notify._MUC_FEATURE]}
                )
            )
        }
    )
    assert await xmpp_notify.target_is_muc_room(getitem_bot, "room@conf.test") is True


@pytest.mark.asyncio
async def test_target_is_muc_room_handles_stored_room_errors():
    class BrokenRooms:
        async def get(self, room):
            raise RuntimeError("db down")

    disco = SimpleNamespace(get_info=AsyncMock(return_value={"features": [xmpp_notify._MUC_FEATURE]}))
    bot = SimpleNamespace(db=SimpleNamespace(rooms=BrokenRooms()), plugin={"xep_0030": disco})

    assert await xmpp_notify.target_is_muc_room(bot, "room@conf.test") is True


@pytest.mark.asyncio
async def test_ensure_room_joined_skips_existing_room():
    bot = SimpleNamespace(presence=SimpleNamespace(joined_rooms={"room@conf.test": "Bot"}))

    assert await xmpp_notify.ensure_room_joined(bot, "room@conf.test") is True


@pytest.mark.asyncio
async def test_ensure_room_joined_requires_muc_plugin():
    assert await xmpp_notify.ensure_room_joined(SimpleNamespace(plugin={}), "room@conf.test") is False

    assert await xmpp_notify.ensure_room_joined(GetItemBot(), "room@conf.test") is False


@pytest.mark.asyncio
async def test_ensure_room_joined_joins_and_updates_runtime_state(monkeypatch):
    monkeypatch.setitem(xmpp_notify.config, "nick", "ConfigBot")
    muc = SimpleNamespace(join_muc=AsyncMock())
    broadcast = MagicMock()
    bot = SimpleNamespace(
        plugin={"xep_0045": muc},
        presence=SimpleNamespace(joined_rooms={}, status={"show": "chat", "status": "Ready"}, broadcast=broadcast),
        boundjid=SimpleNamespace(resource="BoundBot"),
    )

    assert await xmpp_notify.ensure_room_joined(bot, "room@conf.test") is True

    muc.join_muc.assert_awaited_once_with(
        "room@conf.test",
        "ConfigBot",
        pshow="chat",
        pstatus="Ready",
    )
    assert bot.presence.joined_rooms["room@conf.test"] == "ConfigBot"
    assert rooms.JOINED_ROOMS["room@conf.test"]["nick"] == "ConfigBot"
    broadcast.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_room_joined_uses_explicit_or_bound_nick_and_getitem_fallback(monkeypatch):
    monkeypatch.setitem(xmpp_notify.config, "nick", "")
    muc = SimpleNamespace(join_muc=AsyncMock())

    getitem_bot = GetItemBot(
        {"xep_0045": muc},
        boundjid=SimpleNamespace(resource="BoundBot"),
        presence=SimpleNamespace(joined_rooms={}, status={}),
    )

    assert await xmpp_notify.ensure_room_joined(
        getitem_bot, "room@conf.test", nick="Explicit"
    ) is True
    muc.join_muc.assert_awaited_once_with("room@conf.test", "Explicit", pshow=None, pstatus=None)


@pytest.mark.asyncio
async def test_ensure_room_joined_handles_join_and_state_update_failures(monkeypatch):
    monkeypatch.setitem(xmpp_notify.config, "nick", None)
    failing_muc = SimpleNamespace(join_muc=AsyncMock(side_effect=RuntimeError("join failed")))
    bot = SimpleNamespace(
        plugin={"xep_0045": failing_muc},
        presence=SimpleNamespace(joined_rooms={}, status={}),
        boundjid=SimpleNamespace(resource="BoundBot"),
    )
    assert await xmpp_notify.ensure_room_joined(bot, "room@conf.test") is False

    good_muc = SimpleNamespace(join_muc=AsyncMock())

    class BrokenPresence:
        status = {}

        @property
        def joined_rooms(self):
            raise RuntimeError("broken")

    bot = SimpleNamespace(
        plugin={"xep_0045": good_muc},
        presence=BrokenPresence(),
        boundjid=SimpleNamespace(resource="BoundBot"),
    )
    assert await xmpp_notify.ensure_room_joined(bot, "room2@conf.test") is True


@pytest.mark.asyncio
async def test_ensure_notification_target_joined(monkeypatch):
    bot = SimpleNamespace()
    assert await xmpp_notify.ensure_notification_target_joined(bot, "") is False

    target_is_muc = AsyncMock(return_value=False)
    join_room = AsyncMock()
    monkeypatch.setattr(xmpp_notify, "target_is_muc_room", target_is_muc)
    monkeypatch.setattr(xmpp_notify, "ensure_room_joined", join_room)

    assert await xmpp_notify.ensure_notification_target_joined(bot, "user@example.org") is False
    join_room.assert_not_awaited()

    target_is_muc.return_value = True
    join_room.return_value = True
    assert await xmpp_notify.ensure_notification_target_joined(bot, "room@conf.test") is True
    join_room.assert_awaited_once_with(bot, "room@conf.test")
