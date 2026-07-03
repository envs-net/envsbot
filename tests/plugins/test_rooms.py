import core_plugins.rooms as rooms
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import types

import plugins.rss as rss_plugin
import plugins.xkcd as xkcd_plugin
import plugins.pin as pin_plugin
import plugins.poll as poll_plugin

from tests.helpers import PresenceStub, make_presence_stub

# Patch the logging to avoid noisy output
import logging
logging.getLogger("core_plugins.rooms").setLevel(logging.CRITICAL)

# Import the module under test


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


@pytest.mark.asyncio
async def test_is_nick_change_true_and_false():
    pres = MagicMock()
    stat1 = MagicMock()
    stat2 = MagicMock()
    stat1.attrib.get.return_value = "303"
    stat2.attrib.get.return_value = "100"
    pres.xml.findall.return_value = [stat2, stat1]
    assert rooms.is_nick_change(pres) is True

    stat1.attrib.get.return_value = "100"
    stat2.attrib.get.return_value = "200"
    pres.xml.findall.return_value = [stat1, stat2]
    assert rooms.is_nick_change(pres) is False


@pytest.mark.asyncio
async def test_on_muc_presence_join_or_leave(fake_bot):
    fake_bot.boundjid.bare = BOT_JID

    # Bot joins.
    await rooms.on_muc_presence(
        fake_bot,
        make_presence(
            BOT_NICK,
            role="moderator",
            jid=BOT_JID,
            affiliation="admin",
        ),
    )
    assert ROOM_JID in rooms.JOINED_ROOMS
    assert BOT_NICK in rooms.JOINED_ROOMS[ROOM_JID]["nicks"]

    # User joins.
    await rooms.on_muc_presence(fake_bot, make_presence(USER_NICK))
    assert USER_NICK in rooms.JOINED_ROOMS[ROOM_JID]["nicks"]

    # User leaves.
    await rooms.on_muc_presence(fake_bot, make_presence(USER_NICK, type_="unavailable"))
    assert USER_NICK not in rooms.JOINED_ROOMS[ROOM_JID]["nicks"]

    # Bot leaves.
    await rooms.on_muc_presence(
        fake_bot,
        make_presence(
            BOT_NICK,
            role="moderator",
            jid=BOT_JID,
            affiliation="admin",
            type_="unavailable",
        ),
    )
    assert ROOM_JID not in rooms.JOINED_ROOMS


@pytest.mark.asyncio
async def test_bot_has_privilege():
    rooms.JOINED_ROOMS["room"] = {"affiliation": "owner"}
    assert rooms.bot_has_privilege("room") is True
    rooms.JOINED_ROOMS["room"] = {"affiliation": "member"}
    assert rooms.bot_has_privilege("room") is False
    assert rooms.bot_has_privilege("room_notexist") is False


@pytest.mark.asyncio
async def test_room_status_helpers(fake_bot):
    fake_bot.db.rooms.status_get = AsyncMock(return_value={"a": 1})
    assert await rooms.room_status_get(fake_bot, "room", "a") == {"a": 1}
    fake_bot.db.rooms.status_set = AsyncMock()
    await rooms.room_status_set(fake_bot, "room", "x", 123)
    fake_bot.db.rooms.status_set.assert_called_with("room", "x", 123)
    fake_bot.db.rooms.status_delete = AsyncMock()
    await rooms.room_status_delete(fake_bot, "room", "p")
    fake_bot.db.rooms.status_delete.assert_called_with("room", "p")


@pytest.mark.asyncio
async def test_is_valid_room_jid_success(fake_bot, fake_msg):
    with patch("core_plugins.rooms.is_valid_muc_domain",
               AsyncMock(return_value=True)):
        jid = "room@conference.domain"
        assert await rooms.is_valid_room_jid(fake_bot, jid, fake_msg) is True


@pytest.mark.asyncio
async def test_is_valid_room_jid_failures(fake_bot, fake_msg):
    with patch("core_plugins.rooms.is_valid_muc_domain",
               AsyncMock(return_value=False)):
        assert await rooms.is_valid_room_jid(fake_bot,
                                             "room/conference",
                                             fake_msg) is False
        assert await rooms.is_valid_room_jid(fake_bot,
                                             "room",
                                             fake_msg) is False
        assert await rooms.is_valid_room_jid(fake_bot,
                                             "@domain",
                                             fake_msg) is False
        # Simulate failed domain check
        assert await rooms.is_valid_room_jid(fake_bot,
                                             "room@domain",
                                             fake_msg) is False


@pytest.mark.asyncio
async def test_autojoin_rooms(fake_bot):
    fake_bot.db.rooms.list = AsyncMock(
        return_value=[("room1@conf", "BotNick", True, "joined"),
                      ("room2@conf", "BotNick", False, "left")]
    )
    fake_bot.plugin["xep_0045"].join_muc = AsyncMock()
    await rooms.autojoin_rooms(fake_bot)
    assert "room1@conf" in rooms.JOINED_ROOMS
    assert "room2@conf" not in rooms.JOINED_ROOMS


@pytest.mark.asyncio
async def test_set_room_control_defaults(fake_bot):
    # All plugins -> dict
    room = "test@conf"
    fake_bot.db.users.plugin = lambda plugin: types.SimpleNamespace(
        get_global=AsyncMock(return_value={}),
        set_global=AsyncMock())
    await rooms.set_room_control_defaults(fake_bot, room)


@pytest.mark.asyncio
async def test_set_room_control_defaults_uses_configured_defaults(fake_bot, monkeypatch):
    room = "test@conf"
    stores = {}

    def plugin_store(plugin):
        store = stores.setdefault(
            plugin,
            types.SimpleNamespace(data={}),
        )

        async def get_global(key, default=None):
            return store.data.get(key, default)

        async def set_global(key, value):
            store.data[key] = value

        return types.SimpleNamespace(get_global=get_global, set_global=set_global)

    fake_bot.db.users.plugin = plugin_store
    monkeypatch.setitem(
        rooms.config,
        "room_plugin_defaults",
        {"pin": False, "xkcd": True, "info": False, "missing": True},
    )

    await rooms.set_room_control_defaults(fake_bot, room)

    assert stores["pin"].data["PIN"] == {}
    assert stores["xkcd"].data["XKCD"] == {room: True}
    assert stores["dice"].data["DICE"] == {room: True}
    assert stores["information"].data["INFORMATION"] == {}
    assert stores["birthday_notify"].data["birthday_notify"] == {}


def test_get_room_plugin_defaults_merges_and_ignores_bad_keys(monkeypatch):
    monkeypatch.setitem(
        rooms.config,
        "room_plugin_defaults",
        {"xkcd": True, "INFO": False, "unknown": True},
    )
    rooms._WARNED_ROOM_PLUGIN_DEFAULT_KEYS.clear()

    defaults = rooms.get_room_plugin_defaults()

    assert defaults["xkcd"] is True
    assert defaults["information"] is False
    assert defaults["pin"] is True
    assert "unknown" not in defaults


@pytest.mark.asyncio
async def test_cmd_room_setdefaults(fake_bot, fake_msg):
    # Not in joined rooms
    await rooms.cmd_room_setdefaults(fake_bot, "jid", "nick", [],
                                     fake_msg, False)
    # Now simulate the room present and in DB
    room_jid = fake_msg["from"].bare
    rooms.JOINED_ROOMS[room_jid] = {}
    fake_bot.db.rooms.get = AsyncMock(
        return_value=(room_jid, "BotNick", True, None))
    with patch("core_plugins.rooms.set_room_control_defaults", AsyncMock()):
        await rooms.cmd_room_setdefaults(fake_bot, "jid", "nick", [],
                                         fake_msg, False)
        # Error case: trigger inside the try/except block!
        with patch("core_plugins.rooms.set_room_control_defaults",
                   AsyncMock(side_effect=Exception("fail-setdefaults"))):
            await rooms.cmd_room_setdefaults(fake_bot, "jid", "nick", [],
                                             fake_msg, False)
            assert "Error restoring defaults" in fake_bot.reply_error.call_args.args[1]


