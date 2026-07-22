import logging
from xml.etree import ElementTree as ET

from utils.presence_manager import PresenceManager


class _AvatarUpdate:
    def __init__(self, presence):
        self.presence = presence

    def __setitem__(self, key, value):
        assert key == "photo"
        x = self.presence.xml.find("{vcard-temp:x:update}x")
        if x is None:
            x = ET.SubElement(self.presence.xml, "{vcard-temp:x:update}x")
        photo = x.find("photo")
        if photo is None:
            photo = ET.SubElement(x, "photo")
        photo.text = value


class _FakePresence:
    def __init__(self, bot, kwargs, *, bound=True):
        self.bot = bot
        self.stream = bot if bound else None
        self.kwargs = dict(kwargs)
        self.xml = ET.Element("presence")
        if kwargs.get("pto") is not None:
            self.xml.set("to", str(kwargs["pto"]))

    def __getitem__(self, key):
        if key == "vcard_temp_update":
            return _AvatarUpdate(self)
        if key == "to":
            return self.xml.get("to", "")
        return self.kwargs.get(key, "")

    def send(self):
        self.bot.sent_stanzas.append(self)


class DummyBot:
    def __init__(self):
        self.calls = []
        self.sent_stanzas = []
        self.bot_plugins = type("Plugins", (), {"plugins": {}})()
        self.bind_presence = True

    def make_presence(self, **kwargs):
        self.calls.append(kwargs)
        return _FakePresence(self, kwargs, bound=self.bind_presence)


def test_presence_manager_update_sets_status():
    bot = DummyBot()
    pm = PresenceManager(bot)
    pm.update("chat", "Chatting!")
    assert pm.status["show"] == "chat"
    assert pm.status["status"] == "Chatting!"


def test_presence_manager_emoji_for_states():
    bot = DummyBot()
    pm = PresenceManager(bot)
    # All known
    assert pm.emoji("online") == "✅"
    assert pm.emoji("chat") == "💬"
    assert pm.emoji("xa") == "💤"
    assert pm.emoji("dnd") == "⛔"
    assert pm.emoji("away") == "👋 "
    # Fallback
    assert pm.emoji("notreal") == ""


def test_broadcast_sends_stream_bound_presence():
    bot = DummyBot()
    pm = PresenceManager(bot)

    pm.broadcast()

    assert bot.calls == [{"pshow": None, "pstatus": "I'm ready to serve you!"}]
    assert len(bot.sent_stanzas) == 1
    assert bot.sent_stanzas[0].stream is bot


def test_broadcast_with_rooms():
    bot = DummyBot()
    pm = PresenceManager(bot)
    room_plugin = type("Rooms", (), {"JOINED_ROOMS": {
        "room1": {"nick": "Bob"},
        "room2": {"nick": None}
    }})()
    bot.bot_plugins.plugins["rooms"] = room_plugin

    pm.broadcast()

    assert len(bot.calls) == 2
    main, room = bot.calls
    assert "pto" not in main
    assert room["pto"] == "room1/Bob"
    assert all(stanza.stream is bot for stanza in bot.sent_stanzas)


def test_broadcast_with_avatar_hash_uses_single_xep0153_payload():
    bot = DummyBot()
    bot.avatar_hash = "abc123"
    pm = PresenceManager(bot)
    room_plugin = type("Rooms", (), {"JOINED_ROOMS": {
        "room1": {"nick": "BotNick"},
    }})()
    bot.bot_plugins.plugins["rooms"] = room_plugin

    pm.broadcast()

    assert len(bot.sent_stanzas) == 2
    global_presence, room_presence = bot.sent_stanzas
    assert str(room_presence["to"]) == "room1/BotNick"
    for presence in (global_presence, room_presence):
        assert presence.stream is bot
        updates = presence.xml.findall("{vcard-temp:x:update}x")
        assert len(updates) == 1
        assert updates[0].find("photo").text == "abc123"


def test_unbound_presence_is_not_sent(caplog):
    bot = DummyBot()
    bot.bind_presence = False
    pm = PresenceManager(bot)

    with caplog.at_level(logging.WARNING, logger="utils.presence_manager"):
        assert pm._send_presence(pto="user@example.org") is False

    assert bot.sent_stanzas == []
    assert "Skipping unbound presence stanza to user@example.org" in caplog.text


def test_broadcast_logs_duplicate_status_at_debug(caplog):
    bot = DummyBot()
    pm = PresenceManager(bot)

    with caplog.at_level(logging.DEBUG, logger="utils.presence_manager"):
        pm.broadcast()
        pm.broadcast()
        pm.update("away", "Lunch")

    info_messages = [
        record.message
        for record in caplog.records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.message
        for record in caplog.records
        if record.levelno == logging.DEBUG
    ]

    assert info_messages.count(
        "[PRESENCE] ✅ Status set: 'online': [I'm ready to serve you!]"
    ) == 1
    assert (
        "[PRESENCE] ✅ Status set: 'online': [I'm ready to serve you!]"
        in debug_messages
    )
    assert "[PRESENCE] 👋  Status set: 'away': [Lunch]" in info_messages
