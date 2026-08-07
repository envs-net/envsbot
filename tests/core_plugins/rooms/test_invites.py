from .helpers import (
    AsyncMock,
    ExplodingMappingPlugin,
    FallbackPluginStanza,
    InviteMessage,
    MagicMock,
    MappingOnlyPlugin,
    PluginStanza,
    pytest,
    types,
)
from core_plugins.rooms import invites as rooms
from core_plugins.rooms import lifecycle as lifecycle_module
from utils.config import config
from tests.database.helpers import SqliteDbAdapter
from xml.etree import ElementTree as ET
import time


def test_extract_direct_room_invite():
    xml = ET.fromstring(
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
    xml = ET.fromstring(
        "<message><x xmlns='jabber:x:conference' "
        "jid='room2@conference.test'/></message>"
    )
    msg = InviteMessage("inviter@example.org", xml)
    fake_bot.db.conn = None
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.make_message = MagicMock(side_effect=lambda **kwargs: kwargs)
    fake_bot._safe_send_message = AsyncMock()
    fake_bot.audit = AsyncMock()
    monkeypatch.setitem(config, "room_invites_enabled", True)
    monkeypatch.setitem(config, "room_invite_notify_jid", "admins@conference.test")
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
    monkeypatch.setitem(config, "room_invites_enabled", True)
    monkeypatch.setitem(config, "nick", "EnvsBot")

    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["accept", "7"], fake_msg, False)

    join_invited.assert_awaited_once_with(fake_bot, "room3@conference.test", "EnvsBot")
    assert fake_bot.pending_room_invites == {}
    reply_lines = fake_bot.reply.call_args.args[1]
    assert reply_lines[0].startswith("✅ Accepted room invite #7")
    assert any(f"{fake_bot.prefix}rooms diagnose room3@conference.test" in line for line in reply_lines)
    assert any(f"{fake_bot.prefix}rooms plugins room3@conference.test all" in line for line in reply_lines)


@pytest.mark.asyncio
async def test_room_invite_config_and_plugin_helpers(monkeypatch):
    monkeypatch.setitem(config, "room_invite_notify_jid", " AdminRoom@Conference.Test ")
    monkeypatch.setitem(config, "version_check_notify_jid", "updates@conference.test")
    monkeypatch.setitem(config, "owner", "owner@example.org")
    assert rooms.room_invite_notify_target() == "AdminRoom@Conference.Test"
    assert rooms.room_invite_admin_rooms() == {
        "adminroom@conference.test",
        "updates@conference.test",
    }

    monkeypatch.setitem(config, "room_invite_notify_jid", "")
    assert rooms.room_invite_notify_target() == "updates@conference.test"
    monkeypatch.setitem(config, "version_check_notify_jid", "")
    assert rooms.room_invite_notify_target() == "owner@example.org"
    monkeypatch.setitem(config, "owner", "")
    assert rooms.room_invite_notify_target() is None

    monkeypatch.setitem(config, "room_invite_max_age_days", "bad")
    assert rooms._room_invite_max_age_days() == 30
    monkeypatch.setitem(config, "room_invite_max_age_days", -1)
    assert rooms._room_invite_max_age_days() == 0
    assert rooms._room_invite_is_expired({"created_at": 1}, now=999999) is False
    monkeypatch.setitem(config, "room_invite_max_age_days", 1)
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

    invite_el = ET.fromstring(
        "<invite xmlns='http://jabber.org/protocol/muc#user'>"
        "<reason> hello </reason>"
        "</invite>"
    )
    assert rooms._room_invite_reason_from_invite(invite_el) == "hello"
    assert rooms._room_invite_reason_from_invite(ET.fromstring("<invite />")) == ""


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

    monkeypatch.setitem(config, "room_invite_max_age_days", 1)
    conn = await aiosqlite.connect(":memory:")
    adapter = SqliteDbAdapter(conn)
    fake_bot.db.transaction = adapter.transaction
    fake_bot.db.write = adapter.write
    fake_bot.db.fetch_one = adapter.fetch_one
    fake_bot.db.fetch_all = adapter.fetch_all
    try:
        await rooms.setup_room_invites_db(fake_bot)
        now = int(time.time())
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

    monkeypatch.setitem(config, "room_invite_max_age_days", 1)
    fresh = await rooms._store_pending_room_invite(fake_bot, "room@conf", "user@example.org", "hi")
    assert fresh["id"] == 1
    assert await rooms._store_pending_room_invite(fake_bot, "room@conf", "user@example.org", "hi") == fresh

    fresh["created_at"] = int(time.time()) - 3 * 86400
    replacement = await rooms._store_pending_room_invite(fake_bot, "room@conf", "user@example.org", "new")
    assert replacement["id"] == 1
    assert replacement["reason"] == "new"

    old = await rooms._store_pending_room_invite(fake_bot, "old@conf", "old@example.org", "old")
    old["created_at"] = int(time.time()) - 3 * 86400
    assert await rooms.cleanup_expired_room_invites(fake_bot) == 1

    monkeypatch.setitem(config, "room_invite_max_age_days", 0)
    assert await rooms.cleanup_expired_room_invites(fake_bot) == 0
    assert await rooms.cleanup_all_room_invites(fake_bot) == 1