@pytest.mark.asyncio
async def test_cmd_room_plugins(fake_bot, fake_msg):
    room_jid = fake_msg["from"].bare
    rooms.JOINED_ROOMS[room_jid] = {}
    fake_bot.db.users.plugin = lambda plugin: types.SimpleNamespace(
        get_global=AsyncMock(return_value={})
    )
    await rooms.cmd_room_plugins(fake_bot, "jid", "nick", [], fake_msg, False)


@pytest.mark.asyncio
async def test_rooms_add(fake_bot, fake_msg):
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.db.rooms.add = AsyncMock()
    with patch("core_plugins.rooms.set_room_control_defaults", AsyncMock()):
        with patch("core_plugins.rooms.is_valid_room_jid",
                   AsyncMock(return_value=True)):
            msg = dict(fake_msg)
            msg["from"].bare = "room@conference.domain"
            await rooms.rooms_add(fake_bot, "s", "s",
                                  ["room@conference.domain", "BotNick"],
                                  msg, False)


@pytest.mark.asyncio
async def test_rooms_add_already_exists(fake_bot, fake_msg):
    fake_bot.db.rooms.get = AsyncMock(return_value=(1, 2, 3, 4))
    with patch("core_plugins.rooms.is_valid_room_jid",
               AsyncMock(return_value=True)):
        await rooms.rooms_add(fake_bot, "s", "s",
                              ["room@conference.domain", "BotNick"],
                              fake_msg, False)


@pytest.mark.asyncio
async def test_rooms_update(fake_bot, fake_msg):
    fake_bot.db.rooms.update = AsyncMock()
    with patch("core_plugins.rooms.is_valid_room_jid",
               AsyncMock(return_value=True)):
        await rooms.rooms_update(fake_bot, "jid", "nick",
                                 ["room@conference.domain", "nick",
                                  "OtherBot"], fake_msg, False)
        await rooms.rooms_update(fake_bot, "jid", "nick",
                                 ["room@conference.domain",
                                  "autojoin", "yes"], fake_msg, False)
        await rooms.rooms_update(fake_bot, "jid", "nick",
                                 ["room@conference.domain",
                                  "badfield", "xxx"], fake_msg, False)


@pytest.mark.asyncio
async def test_rooms_delete(fake_bot, fake_msg):
    fake_bot.db.rooms.get = AsyncMock(return_value=(1, 2, 3, 4))
    fake_bot.db.rooms.delete = AsyncMock()
    with patch("core_plugins.rooms.is_valid_room_jid",
               AsyncMock(return_value=True)):
        # room joined
        room_jid = "room@conference.domain"
        rooms.JOINED_ROOMS[room_jid] = {"nick": "BotNick"}
        fake_bot.presence.joined_rooms[room_jid] = "BotNick"
        await rooms.rooms_delete(fake_bot, "jid", "nick", [room_jid],
                                 fake_msg, False)
        # room not joined, but in db
        # Restore for test coverage, since previous call popped it
        rooms.JOINED_ROOMS[room_jid] = {"nick": "BotNick"}
        await rooms.rooms_delete(fake_bot, "jid", "nick", [room_jid],
                                 fake_msg, False)
        # DB removal failure
        fake_bot.db.rooms.get = AsyncMock(side_effect=Exception("db error"))
        await rooms.rooms_delete(fake_bot, "jid", "nick", [room_jid],
                                 fake_msg, False)


class DummyPluginStore(dict):
    async def get_global(self, key, default=None):
        return self.get(key, default)

    async def set_global(self, key, value):
        self[key] = value


@pytest.mark.asyncio
async def test_rooms_delete_cleans_room_plugin_state(fake_bot, fake_msg, monkeypatch):
    room_jid = "room@conference.domain"
    other_room = "other@conference.domain"
    feed_keep = "https://example.org/keep.xml"
    feed_drop = "https://example.org/drop.xml"

    stores = {
        "rss": DummyPluginStore({
            "RSS": {
                feed_keep: {"rooms": [room_jid, other_room], "period": 42},
                feed_drop: {"rooms": [room_jid], "period": 84},
                "https://example.org/other.xml": {"rooms": [other_room]},
            }
        }),
        "xkcd": DummyPluginStore({
            "XKCD": {
                room_jid: True,
                other_room: True,
                "rooms": [room_jid, other_room],
            }
        }),
        "pin": DummyPluginStore({
            "PIN": {room_jid: True, other_room: True},
            "PIN_DATA": {room_jid: {"pins": [1]}, other_room: {"pins": [2]}},
        }),
        "poll": DummyPluginStore({
            "POLL": {room_jid: False, other_room: True},
            "POLL_DATA": {
                "rooms": {
                    room_jid: {"polls": {"1": {}}},
                    other_room: {"polls": {"2": {}}},
                }
            },
        }),
    }
    fake_bot.db.users.plugin.side_effect = lambda name: stores.setdefault(
        name,
        DummyPluginStore(),
    )
    cancel_feed_task = AsyncMock()
    monkeypatch.setattr(rss_plugin, "_cancel_feed_task", cancel_feed_task)

    async def cleanup_room_state(room_jid):
        return {
            "rss": await rss_plugin.cleanup_room_state(fake_bot, room_jid),
            "xkcd": await xkcd_plugin.cleanup_room_state(fake_bot, room_jid),
            "pin": await pin_plugin.cleanup_room_state(fake_bot, room_jid),
            "poll": await poll_plugin.cleanup_room_state(fake_bot, room_jid),
        }

    fake_bot.bot_plugins.cleanup_room_state = AsyncMock(
        side_effect=cleanup_room_state
    )
    fake_bot.db.rooms.get = AsyncMock(return_value=(room_jid, "BotNick", True, None))
    fake_bot.db.rooms.delete = AsyncMock()

    with patch("core_plugins.rooms.is_valid_room_jid", AsyncMock(return_value=True)):
        await rooms.rooms_delete(fake_bot, "jid", "nick", [room_jid], fake_msg, False)

    assert stores["rss"]["RSS"] == {
        feed_keep: {"rooms": [other_room], "period": 42},
        "https://example.org/other.xml": {"rooms": [other_room]},
    }
    cancel_feed_task.assert_called_once_with(fake_bot, feed_drop)

    assert stores["xkcd"]["XKCD"] == {
        other_room: True,
        "rooms": [other_room],
    }
    assert stores["pin"]["PIN"] == {other_room: True}
    assert stores["pin"]["PIN_DATA"] == {other_room: {"pins": [2]}}
    assert stores["poll"]["POLL"] == {other_room: True}
    assert stores["poll"]["POLL_DATA"]["rooms"] == {
        other_room: {"polls": {"2": {}}},
    }
    fake_bot.db.rooms.delete.assert_awaited_once_with(room_jid)


@pytest.mark.asyncio
async def test_rooms_delete_reports_not_used_without_delete_log(fake_bot, fake_msg):
    room_jid = "room@conference.domain"
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.db.rooms.delete = AsyncMock()

    with patch("core_plugins.rooms.is_valid_room_jid", AsyncMock(return_value=True)), \
            patch("core_plugins.rooms.audit_event", AsyncMock()) as audit, \
            patch("core_plugins.rooms.log.info") as log_info:
        await rooms.rooms_delete(fake_bot, "jid", "nick", [room_jid], fake_msg, False)

    fake_bot.db.rooms.delete.assert_not_called()
    audit.assert_not_awaited()
    fake_bot.reply_info.assert_called_once_with(
        fake_msg,
        f"Room is not used by this bot: {room_jid}",
    )
    assert not any(
        "Deleted room" in str(call.args[0])
        for call in log_info.call_args_list
    )


