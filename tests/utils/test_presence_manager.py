import logging

from utils.presence_manager import PresenceManager


class DummyBot:
    def __init__(self):
        self.calls = []
        self.sent_stanzas = []
        self.bot_plugins = type("Plugins", (), {"plugins": {}})()

    def send_presence(self, **kwargs):
        self.calls.append(kwargs)

    def send(self, stanza):
        self.sent_stanzas.append(stanza)


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


def test_broadcast_sends_presence(monkeypatch):
    bot = DummyBot()
    pm = PresenceManager(bot)
    # Simulate no rooms plugin
    pm.broadcast()
    assert len(bot.calls) == 1
    assert "pshow" not in bot.calls[0] or isinstance(
        bot.calls[0]["pshow"], str)


def test_broadcast_with_rooms(monkeypatch):
    bot = DummyBot()
    pm = PresenceManager(bot)
    room_plugin = type("Rooms", (), {"JOINED_ROOMS": {
        "room1": {"nick": "Bob"},
        "room2": {"nick": None}
    }})()
    bot.bot_plugins.plugins["rooms"] = room_plugin
    pm.broadcast()
    # Should call send_presence for bot plus one extra for room1 (has nick)
    assert len(bot.calls) == 2
    main, room = bot.calls
    assert "pto" not in main
    assert room["pto"] == "room1/Bob"


def test_broadcast_with_avatar_hash_sends_xep0153_presence():
    bot = DummyBot()
    bot.avatar_hash = "abc123"
    pm = PresenceManager(bot)
    room_plugin = type("Rooms", (), {"JOINED_ROOMS": {
        "room1": {"nick": "BotNick"},
    }})()
    bot.bot_plugins.plugins["rooms"] = room_plugin

    pm.broadcast()

    assert bot.calls == []
    assert len(bot.sent_stanzas) == 2
    global_presence, room_presence = bot.sent_stanzas
    assert str(room_presence["to"]) == "room1/BotNick"
    assert global_presence.xml.find("{vcard-temp:x:update}x") is not None
    x = room_presence.xml.find("{vcard-temp:x:update}x")
    assert x is not None
    assert x.find("photo").text == "abc123"


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