@pytest.mark.asyncio
async def test_room_invite_notification_and_handle_branches(fake_bot, monkeypatch):
    fake_bot.db.conn = None
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.make_message = MagicMock(side_effect=lambda **kwargs: kwargs)
    fake_bot._safe_send_message = AsyncMock()
    monkeypatch.setitem(config, "room_invite_notify_jid", "")
    monkeypatch.setitem(config, "version_check_notify_jid", "")
    monkeypatch.setitem(config, "owner", "")
    await rooms._notify_room_invite(fake_bot, "no target")
    fake_bot._safe_send_message.assert_not_called()

    monkeypatch.setitem(config, "room_invite_notify_jid", "admins@conference.test")
    monkeypatch.setattr(rooms, "ensure_notification_target_joined", AsyncMock(return_value=True))
    monkeypatch.setattr(rooms, "notification_message_type", lambda bot, target: "groupchat")
    await rooms._notify_room_invite(fake_bot, "body")
    assert fake_bot._safe_send_message.await_args.args[0]["mtype"] == "groupchat"

    empty_msg = InviteMessage("inviter@example.org", ET.fromstring("<message />"))
    assert await rooms.handle_room_invite(fake_bot, empty_msg) is False

    monkeypatch.setitem(config, "room_invites_enabled", False)
    invalid_msg = InviteMessage(
        "inviter@example.org",
        ET.fromstring("<message><x xmlns='jabber:x:conference' jid='bad/room'/></message>"),
    )
    assert await rooms.handle_room_invite(fake_bot, invalid_msg) is True
    monkeypatch.setitem(config, "room_invites_enabled", True)

    assert await rooms.handle_room_invite(fake_bot, invalid_msg) is True
    assert "Ignored invalid room invite" in fake_bot._safe_send_message.await_args.args[0]["mbody"]

    joined_msg = InviteMessage(
        "inviter@example.org",
        ET.fromstring("<message><x xmlns='jabber:x:conference' jid='joined@conference.test'/></message>"),
    )
    rooms.JOINED_ROOMS["joined@conference.test"] = {"nick": "Bot"}
    assert await rooms.handle_room_invite(fake_bot, joined_msg) is True

    stored_msg = InviteMessage(
        "inviter@example.org",
        ET.fromstring("<message><x xmlns='jabber:x:conference' jid='stored@conference.test'/></message>"),
    )
    fake_bot.db.rooms.get = AsyncMock(return_value=("stored@conference.test", "Bot", True, None))
    assert await rooms.handle_room_invite(fake_bot, stored_msg) is True

    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    monkeypatch.setattr(rooms, "_store_pending_room_invite", AsyncMock(return_value=None))
    pending_msg = InviteMessage(
        "inviter@example.org",
        ET.fromstring("<message><x xmlns='jabber:x:conference' jid='pending@conference.test'/></message>"),
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
    monkeypatch.setattr(lifecycle_module, "load_pending_room_invites", load)
    monkeypatch.setattr(lifecycle_module, "cleanup_expired_room_invites", cleanup)

    await lifecycle_module.on_ready(fake_bot)

    load.assert_awaited_once_with(fake_bot)
    cleanup.assert_awaited_once_with(fake_bot)


@pytest.mark.asyncio
async def test_rooms_invite_list_empty_shows_none(fake_bot, fake_msg, monkeypatch):
    monkeypatch.setitem(config, "room_invites_enabled", True)
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
    monkeypatch.setitem(config, "room_invites_enabled", False)
    await rooms.rooms_invite(fake_bot, "admin@example.org", "admin", ["list"], fake_msg, False)
    fake_bot.reply_error.assert_called()

    monkeypatch.setitem(config, "room_invites_enabled", True)
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
    monkeypatch.setitem(config, "room_invites_enabled", True)
    monkeypatch.setitem(config, "nick", "")
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
    assert "Accepted room invite #5" in fake_bot.reply.call_args.args[1][0]
    assert any("!rooms diagnose room5@conf" in line for line in fake_bot.reply.call_args.args[1])

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


def test_room_invite_onboarding_lines_use_runtime_prefix(fake_bot):
    fake_bot.prefix = ";"
    lines = rooms._room_invite_onboarding_lines(fake_bot, "new@conference.test")

    assert lines[0].startswith("✅ Accepted room invite")
    assert any(";rooms diagnose new@conference.test" in line for line in lines)
    assert any(";rooms plugins new@conference.test all" in line for line in lines)
    assert any(";doctor rooms" in line for line in lines)