@pytest.mark.asyncio
async def test_rooms_delete_cleans_stale_plugin_state_without_db_room(fake_bot, fake_msg):
    room_jid = "room@conference.domain"
    other_room = "other@conference.domain"
    stores = {
        "xkcd": DummyPluginStore({"XKCD": {room_jid: True, other_room: True}}),
    }
    fake_bot.db.users.plugin.side_effect = lambda name: stores.setdefault(
        name,
        DummyPluginStore(),
    )
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.db.rooms.delete = AsyncMock()

    async def cleanup_room_state(room_jid):
        return {
            "xkcd": await xkcd_plugin.cleanup_room_state(fake_bot, room_jid),
        }

    fake_bot.bot_plugins.cleanup_room_state = AsyncMock(
        side_effect=cleanup_room_state
    )

    with patch("core_plugins.rooms.is_valid_room_jid", AsyncMock(return_value=True)), \
            patch("core_plugins.rooms.audit_event", AsyncMock()) as audit, \
            patch("core_plugins.rooms.log.info") as log_info:
        await rooms.rooms_delete(fake_bot, "jid", "nick", [room_jid], fake_msg, False)

    assert stores["xkcd"]["XKCD"] == {other_room: True}
    fake_bot.db.rooms.delete.assert_not_called()
    audit.assert_awaited_once()
    assert audit.await_args.args[1] == "room_plugin_state_cleaned"
    fake_bot.reply.assert_called_once_with(
        fake_msg,
        f"🧹 Room was not stored, but stale plugin state was cleaned: {room_jid}",
    )
    assert any(
        "Cleaned stale plugin state" in str(call.args[0])
        for call in log_info.call_args_list
    )
    assert not any(
        "Deleted room" in str(call.args[0])
        for call in log_info.call_args_list
    )


@pytest.mark.asyncio
async def test_rooms_delete_suppresses_delayed_presence_until_rejoin(fake_bot, fake_msg):
    room_jid = "room@conference.domain"
    fake_bot.db.rooms.get = AsyncMock(return_value=(room_jid, "BotNick", True, None))
    fake_bot.db.rooms.delete = AsyncMock()
    fake_bot.plugin["xep_0045"].leave_muc = AsyncMock()
    rooms.JOINED_ROOMS[room_jid] = {"nick": "BotNick", "nicks": {}}
    fake_bot.presence.joined_rooms[room_jid] = "BotNick"

    with patch("core_plugins.rooms.is_valid_room_jid", AsyncMock(return_value=True)):
        await rooms.rooms_delete(fake_bot, "jid", "nick", [room_jid], fake_msg, False)

    assert room_jid not in rooms.JOINED_ROOMS
    assert room_jid not in fake_bot.presence.joined_rooms
    fake_bot.plugin["xep_0045"].leave_muc.assert_awaited_once_with(room_jid, "BotNick")

    await rooms.on_muc_presence(
        fake_bot,
        make_presence("OtherNick", room=room_jid, jid="other@example.org"),
    )

    assert room_jid not in rooms.JOINED_ROOMS

    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.db.rooms.add = AsyncMock()
    fake_bot.plugin["xep_0045"].join_muc = AsyncMock()
    with patch("core_plugins.rooms.is_valid_room_jid", AsyncMock(return_value=True)):
        await rooms.rooms_join(fake_bot, "jid", "nick", [room_jid, "BotNick"], fake_msg, False)

    await rooms.on_muc_presence(
        fake_bot,
        make_presence("OtherNick", room=room_jid, jid="other@example.org"),
    )

    assert rooms.JOINED_ROOMS[room_jid]["nicks"]["OtherNick"]["jid"] == "other@example.org"


@pytest.mark.asyncio
async def test_rooms_delete_leaves_presence_only_runtime_entry(fake_bot, fake_msg):
    room_jid = "room@conference.domain"
    fake_bot.db.rooms.get = AsyncMock(return_value=(room_jid, "BotNick", True, None))
    fake_bot.db.rooms.delete = AsyncMock()
    fake_bot.presence.joined_rooms[room_jid] = "BotNick"
    fake_bot.plugin["xep_0045"].leave_muc = AsyncMock()

    with patch("core_plugins.rooms.is_valid_room_jid", AsyncMock(return_value=True)):
        await rooms.rooms_delete(fake_bot, "jid", "nick", [room_jid], fake_msg, False)

    assert room_jid not in rooms.JOINED_ROOMS
    assert room_jid not in fake_bot.presence.joined_rooms
    fake_bot.plugin["xep_0045"].leave_muc.assert_awaited_once_with(room_jid, "BotNick")


@pytest.mark.asyncio
async def test_rooms_list(fake_bot):
    fake_bot.db.rooms.list = AsyncMock(return_value=[
        ("room@conference.a", "nick1", True, "stat1"),
        ("room@conference.b", "nick2", False, "{}")
    ])
    rooms.JOINED_ROOMS["room@conference.a"] = {
        "nick": "nick1", "affiliation": "admin", "role": "owner",
        "autojoin": True, "status": "stat1"
    }
    await rooms.rooms_list(fake_bot, "jid", "nick", [], MagicMock(), False)
    listing = fake_bot.reply.call_args.args[1]
    assert "Counts: stored=2 | joined=1" in listing
    assert any("room@conference.a" in line for line in listing)

    # Test with no rows and no joined rooms.
    fake_bot.db.rooms.list = AsyncMock(return_value=[])
    rooms.JOINED_ROOMS.clear()
    await rooms.rooms_list(fake_bot, "jid", "nick", [], MagicMock(), False)
    listing = fake_bot.reply.call_args.args[1]
    assert "Counts: stored=0 | joined=0" in listing
    assert "Stored rooms: —" in listing
    assert "Joined rooms: —" in listing


@pytest.mark.asyncio
async def test_rooms_join_leave_and_sync(fake_bot, fake_msg):
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.db.rooms.add = AsyncMock()
    fake_bot.plugin["xep_0045"].join_muc = AsyncMock()
    fake_bot.presence.joined_rooms = {}
    with patch("core_plugins.rooms.is_valid_room_jid",
               AsyncMock(return_value=True)):
        await rooms.rooms_join(fake_bot, "jid", "nick",
                               ["room@conf", "BotNick"], fake_msg, False)
        await rooms.rooms_join(fake_bot, "jid", "nick",
                               ["room@conf"], fake_msg, False)

    # leave
    room_jid = "room@conf"
    rooms.JOINED_ROOMS[room_jid] = {"nick": "BotNick"}
    fake_bot.presence.joined_rooms[room_jid] = "BotNick"
    fake_bot.plugin["xep_0045"].leave_muc = MagicMock()
    with patch("core_plugins.rooms.is_valid_room_jid",
               AsyncMock(return_value=True)):
        await rooms.rooms_leave(fake_bot, "jid", "nick", [room_jid],
                                fake_msg, False)

    # sync
    fake_bot.db.rooms.list = AsyncMock(return_value=[
        ("room@c1", "Bot", True, "state1"),
        ("room@c2", "Bot2", False, "state2"),
    ])
    fake_bot.plugin["xep_0045"].join_muc = AsyncMock()
    rooms.JOINED_ROOMS["room@c1"] = {"nick": "Bot"}
    with patch("core_plugins.rooms.is_valid_room_jid",
               AsyncMock(return_value=True)):
        await rooms.rooms_sync(fake_bot, "jid", "nick", [], fake_msg, False)


@pytest.mark.asyncio
async def test_rooms_leave_reports_noop_state(fake_bot, fake_msg):
    room_jid = "room@conference.domain"
    unknown_room = "unknown@conference.domain"
    fake_bot.db.rooms.get = AsyncMock(
        side_effect=lambda jid: (room_jid, "BotNick", True, None)
        if jid == room_jid else None
    )
    fake_bot.plugin["xep_0045"].leave_muc = AsyncMock()
    rooms.JOINED_ROOMS[room_jid] = {"nick": "BotNick"}
    fake_bot.presence.joined_rooms[room_jid] = "BotNick"

    with patch("core_plugins.rooms.is_valid_room_jid",
               AsyncMock(return_value=True)):
        await rooms.rooms_leave(fake_bot, "jid", "nick", [room_jid],
                                fake_msg, False)
        await rooms.rooms_leave(fake_bot, "jid", "nick", [room_jid],
                                fake_msg, False)
        await rooms.rooms_leave(fake_bot, "jid", "nick", [unknown_room],
                                fake_msg, False)

    fake_bot.plugin["xep_0045"].leave_muc.assert_awaited_once_with(
        room_jid, "BotNick"
    )
    replies = [call.args[1] for call in fake_bot.reply.call_args_list]
    assert f"🚶 Left room: {room_jid}" in replies
    assert f"ℹ️ Room already left: {room_jid}" in replies
    assert f"ℹ️ Room is not used by this bot: {unknown_room}" in replies
    fake_bot.presence.broadcast.assert_called_once()
    assert unknown_room not in rooms._LEAVING_ROOMS


@pytest.mark.asyncio
async def test_is_valid_muc_domain_true_false(fake_bot):
    xmpp_plugin = MagicMock()
    xmpp_plugin.get_info = AsyncMock(
        return_value={"disco_info": {"features":
                                     ["http://jabber.org/protocol/muc"]}})
    fake_bot.__getitem__.return_value = xmpp_plugin
    fake_bot.__getitem__ = MagicMock(return_value=xmpp_plugin)
    assert await rooms.is_valid_muc_domain(fake_bot, "conference.domain")
    xmpp_plugin.get_info = AsyncMock(side_effect=Exception("fail"))
    assert not await rooms.is_valid_muc_domain(fake_bot, "conference.domain")


@pytest.mark.asyncio
async def test_on_load_restores_reload_rooms_and_registers_presence_handler(fake_bot):
    fake_bot._reload_rooms = {
        "room1@conf": {"nick": "RuntimeNick", "autojoin": None, "status": None},
        "room2@conf": {"autojoin": False, "status": "away"},
    }
    fake_bot.db.rooms.get = AsyncMock(side_effect=[
        ("room1@conf", "DbNick", True, "chat"),
        ("room2@conf", "DbNick2", True, "xa"),
    ])
    fake_bot.plugin["xep_0045"].join_muc = AsyncMock()

    await rooms.on_load(fake_bot)

    assert not hasattr(fake_bot, "_reload_rooms")
    assert fake_bot.bot_plugins.register_event.call_count == 4
    assert rooms.JOINED_ROOMS["room1@conf"] == {
        "nick": "RuntimeNick",
        "autojoin": True,
        "status": "chat",
        "affiliation": "unknown",
        "role": "unknown",
        "nicks": {},
    }
    assert rooms.JOINED_ROOMS["room2@conf"]["nick"] == "DbNick2"
    assert rooms.JOINED_ROOMS["room2@conf"]["autojoin"] is False
    assert rooms.JOINED_ROOMS["room2@conf"]["status"] == "away"
    assert fake_bot.presence.joined_rooms == {
        "room1@conf": "RuntimeNick",
        "room2@conf": "DbNick2",
    }
    fake_bot.plugin["xep_0045"].join_muc.assert_any_await(
        "room1@conf", "RuntimeNick", pshow="chat", pstatus="online"
    )


@pytest.mark.asyncio
async def test_on_load_missing_dependencies_and_normal_startup(fake_bot):
    fake_bot.plugin["xep_0045"] = None
    await rooms.on_load(fake_bot)
    assert fake_bot.bot_plugins.register_event.call_count == 4

    fake_bot.bot_plugins.register_event.reset_mock()
    fake_bot.plugin["xep_0045"] = MagicMock()
    fake_bot.db.rooms = None
    await rooms.on_load(fake_bot)
    assert fake_bot.bot_plugins.register_event.call_count == 4

    fake_bot.db.rooms = MagicMock()
    fake_bot._reload_rooms = None
    with patch("core_plugins.rooms.autojoin_rooms", AsyncMock()) as autojoin:
        await rooms.on_load(fake_bot)
        autojoin.assert_awaited_once_with(fake_bot)


@pytest.mark.asyncio
async def test_room_feature_toggle_branches(fake_bot, fake_msg, monkeypatch):
    patch_reply_methods(fake_bot)
    fake_bot.prefix = ","
    fake_msg["type"] = "chat"

    await rooms._handle_room_feature_toggle(fake_bot, "admin@example.org", fake_msg, False, [], enabled=True)
    fake_bot.reply_usage.assert_called_with(fake_msg, ",rooms enable [<room_jid>] <plugin>")

    fake_msg["from"].bare = "missing@conf"
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    await rooms._handle_room_feature_toggle(fake_bot, "admin@example.org", fake_msg, False, ["missing@conf", "pin"], enabled=True)
    fake_bot.reply_error.assert_called_with(fake_msg, "Room 'missing@conf' is not currently joined or stored.")

    fake_bot.db.rooms.get = AsyncMock(return_value=(ROOM_JID, BOT_NICK, True, None))
    fake_msg["from"].bare = "room@conference.test"
    fake_msg["from"].resource = "Nick"
    rooms.JOINED_ROOMS[fake_msg["from"].bare] = {"nick": "BotNick", "nicks": {}}
    monkeypatch.setattr(rooms, "get_room_feature", AsyncMock(side_effect=KeyError))
    await rooms._handle_room_feature_toggle(fake_bot, "admin@example.org", fake_msg, False, ["unknown"], enabled=True)
    assert "Unknown room plugin" in fake_bot.reply_warn.call_args.args[1]

    previous = types.SimpleNamespace(name="pin", enabled=True)
    state = types.SimpleNamespace(name="pin", enabled=True)
    monkeypatch.setattr(rooms, "get_room_feature", AsyncMock(return_value=previous))
    monkeypatch.setattr(rooms, "set_room_feature", AsyncMock(return_value=state))
    monkeypatch.setattr(rooms, "format_room_feature_line", lambda state: "pin: enabled")
    await rooms._handle_room_feature_toggle(fake_bot, "admin@example.org", fake_msg, False, ["pin"], enabled=True)
    assert "already enabled" in fake_bot.reply_info.call_args.args[1]

    state = types.SimpleNamespace(name="pin", enabled=False)
    monkeypatch.setattr(rooms, "set_room_feature", AsyncMock(return_value=state))
    monkeypatch.setattr(rooms, "audit_event", AsyncMock())
    await rooms._handle_room_feature_toggle(fake_bot, "admin@example.org", fake_msg, False, ["pin"], enabled=False)
    rooms.audit_event.assert_awaited_once()
    assert "pin is now disabled" in fake_bot.reply_ok.call_args.args[1]

@pytest.mark.asyncio
async def test_on_unload_leaves_rooms_and_preserves_reload_snapshot(fake_bot):
    rooms.JOINED_ROOMS.update({
        "room1@conf": {"nick": "BotOne"},
        "room2@conf": {"nick": "BotTwo"},
    })
    fake_bot.presence.joined_rooms = {"room1@conf": "BotOne", "room2@conf": "BotTwo"}

    await rooms.on_unload(fake_bot)

    assert fake_bot._reload_rooms == {
        "room1@conf": {"nick": "BotOne"},
        "room2@conf": {"nick": "BotTwo"},
    }
    fake_bot.plugin["xep_0045"].leave_muc.assert_any_call("room1@conf", "BotOne")
    fake_bot.plugin["xep_0045"].leave_muc.assert_any_call("room2@conf", "BotTwo")
    assert fake_bot.presence.joined_rooms == {}


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


def test_extract_direct_room_invite():
    xml = rooms.ET.fromstring(
        "<message><x xmlns='jabber:x:conference' "
        "jid='NewRoom@conference.test' reason='join us'/></message>"
    )
    msg = InviteMessage("inviter@example.org", xml)

    invite = rooms.extract_room_invite(msg)

    assert invite == {
        "room_jid": "newroom@conference.test",
        "inviter": "inviter@example.org",
        "reason": "join us",
    }


@pytest.mark.asyncio
async def test_handle_room_invite_stores_and_announces(fake_bot, monkeypatch):
    xml = rooms.ET.fromstring(
        "<message><x xmlns='jabber:x:conference' "
        "jid='room2@conference.test'/></message>"
    )
    msg = InviteMessage("inviter@example.org", xml)
    fake_bot.db.conn = None
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.make_message = MagicMock(side_effect=lambda **kwargs: kwargs)
    fake_bot._safe_send_message = AsyncMock()
    fake_bot.audit = AsyncMock()
    monkeypatch.setitem(rooms.config, "room_invites_enabled", True)
    monkeypatch.setitem(rooms.config, "room_invite_notify_jid", "admins@conference.test")
    monkeypatch.setattr(
        rooms,
        "ensure_notification_target_joined",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(rooms, "notification_message_type", lambda bot, target: "groupchat")

    handled = await rooms.handle_room_invite(fake_bot, msg)

    assert handled is True
    assert fake_bot.pending_room_invites[1]["room_jid"] == "room2@conference.test"
    outbound = fake_bot._safe_send_message.await_args.args[0]
    assert outbound["mto"] == "admins@conference.test"
    assert outbound["mtype"] == "groupchat"
    assert "rooms invite accept 1" in outbound["mbody"]


@pytest.mark.asyncio
async def test_rooms_invite_accept_joins_and_removes_pending(fake_bot, fake_msg, monkeypatch):
    fake_bot.db.conn = None
    fake_bot.pending_room_invites = {
        7: {
            "id": 7,
            "room_jid": "room3@conference.test",
            "inviter": "inviter@example.org",
            "reason": "",
            "created_at": 1,
        }
    }
    fake_bot.pending_room_invite_index = {("room3@conference.test", "inviter@example.org"): 7}
    join_invited = AsyncMock()
    monkeypatch.setattr(rooms, "_join_invited_room", join_invited)
    monkeypatch.setattr(rooms, "load_pending_room_invites", AsyncMock(return_value=fake_bot.pending_room_invites))
    monkeypatch.setitem(rooms.config, "room_invites_enabled", True)
    monkeypatch.setitem(rooms.config, "nick", "EnvsBot")

    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["accept", "7"], fake_msg, False)

    join_invited.assert_awaited_once_with(fake_bot, "room3@conference.test", "EnvsBot")
    assert fake_bot.pending_room_invites == {}
    fake_bot.reply_ok.assert_called()


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


@pytest.mark.asyncio
async def test_room_invite_config_and_plugin_helpers(monkeypatch):
    monkeypatch.setitem(rooms.config, "room_invite_notify_jid", " AdminRoom@Conference.Test ")
    monkeypatch.setitem(rooms.config, "version_check_notify_jid", "updates@conference.test")
    monkeypatch.setitem(rooms.config, "owner", "owner@example.org")
    assert rooms.room_invite_notify_target() == "AdminRoom@Conference.Test"
    assert rooms.room_invite_admin_rooms() == {
        "adminroom@conference.test",
        "updates@conference.test",
    }

    monkeypatch.setitem(rooms.config, "room_invite_notify_jid", "")
    assert rooms.room_invite_notify_target() == "updates@conference.test"
    monkeypatch.setitem(rooms.config, "version_check_notify_jid", "")
    assert rooms.room_invite_notify_target() == "owner@example.org"
    monkeypatch.setitem(rooms.config, "owner", "")
    assert rooms.room_invite_notify_target() is None

    monkeypatch.setitem(rooms.config, "room_invite_max_age_days", "bad")
    assert rooms._room_invite_max_age_days() == 30
    monkeypatch.setitem(rooms.config, "room_invite_max_age_days", -1)
    assert rooms._room_invite_max_age_days() == 0
    assert rooms._room_invite_is_expired({"created_at": 1}, now=999999) is False
    monkeypatch.setitem(rooms.config, "room_invite_max_age_days", 1)
    assert rooms._room_invite_is_expired({"created_at": "bad"}, now=999999) is False
    assert rooms._room_invite_is_expired({"created_at": 0}, now=999999) is False
    assert rooms._room_invite_is_expired({"created_at": 100}, now=100 + 86400 + 1) is True

    assert rooms._jid_bare(None) == ""
    assert rooms._jid_bare(types.SimpleNamespace(bare="User@Example.Org")) == "user@example.org"
    assert rooms._invite_inviter_from_attr("room@conf/Nick", "room@conf") == "room@conf/nick"
    assert rooms._invite_inviter_from_attr("User@Example.Org/Device", "room@conf") == "user@example.org"
    assert rooms._invite_inviter_from_attr(None, "room@conf") == ""

    assert rooms._safe_get_plugin(object(), "muc") is None
    assert rooms._safe_get_plugin(PluginStanza(plugins={"muc": RuntimeError("boom")}), "muc") is None
    invite_plugin = {"from": "User@Example.Org/Phone", "reason": "please join"}
    assert rooms._safe_get_plugin(FallbackPluginStanza(invite_plugin), "muc") == invite_plugin
    assert rooms._safe_plugin_value(None, "jid") == ""
    assert rooms._safe_plugin_value({"jid": None}, "jid") == ""
    assert rooms._safe_plugin_value(MappingOnlyPlugin({"jid": "room@conf"}), "jid") == "room@conf"
    assert rooms._safe_plugin_value(ExplodingMappingPlugin(), "jid") == ""

    invite_el = rooms.ET.fromstring(
        "<invite xmlns='http://jabber.org/protocol/muc#user'>"
        "<reason> hello </reason>"
        "</invite>"
    )
    assert rooms._room_invite_reason_from_invite(invite_el) == "hello"
    assert rooms._room_invite_reason_from_invite(rooms.ET.fromstring("<invite />")) == ""


@pytest.mark.asyncio
async def test_extract_room_invite_from_stanza_plugins():
    invite_plugin = {"from": "Room@Conference.Test/Alice", "reason": "mediated"}
    muc_plugin = PluginStanza(plugins={"invite": invite_plugin})
    msg = PluginStanza("Room@Conference.Test/Bot", plugins={"muc": muc_plugin})
    invite = rooms.extract_room_invite(msg)
    assert invite == {
        "room_jid": "room@conference.test",
        "inviter": "room@conference.test/alice",
        "reason": "mediated",
    }

    msg = PluginStanza(
        "Inviter@Example.Org/Phone",
        plugins={"groupchat_invite": {"jid": "Direct@Conference.Test", "reason": "direct"}},
    )
    assert rooms.extract_room_invite(msg) == {
        "room_jid": "direct@conference.test",
        "inviter": "inviter@example.org",
        "reason": "direct",
    }

    msg = PluginStanza(
        "Inviter@Example.Org/Phone",
        plugins={"conference": {"room": "Fallback@Conference.Test"}},
    )
    assert rooms.extract_room_invite(msg)["room_jid"] == "fallback@conference.test"

    assert rooms._room_invite_from_muc_plugin(PluginStanza("room@conf/Bot", plugins={"muc": None})) is None
    assert rooms._room_invite_from_direct_plugin(PluginStanza(plugins={"groupchat_invite": {}})) is None


@pytest.mark.asyncio
async def test_room_invite_database_lifecycle(fake_bot, monkeypatch):
    import aiosqlite

    monkeypatch.setitem(rooms.config, "room_invite_max_age_days", 1)
    conn = await aiosqlite.connect(":memory:")
    fake_bot.db.conn = conn
    try:
        await rooms.setup_room_invites_db(fake_bot)
        now = int(rooms.time.time())
        await conn.execute(
            "INSERT INTO room_invites (room_jid, inviter, reason, created_at) VALUES (?, ?, ?, ?)",
            ("active@conference.test", "inviter@example.org", None, now),
        )
        await conn.execute(
            "INSERT INTO room_invites (room_jid, inviter, reason, created_at) VALUES (?, ?, ?, ?)",
            ("Old@Conference.Test", "Old@Example.Org", "expired", now - 3 * 86400),
        )
        await conn.commit()

        pending = await rooms.load_pending_room_invites(fake_bot)
        assert list(pending) == [1]
        assert pending[1]["room_jid"] == "active@conference.test"
        assert pending[1]["reason"] == ""
        assert fake_bot.pending_room_invite_index == {("active@conference.test", "inviter@example.org"): 1}

        # Duplicate insert path reloads the already persisted row after UNIQUE failure.
        fake_bot.pending_room_invites = {}
        fake_bot.pending_room_invite_index = {}
        duplicate = await rooms._store_pending_room_invite(
            fake_bot,
            "active@conference.test",
            "inviter@example.org",
            "ignored",
        )
        assert duplicate["id"] == 1

        stored = await rooms._store_pending_room_invite(
            fake_bot,
            "new@conference.test",
            "new@example.org",
            "new reason",
        )
        assert stored["id"] >= 2
        removed = await rooms._delete_pending_room_invite(fake_bot, stored["id"])
        assert removed["room_jid"] == "new@conference.test"
        assert ("new@conference.test", "new@example.org") not in fake_bot.pending_room_invite_index

        await conn.execute(
            "INSERT INTO room_invites (room_jid, inviter, reason, created_at) VALUES (?, ?, ?, ?)",
            ("FetchOnly@Conference.Test", "Fetch@Example.Org", "row path", now),
        )
        await conn.commit()
        row_id = (await (await conn.execute("SELECT MAX(id) FROM room_invites")).fetchone())[0]
        fake_bot.pending_room_invites = {}
        fetched = await rooms._delete_pending_room_invite(fake_bot, row_id)
        assert fetched["room_jid"] == "fetchonly@conference.test"

        count = await rooms.cleanup_all_room_invites(fake_bot)
        assert count >= 1
        assert fake_bot.pending_room_invites == {}
        assert fake_bot.pending_room_invite_index == {}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_room_invite_runtime_lifecycle_without_database(fake_bot, monkeypatch):
    fake_bot.db.conn = None
    fake_bot.pending_room_invites = "invalid"
    fake_bot.pending_room_invite_index = "invalid"
    assert await rooms.load_pending_room_invites(fake_bot) == {}

    monkeypatch.setitem(rooms.config, "room_invite_max_age_days", 1)
    fresh = await rooms._store_pending_room_invite(fake_bot, "room@conf", "user@example.org", "hi")
    assert fresh["id"] == 1
    assert await rooms._store_pending_room_invite(fake_bot, "room@conf", "user@example.org", "hi") == fresh

    fresh["created_at"] = int(rooms.time.time()) - 3 * 86400
    replacement = await rooms._store_pending_room_invite(fake_bot, "room@conf", "user@example.org", "new")
    assert replacement["id"] == 1
    assert replacement["reason"] == "new"

    old = await rooms._store_pending_room_invite(fake_bot, "old@conf", "old@example.org", "old")
    old["created_at"] = int(rooms.time.time()) - 3 * 86400
    assert await rooms.cleanup_expired_room_invites(fake_bot) == 1

    monkeypatch.setitem(rooms.config, "room_invite_max_age_days", 0)
    assert await rooms.cleanup_expired_room_invites(fake_bot) == 0
    assert await rooms.cleanup_all_room_invites(fake_bot) == 1


@pytest.mark.asyncio
async def test_room_invite_notification_and_handle_branches(fake_bot, monkeypatch):
    fake_bot.db.conn = None
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.make_message = MagicMock(side_effect=lambda **kwargs: kwargs)
    fake_bot._safe_send_message = AsyncMock()
    monkeypatch.setitem(rooms.config, "room_invite_notify_jid", "")
    monkeypatch.setitem(rooms.config, "version_check_notify_jid", "")
    monkeypatch.setitem(rooms.config, "owner", "")
    await rooms._notify_room_invite(fake_bot, "no target")
    fake_bot._safe_send_message.assert_not_called()

    monkeypatch.setitem(rooms.config, "room_invite_notify_jid", "admins@conference.test")
    monkeypatch.setattr(rooms, "ensure_notification_target_joined", AsyncMock(return_value=True))
    monkeypatch.setattr(rooms, "notification_message_type", lambda bot, target: "groupchat")
    await rooms._notify_room_invite(fake_bot, "body")
    assert fake_bot._safe_send_message.await_args.args[0]["mtype"] == "groupchat"

    empty_msg = InviteMessage("inviter@example.org", rooms.ET.fromstring("<message />"))
    assert await rooms.handle_room_invite(fake_bot, empty_msg) is False

    monkeypatch.setitem(rooms.config, "room_invites_enabled", False)
    invalid_msg = InviteMessage(
        "inviter@example.org",
        rooms.ET.fromstring("<message><x xmlns='jabber:x:conference' jid='bad/room'/></message>"),
    )
    assert await rooms.handle_room_invite(fake_bot, invalid_msg) is True
    monkeypatch.setitem(rooms.config, "room_invites_enabled", True)

    assert await rooms.handle_room_invite(fake_bot, invalid_msg) is True
    assert "Ignored invalid room invite" in fake_bot._safe_send_message.await_args.args[0]["mbody"]

    joined_msg = InviteMessage(
        "inviter@example.org",
        rooms.ET.fromstring("<message><x xmlns='jabber:x:conference' jid='joined@conference.test'/></message>"),
    )
    rooms.JOINED_ROOMS["joined@conference.test"] = {"nick": "Bot"}
    assert await rooms.handle_room_invite(fake_bot, joined_msg) is True

    stored_msg = InviteMessage(
        "inviter@example.org",
        rooms.ET.fromstring("<message><x xmlns='jabber:x:conference' jid='stored@conference.test'/></message>"),
    )
    fake_bot.db.rooms.get = AsyncMock(return_value=("stored@conference.test", "Bot", True, None))
    assert await rooms.handle_room_invite(fake_bot, stored_msg) is True

    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    monkeypatch.setattr(rooms, "_store_pending_room_invite", AsyncMock(return_value=None))
    pending_msg = InviteMessage(
        "inviter@example.org",
        rooms.ET.fromstring("<message><x xmlns='jabber:x:conference' jid='pending@conference.test'/></message>"),
    )
    assert await rooms.handle_room_invite(fake_bot, pending_msg) is True


@pytest.mark.asyncio
async def test_room_invite_event_handlers(fake_bot, monkeypatch):
    handled = AsyncMock(return_value=True)
    monkeypatch.setattr(rooms, "handle_room_invite", handled)
    await rooms.on_room_invite_message(fake_bot, {"type": "groupchat"})
    handled.assert_not_awaited()

    class FallbackTypeMessage(dict):
        def __getitem__(self, key):
            raise KeyError(key)

        def get(self, key, default=None):
            return "normal" if key == "type" else default

    await rooms.on_room_invite_message(fake_bot, FallbackTypeMessage())
    handled.assert_awaited_once()

    handled.reset_mock()
    handled.return_value = False
    await rooms.on_room_invite(fake_bot, MagicMock())
    handled.assert_awaited_once()


@pytest.mark.asyncio
async def test_join_invited_room_adds_or_updates_room(fake_bot, monkeypatch):
    fake_bot.plugin["xep_0045"].join_muc = AsyncMock()
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.db.rooms.add = AsyncMock()
    fake_bot.db.rooms.update = AsyncMock()
    defaults = AsyncMock()
    monkeypatch.setattr(rooms, "set_room_control_defaults", defaults)

    await rooms._join_invited_room(fake_bot, "new@conference.test", "BotNick")
    fake_bot.plugin["xep_0045"].join_muc.assert_awaited_with(
        "new@conference.test",
        "BotNick",
        pshow="chat",
        pstatus="online",
    )
    fake_bot.db.rooms.add.assert_awaited_once_with("new@conference.test", "BotNick", True)
    assert rooms.JOINED_ROOMS["new@conference.test"]["autojoin"] is True
    assert fake_bot.presence.joined_rooms["new@conference.test"] == "BotNick"
    fake_bot.presence.broadcast.assert_called()
    defaults.assert_awaited_with(fake_bot, "new@conference.test")

    fake_bot.db.rooms.get = AsyncMock(return_value=("existing@conference.test", "Old", False, None))
    await rooms._join_invited_room(fake_bot, "existing@conference.test", "BotNick")
    fake_bot.db.rooms.update.assert_awaited_with("existing@conference.test", nick="BotNick", autojoin=True)


@pytest.mark.asyncio
async def test_on_ready_loads_and_cleans_invites(fake_bot, monkeypatch):
    load = AsyncMock(return_value={})
    cleanup = AsyncMock(return_value=0)
    monkeypatch.setattr(rooms, "load_pending_room_invites", load)
    monkeypatch.setattr(rooms, "cleanup_expired_room_invites", cleanup)

    await rooms.on_ready(fake_bot)

    load.assert_awaited_once_with(fake_bot)
    cleanup.assert_awaited_once_with(fake_bot)


@pytest.mark.asyncio
async def test_rooms_invite_list_empty_shows_none(fake_bot, fake_msg, monkeypatch):
    monkeypatch.setitem(rooms.config, "room_invites_enabled", True)
    fake_bot.pending_room_invites = {}
    monkeypatch.setattr(
        rooms,
        "load_pending_room_invites",
        AsyncMock(return_value=fake_bot.pending_room_invites),
    )
    monkeypatch.setattr(rooms, "cleanup_expired_room_invites", AsyncMock(return_value=0))

    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["list"], fake_msg, False)

    assert fake_bot.reply.call_args.args[1] == ["📨 Pending Room Invites", "None"]


@pytest.mark.asyncio
async def test_rooms_invite_command_list_cleanup_and_errors(fake_bot, fake_msg, monkeypatch):
    monkeypatch.setitem(rooms.config, "room_invites_enabled", False)
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["list"], fake_msg, False)
    fake_bot.reply_error.assert_called()

    monkeypatch.setitem(rooms.config, "room_invites_enabled", True)
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", [], fake_msg, False)
    assert "rooms invite list" in fake_bot.reply.call_args.args[1]

    cleanup_expired = AsyncMock(return_value=2)
    cleanup_all = AsyncMock(return_value=3)
    monkeypatch.setattr(rooms, "cleanup_expired_room_invites", cleanup_expired)
    monkeypatch.setattr(rooms, "cleanup_all_room_invites", cleanup_all)
    monkeypatch.setattr(rooms, "audit_event", AsyncMock())
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["cleanup", "expired"], fake_msg, False)
    assert "Deleted: 2" in fake_bot.reply_ok.call_args.args[1]
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["cleanup"], fake_msg, False)
    assert "Deleted: 3" in fake_bot.reply_ok.call_args.args[1]
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["cleanup", "all"], fake_msg, False)
    assert "Deleted: 3" in fake_bot.reply_ok.call_args.args[1]
    cleanup_expired.assert_awaited_once_with(fake_bot)
    assert cleanup_all.await_count == 2
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["cleanup", "1"], fake_msg, False)
    fake_bot.reply_usage.assert_called_with(fake_msg, "!rooms invite cleanup [all|expired]")

    fake_bot.pending_room_invites = {
        2: {"id": 2, "room_jid": "b@conf", "inviter": "b@example.org", "reason": ""},
        1: {"id": 1, "room_jid": "a@conf", "inviter": "a@example.org", "reason": "why"},
    }
    monkeypatch.setattr(rooms, "load_pending_room_invites", AsyncMock(return_value=fake_bot.pending_room_invites))
    monkeypatch.setattr(rooms, "cleanup_expired_room_invites", AsyncMock(return_value=0))
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["list", "all"], fake_msg, False)
    listing = fake_bot.reply.call_args.args[1]
    assert any("#1 a@conf" in line for line in listing)
    assert any("#2 b@conf" in line for line in listing)
    assert any("— why" in line for line in listing)

    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["wat"], fake_msg, False)
    fake_bot.reply_warn.assert_called_with(fake_msg, "Unknown room invite action: wat")
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["accept"], fake_msg, False)
    fake_bot.reply_usage.assert_called_with(fake_msg, "!rooms invite accept <id>")
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["accept", "not-number"], fake_msg, False)
    fake_bot.reply_error.assert_called_with(fake_msg, "Invite id must be a number.")
    fake_bot.pending_room_invites = {}
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["accept", "99"], fake_msg, False)
    fake_bot.reply_error.assert_called_with(fake_msg, "Unknown pending room invite id: 99")


@pytest.mark.asyncio
async def test_rooms_invite_command_accept_and_decline_edges(fake_bot, fake_msg, monkeypatch):
    monkeypatch.setitem(rooms.config, "room_invites_enabled", True)
    monkeypatch.setitem(rooms.config, "nick", "")
    fake_bot.boundjid.resource = "ResourceNick"
    fake_bot.pending_room_invites = {
        5: {"id": 5, "room_jid": "room5@conf", "inviter": "user@example.org", "reason": ""}
    }
    monkeypatch.setattr(rooms, "load_pending_room_invites", AsyncMock(return_value=fake_bot.pending_room_invites))
    monkeypatch.setattr(rooms, "_join_invited_room", AsyncMock(side_effect=RuntimeError("join failed")))

    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["accept", "5"], fake_msg, False)
    assert "could not be accepted" in fake_bot.reply_error.call_args.args[1]
    assert 5 in fake_bot.pending_room_invites

    join = AsyncMock()
    delete = AsyncMock(return_value=fake_bot.pending_room_invites[5])
    audit = AsyncMock()
    monkeypatch.setattr(rooms, "_join_invited_room", join)
    monkeypatch.setattr(rooms, "_delete_pending_room_invite", delete)
    monkeypatch.setattr(rooms, "audit_event", audit)
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["accept", "5"], fake_msg, False)
    join.assert_awaited_once_with(fake_bot, "room5@conf", "ResourceNick")
    delete.assert_awaited_once_with(fake_bot, 5)
    assert audit.await_args.kwargs["target"] == "room5@conf"
    assert "Accepted room invite #5" in fake_bot.reply_ok.call_args.args[1]

    fake_bot.pending_room_invites = {
        6: {"id": 6, "room_jid": "room6@conf", "inviter": "user@example.org", "reason": ""}
    }
    monkeypatch.setattr(rooms, "load_pending_room_invites", AsyncMock(return_value=fake_bot.pending_room_invites))
    monkeypatch.setattr(rooms, "_delete_pending_room_invite", AsyncMock(return_value=None))
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["decline", "6"], fake_msg, False)
    assert "Unknown pending room invite id: 6" in fake_bot.reply_error.call_args.args[1]

    monkeypatch.setattr(rooms, "_delete_pending_room_invite", AsyncMock(return_value=fake_bot.pending_room_invites[6]))
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["rm", "6"], fake_msg, False)
    assert "Declined room invite #6" in fake_bot.reply_ok.call_args.args[1]


@pytest.mark.asyncio
async def test_room_settings_explicit_dm_allows_visible_room_owner(fake_bot, fake_msg, monkeypatch):
    patch_reply_methods(fake_bot)
    fake_msg["type"] = "chat"
    fake_msg["from"].bare = "owner@example.org"
    fake_msg["from"].resource = ""
    target_room = "target@conference.test"
    rooms.JOINED_ROOMS[target_room] = {
        "nick": "BotNick",
        "nicks": {
            "OwnerNick": {
                "jid": "owner@example.org/resource",
                "affiliation": "owner",
            }
        },
    }
    fake_bot.get_user_role = AsyncMock(return_value=rooms.Role.NONE)
    fake_bot.db.rooms.get = AsyncMock(return_value=(target_room, "BotNick", True, None))
    previous = types.SimpleNamespace(name="pin", enabled=True)
    state = types.SimpleNamespace(name="pin", enabled=False)
    monkeypatch.setattr(rooms, "get_room_feature", AsyncMock(return_value=previous))
    monkeypatch.setattr(rooms, "set_room_feature", AsyncMock(return_value=state))
    monkeypatch.setattr(rooms, "audit_event", AsyncMock())

    await rooms.cmd_room_disable(
        fake_bot,
        "owner@example.org",
        None,
        [target_room, "pin"],
        fake_msg,
        False,
    )

    rooms.set_room_feature.assert_awaited_once_with(fake_bot, target_room, "pin", False)
    assert f"pin is now disabled for {target_room}" in fake_bot.reply_ok.call_args.args[1]


@pytest.mark.asyncio
async def test_room_settings_explicit_admin_room_allows_bot_admin(fake_bot, fake_msg, monkeypatch):
    patch_reply_methods(fake_bot)
    fake_msg["type"] = "groupchat"
    fake_msg["from"].bare = "admins@conference.test"
    fake_msg["from"].resource = "AdminNick"
    target_room = "target@conference.test"
    fake_bot.get_user_role = AsyncMock(return_value=rooms.Role.ADMIN)
    fake_bot.db.rooms.get = AsyncMock(return_value=(target_room, "BotNick", True, None))
    previous = types.SimpleNamespace(name="weather", enabled=False)
    state = types.SimpleNamespace(name="weather", enabled=True)
    monkeypatch.setattr(rooms, "get_room_feature", AsyncMock(return_value=previous))
    monkeypatch.setattr(rooms, "set_room_feature", AsyncMock(return_value=state))
    monkeypatch.setattr(rooms, "audit_event", AsyncMock())

    await rooms.cmd_room_enable(
        fake_bot,
        "admin@example.org",
        "AdminNick",
        [target_room, "weather"],
        fake_msg,
        True,
    )

    rooms.set_room_feature.assert_awaited_once_with(fake_bot, target_room, "weather", True)
    assert f"weather is now enabled for {target_room}" in fake_bot.reply_ok.call_args.args[1]


@pytest.mark.asyncio
async def test_room_settings_public_room_without_target_uses_current_room(fake_bot, fake_msg, monkeypatch):
    patch_reply_methods(fake_bot)
    fake_msg["type"] = "groupchat"
    fake_msg["from"].bare = ROOM_JID
    rooms.JOINED_ROOMS[ROOM_JID] = {"nick": "BotNick", "nicks": {}}
    fake_bot.get_user_role = AsyncMock(return_value=rooms.Role.MODERATOR)
    monkeypatch.setattr(
        rooms,
        "list_room_features",
        AsyncMock(return_value=[types.SimpleNamespace(name="pin", enabled=True, default=True, modified=False)]),
    )
    monkeypatch.setattr(rooms, "format_room_feature_line", lambda state: f"• {state.name}: on")

    await rooms.cmd_room_plugins(fake_bot, "mod@example.org", "ModNick", ["all"], fake_msg, True)

    rooms.list_room_features.assert_awaited_once_with(fake_bot, ROOM_JID)
    assert f"Plugin settings for room '{ROOM_JID}'" in fake_bot.reply.call_args.args[1][0]


@pytest.mark.asyncio
async def test_room_settings_rejects_unprivileged_explicit_target(fake_bot, fake_msg):
    patch_reply_methods(fake_bot)
    target_room = "target@conference.test"
    fake_msg["type"] = "chat"
    fake_msg["from"].bare = "user@example.org"
    rooms.JOINED_ROOMS[target_room] = {
        "nick": "BotNick",
        "nicks": {"UserNick": {"jid": "user@example.org", "affiliation": "member"}},
    }
    fake_bot.get_user_role = AsyncMock(return_value=rooms.Role.USER)
    fake_bot.db.rooms.get = AsyncMock(return_value=(target_room, "BotNick", True, None))

    await rooms.cmd_room_enable(
        fake_bot,
        "user@example.org",
        None,
        [target_room, "pin"],
        fake_msg,
        False,
    )

    assert "Only room admins/owners" in fake_bot.reply_error.call_args.args[1]


@pytest.mark.asyncio
async def test_room_setdefaults_explicit_target_from_dm(fake_bot, fake_msg, monkeypatch):
    patch_reply_methods(fake_bot)
    target_room = "target@conference.test"
    fake_msg["type"] = "chat"
    fake_msg["from"].bare = "admin@example.org"
    fake_bot.get_user_role = AsyncMock(return_value=rooms.Role.ADMIN)
    fake_bot.db.rooms.get = AsyncMock(return_value=(target_room, "BotNick", True, None))
    defaults = AsyncMock()
    monkeypatch.setattr(rooms, "set_room_control_defaults", defaults)
    monkeypatch.setattr(rooms, "audit_event", AsyncMock())

    await rooms.cmd_room_setdefaults(
        fake_bot,
        "admin@example.org",
        None,
        [target_room],
        fake_msg,
        False,
    )

    defaults.assert_awaited_once_with(fake_bot, target_room)
    assert f"Restored plugin defaults for room '{target_room}'" in fake_bot.reply_ok.call_args.args[1]


def test_plugin_cleanup_summary_helpers_cover_plugin_hook_shapes():
    summary = {
        "toggles": 0,
        "data": 0,
        "rss_subscriptions": 0,
        "rss_feeds": 0,
        "xkcd_legacy_rooms": 0,
        "plugin_hooks": {},
    }
    plugin_summary = {
        "rss": {"subscriptions": "2", "feeds": 1},
        "xkcd": {"legacy_rooms": "3"},
        "pin": {"rooms": 1, "data": "4"},
        "reminder": {"reminders": 2, "tasks": "ignored"},
        "bad": {"rooms": "nope"},
        "plain": "ignored",
    }

    rooms._merge_plugin_cleanup_summary(summary, plugin_summary)

    assert summary["rss_subscriptions"] == 2
    assert summary["rss_feeds"] == 1
    assert summary["xkcd_legacy_rooms"] == 3
    assert summary["data"] == 7
    assert rooms._plugin_cleanup_changed(summary) is True
    assert rooms._plugin_hook_cleanup_changed({"pin": {"rooms": "1"}}) is True
    assert rooms._plugin_hook_cleanup_changed({"pin": {"rooms": "bad"}}) is False
    assert rooms._plugin_hook_cleanup_changed(None) is False

@pytest.mark.asyncio
async def test_room_diagnose_lines_include_runtime_and_plugin_state(fake_bot, monkeypatch):
    room_jid = "room@conference.test"
    rooms.JOINED_ROOMS[room_jid] = {
        "nick": "BotNick",
        "affiliation": "admin",
        "role": "moderator",
        "nicks": {"alice": {}, "bob": {}},
    }
    fake_bot.presence.joined_rooms = {room_jid: "BotNick"}
    fake_bot.pending_room_invites = {
        "one": {"room_jid": room_jid.upper()},
        "two": {"room_jid": "other@conference.test"},
    }
    fake_bot.db.rooms.get = AsyncMock(return_value=(room_jid, "BotNick", True, "active"))
    monkeypatch.setattr(
        rooms,
        "list_room_features",
        AsyncMock(return_value=[
            types.SimpleNamespace(name="rss", enabled=True),
            types.SimpleNamespace(name="xkcd", enabled=False),
        ]),
    )
    fake_bot.bot_plugins.plugins = {"rss": object(), "pin": object()}
    fake_bot.bot_plugins.plugin_state = AsyncMock(
        side_effect=[{"feeds": 2, "loaded": True}, {"pins": 1}]
    )

    lines = await rooms._room_diagnose_lines(fake_bot, room_jid)

    assert lines[0] == f"🔎 Room diagnostics: {room_jid}"
    assert "Known in DB: yes" in lines
    assert "Currently joined: yes" in lines
    assert "Presence joined: yes" in lines
    assert "Tracked occupants: 2" in lines
    assert "Pending invites: 1" in lines
    assert "Configured nick: BotNick" in lines
    assert "Autojoin: yes" in lines
    assert "Status: active" in lines
    assert "Runtime nick: BotNick" in lines
    assert "Runtime affiliation: admin" in lines
    assert "Runtime role: moderator" in lines
    assert "Enabled room plugins (1): rss" in lines
    assert "Disabled room plugins (1): xkcd" in lines
    assert "Plugin room state:" in lines
    assert "• rss: feeds=2" in lines
    assert "• pin: pins=1" in lines


@pytest.mark.asyncio
async def test_room_diagnose_lines_handles_missing_room_and_bad_row(fake_bot, monkeypatch):
    room_jid = "missing@conference.test"
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.presence.joined_rooms = {}
    fake_bot.pending_room_invites = {}
    monkeypatch.setattr(rooms, "list_room_features", AsyncMock(return_value=[]))

    lines = await rooms._room_diagnose_lines(fake_bot, room_jid)

    assert "Known in DB: no" in lines
    assert "Currently joined: no" in lines
    assert "Presence joined: no" in lines
    assert "Pending invites: 0" in lines
    assert "Enabled room plugins (0): none" in lines
    assert "Disabled room plugins (0): none" in lines
    assert rooms._yes_no(object()) == "yes"
    assert rooms._yes_no(None) == "no"

