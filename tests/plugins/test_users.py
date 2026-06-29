import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import types

import core_plugins.users as users_mod  # Always import the tested module
import core_plugins.rooms


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.db = MagicMock()
    bot.db.users = MagicMock()
    bot.db.users.plugin = MagicMock()
    bot.bot_plugins = MagicMock()
    bot.bot_plugins.plugins = {}
    bot.reply = MagicMock()
    bot.get_user_role = AsyncMock(return_value=users_mod.Role.USER)
    bot.audit = AsyncMock()
    return bot


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
        bot = MagicMock()
        bot.db = MagicMock()
        bot.db.users = MagicMock()
        bot.db.users.plugin = MagicMock()
        bot.bot_plugins = MagicMock()
        bot.bot_plugins.plugins = {}
        bot.reply = MagicMock()
        bot.get_user_role = AsyncMock(return_value=users_mod.Role.USER)
        return bot
    return factory


@pytest.mark.asyncio
async def test_on_muc_presence_adds_and_tracks_nick(mock_bot, mock_msg):
    pres = {
        "type": "available",
        "muc": {"room": "room1@conference.x", "nick": "john", "jid":
                MagicMock(bare="john@foo.bar")},
        "from": MagicMock(),
    }
    with patch("core_plugins.users.track_room_nick", new=AsyncMock()) as track, \
            patch("core_plugins.users.update_last_seen",
                  new=AsyncMock()) as last_seen:
        await users_mod.on_muc_presence(mock_bot, pres)
        track.assert_awaited()
        last_seen.assert_awaited()


@pytest.mark.asyncio
async def test_on_groupchat_message_updates_last_seen(mock_bot, mock_msg):
    bot_has_priv = MagicMock(return_value=True)
    mock_bot.bot_plugins.plugins = {'rooms': type(
        "RoomsPlugin", (), {"bot_has_privilege": bot_has_priv})()}
    mock_msg['muc'] = {"room": "room-A", "nick": "Nick"}
    mock_bot.plugin = {"xep_0045": MagicMock(
        get_jid_property=lambda r, n, s: "realjid@x")}
    with patch("core_plugins.users.update_last_seen",
               new=AsyncMock()) as update_last_seen:
        await users_mod.on_groupchat_message(mock_bot, mock_msg)
        update_last_seen.assert_awaited()


@pytest.mark.asyncio
async def test_on_muc_presence_skips_own_presence(mock_bot):
    mock_bot.boundjid.bare = "self@example.org"
    pres = {
        "type": "available",
        "muc": {
            "room": "room@conference.example.org",
            "nick": "Self",
            "jid": types.SimpleNamespace(bare="self@example.org"),
        },
    }

    with patch("core_plugins.users.track_room_nick", new=AsyncMock()) as track, \
            patch("core_plugins.users.update_last_seen",
                  new=AsyncMock()) as last_seen:
        await users_mod.on_muc_presence(mock_bot, pres)

    track.assert_not_awaited()
    last_seen.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_groupchat_message_skips_own_message(mock_bot, mock_msg):
    mock_bot.boundjid.bare = "self@example.org"
    mock_bot.bot_plugins.plugins = {
        "rooms": types.SimpleNamespace(bot_has_privilege=lambda room: True),
    }
    mock_bot.plugin = {
        "xep_0045": types.SimpleNamespace(
            get_jid_property=lambda room, nick, prop: "self@example.org/resource"
        ),
    }

    with patch("core_plugins.users.update_last_seen",
               new=AsyncMock()) as last_seen:
        await users_mod.on_groupchat_message(mock_bot, mock_msg)

    last_seen.assert_not_awaited()


@pytest.mark.asyncio
async def test_track_room_nick(build_mock_bot, monkeypatch):
    bot = build_mock_bot()
    bot.db.users.get = AsyncMock(return_value=None)
    bot.db.users.create = AsyncMock()
    plugin_store = AsyncMock()
    plugin_store.get = AsyncMock(return_value={
        "roomY": ["oldnick", "oldernick"],
        "roomZ": ["sharednick"],
    })
    plugin_store.set = AsyncMock()
    bot.db.users.plugin.return_value = plugin_store
    bot.db.users._nick_index = {
        "nickname": ["other@x"],
        "oldnick": ["jid@x", "other@x"],
        "stale": ["jid@x"],
    }
    bot.db.users._nick_index_lock = asyncio.Lock()

    monkeypatch.setattr(users_mod, "MAX_ROOM_NICKS", 2)

    await users_mod.track_room_nick(bot, "jid@x", "roomY", "nickname")

    bot.db.users.create.assert_awaited_once_with("jid@x", "nickname")
    plugin_store.set.assert_awaited_once_with(
        "jid@x",
        "roomnicks",
        {
            "roomY": ["nickname", "oldnick"],
            "roomZ": ["sharednick"],
        },
    )
    assert bot.db.users._nick_index == {
        "nickname": ["other@x", "jid@x"],
        "oldnick": ["other@x", "jid@x"],
        "sharednick": ["jid@x"],
    }


@pytest.mark.asyncio
async def test_find_users_by_nick_safe_sorts_and_handles_missing(build_mock_bot):
    bot = build_mock_bot()
    bot.db.users._nick_index = {
        "Nick": ["z@example.net", "a@example.net"],
        "Other": ["other@example.net"],
    }

    assert await users_mod.find_users_by_nick_safe(bot, "Nick") == [
        "a@example.net",
        "z@example.net",
    ]
    assert await users_mod.find_users_by_nick_safe(bot, "Missing") == []


@pytest.mark.asyncio
async def test_update_last_seen_newer_skipped(build_mock_bot):
    bot = build_mock_bot()
    bot.db.users.get = AsyncMock(
        return_value={"last_seen": "2099-01-01T01:01:01+00:00"})
    await users_mod.update_last_seen(bot, "jidtoignore@x")


@pytest.mark.asyncio
async def test_users_info_jid_and_nick(mock_bot, mock_msg):
    with patch.object(users_mod, "prefix", ","):
        # 1. Direct JID lookup
        mock_bot.db.users.get = AsyncMock(
            return_value={"jid": "user1@example.com",
                          "nickname": "N", "role": 4})
        with patch("core_plugins.users._send_user_info", new=AsyncMock()) as s_ui:
            await users_mod.users_info(mock_bot, "sender", "n",
                                       ["user1@example.com"], mock_msg, False)
            s_ui.assert_awaited()
        # 2. Fallback by nick, with single
        mock_bot.db.users.get = AsyncMock(
            side_effect=[None, {"jid": "user2@example.com",
                                "nickname": "M", "role": 4}])
        with patch("core_plugins.users.find_users_by_nick_safe",
                   new=AsyncMock(return_value=["user2@example.com"])), \
                patch("core_plugins.users._send_user_info",
                      new=AsyncMock()) as s_ui:
            await users_mod.users_info(mock_bot, "sender", "n", ["M"],
                                       mock_msg, False)
            s_ui.assert_awaited_once()
            assert s_ui.await_args.args[2]["jid"] == "user2@example.com"
        # 3. Multiple users match by nick
        with patch("core_plugins.users.find_users_by_nick_safe",
                   new=AsyncMock(return_value=["a@e", "b@e"])), \
                patch.object(mock_bot, "reply") as bot_reply:
            await users_mod.users_info(mock_bot, "sender", "n", ["foo"],
                                       mock_msg, False)
            found = False
            for call in bot_reply.call_args_list:
                for arg in call[0]:
                    if "multiple users found" in str(arg).lower():
                        found = True
            assert found
        # 4. Edge: nick index points to a user that no longer exists
        mock_bot.db.users.get = AsyncMock(side_effect=[None, None])
        with patch("core_plugins.users.find_users_by_nick_safe",
                   new=AsyncMock(return_value=["ghost@example.com"])), \
                patch.object(mock_bot, "reply") as bot_reply:
            await users_mod.users_info(mock_bot, "sender", "n", ["ghost"],
                                       mock_msg, False)
            assert "not registered" in bot_reply.call_args.args[1].lower()
        # 5. Edge: user not found
        mock_bot.db.users.get = AsyncMock(return_value=None)
        with patch("core_plugins.users.find_users_by_nick_safe",
                   new=AsyncMock(return_value=[])), \
                patch.object(mock_bot, "reply") as bot_reply:
            await users_mod.users_info(mock_bot, "sender", "n",
                                       ["zzznotfound"], mock_msg, False)
            assert "no users found" in bot_reply.call_args.args[1].lower()
        # 6. args missing
        with patch.object(mock_bot, "reply") as bot_reply:
            await users_mod.users_info(mock_bot, "sender", "n", [],
                                       mock_msg, False)
            found = False
            for call in bot_reply.call_args_list:
                for arg in call[0]:
                    if "usage:" in str(arg).lower():
                        found = True
            assert found


@pytest.mark.asyncio
async def test_users_list_shows_users(mock_bot, mock_msg):
    # Simulate room context
    users_mod.JOINED_ROOMS["room-A"] = {
        "nicks": {
            "A": {"jid": "a@example",
                  "affiliation": "member", "role": "user"},
            "B": {"jid": "b@example",
                  "affiliation": "member", "role": "admin"},
        }
    }
    # Patch to force visibility of rooms plugin with required attributes
    fake_rooms = type("RoomsPlugin", (), {
                      "JOINED_ROOMS": users_mod.JOINED_ROOMS})()
    mock_bot.bot_plugins.plugins = {"rooms": fake_rooms}
    mock_msg['from'].bare = "room-A"
    with (patch.object(users_mod, "prefix", ","),
          patch.object(mock_bot, "reply") as bot_reply):
        await users_mod.users_list(mock_bot, "send", "nick", [],
                                   mock_msg, False)
        reply_text = bot_reply.call_args.args[1]
        assert "📋 Users in room-A:" in reply_text
        assert "[member/admin] B (b@example)" in reply_text
        assert "[member/user] A (a@example)" in reply_text
        assert reply_text.index("[member/admin] B") < reply_text.index(
            "[member/user] A"
        )
    # No nicks
    users_mod.JOINED_ROOMS["room-B"] = {"nicks": {}}
    mock_msg['from'].bare = "room-B"
    fake_rooms = type("RoomsPlugin", (), {
                      "JOINED_ROOMS": users_mod.JOINED_ROOMS})()
    mock_bot.bot_plugins.plugins = {"rooms": fake_rooms}
    with (patch.object(users_mod, "prefix", ","),
          patch.object(mock_bot, "reply") as bot_reply):
        await users_mod.users_list(mock_bot, "send", "nick", ["room-B"],
                                   mock_msg, False)
        assert bot_reply.call_args.args[1] == "ℹ️ No users found in room: room-B"


@pytest.mark.asyncio
async def test_users_role_permission_logic(mock_bot, mock_msg):
    with patch.object(users_mod, "prefix", ","):
        mock_bot.db.users.get = AsyncMock(
            return_value={"jid": "receiver@example.com",
                          "role": users_mod.Role.USER.value})
        mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
        mock_bot.db.users.set = AsyncMock()
        args = ["receiver@example.com", "trusted"]
        with patch.object(mock_bot, "reply"):
            await users_mod.users_update(mock_bot, "senderjid@example.com",
                                         "nick", args, mock_msg, False)
            assert mock_bot.db.users.set.await_count == 1


@pytest.mark.asyncio
async def test_users_delete_logic(mock_bot, mock_msg):
    with patch.object(users_mod, "prefix", ","):
        mock_bot.db.users.get = AsyncMock(
            return_value={"jid": "to@delete",
                          "role": users_mod.Role.USER.value})
        mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
        mock_bot.db.users.delete = AsyncMock()
        args = ["to@delete"]
        with patch.object(mock_bot, "reply"):
            await users_mod.users_delete(mock_bot, "sender@example.org", "nick", args,
                                         mock_msg, False)
            mock_bot.db.users.delete.assert_awaited_with("to@delete")


@pytest.mark.asyncio
async def test_users_delete_errors(mock_bot, mock_msg):
    with patch.object(users_mod, "prefix", ","):
        mock_bot.db.users.get = AsyncMock(return_value=None)
        with patch.object(mock_bot, "reply") as bot_reply:
            await users_mod.users_delete(mock_bot, "s", "n", [],
                                         mock_msg, False)
            found = False
            for call in bot_reply.call_args_list:
                for arg in call[0]:
                    if "usage:" in str(arg).lower():
                        found = True
            assert found
        # Invalid JID
        args = ["invalidjid"]
        mock_bot.db.users.delete = AsyncMock()
        with patch.object(mock_bot, "reply") as bot_reply:
            await users_mod.users_delete(mock_bot, "s", "n", args,
                                         mock_msg, False)
            assert "Invalid user JID" in bot_reply.call_args.args[1]
        mock_bot.db.users.delete.assert_not_awaited()
        # User not found
        mock_bot.db.users.get = AsyncMock(return_value=None)
        args = ["notfound@x"]
        with patch.object(mock_bot, "reply") as bot_reply:
            await users_mod.users_delete(mock_bot, "s", "n",
                                         args, mock_msg, False)


@pytest.mark.asyncio
async def test_users_usage_replies_use_runtime_prefix(mock_bot, mock_msg):
    mock_bot.prefix = "!"

    with patch.object(mock_bot, "reply") as bot_reply:
        await users_mod.users_info(
            mock_bot, "sender", "nick", [], mock_msg, False
        )
        assert bot_reply.call_args.args[1] == "🟡️ Usage: !users info <jid|nick>"

    mock_bot.reply_usage = MagicMock()
    await users_mod.users_update(
        mock_bot, "sender", "nick", [], mock_msg, False
    )
    mock_bot.reply_usage.assert_called_once_with(
        mock_msg, "!users role <jid> <role>"
    )

    with patch.object(mock_bot, "reply") as bot_reply:
        await users_mod.users_delete(
            mock_bot, "sender", "nick", [], mock_msg, False
        )
        assert bot_reply.call_args.args[1] == "🟡️ Usage: !users delete <jid>"


@pytest.mark.asyncio
async def test__send_user_info_display_full(mock_bot, mock_msg):
    user_data = {
        "jid": "x@y", "nickname": "nn", "role": users_mod.Role.ADMIN.value,
        "created_at": "2024-01-01T01:00:00", "last_seen": "2024-05-01T17:00:00"
    }
    with patch.object(users_mod, "prefix", ","):
        await users_mod._send_user_info(mock_bot, mock_msg, user_data)
        assert mock_bot.reply.called

# ...add additional tests for track_room_nick, find_users_by_nick_safe, error
# and edge branches...

@pytest.mark.asyncio
async def test_presence_and_message_skip_branches(mock_bot, mock_msg):
    await users_mod.on_muc_presence(mock_bot, {"type": "subscribe", "muc": {}})
    await users_mod.on_muc_presence(mock_bot, {"type": "available"})

    pres = {
        "type": "available",
        "muc": {"room": "room", "nick": "nick", "jid": None},
    }
    await users_mod.on_muc_presence(mock_bot, pres)

    mock_bot.boundjid.bare = "self@example.org"
    own = {
        "type": "available",
        "muc": {
            "room": "room",
            "nick": "self",
            "jid": types.SimpleNamespace(bare="self@example.org"),
        },
    }
    await users_mod.on_muc_presence(mock_bot, own)

    leaving = {
        "type": "unavailable",
        "muc": {
            "room": "room",
            "nick": "nick",
            "jid": types.SimpleNamespace(bare="other@example.org"),
        },
    }
    with patch("core_plugins.users.update_last_seen", new=AsyncMock()) as last_seen:
        await users_mod.on_muc_presence(mock_bot, leaving)
        last_seen.assert_awaited_once_with(mock_bot, "other@example.org")

    await users_mod.on_groupchat_message(mock_bot, mock_msg)
    mock_bot.bot_plugins.plugins = {"rooms": types.SimpleNamespace(bot_has_privilege=lambda room: False)}
    await users_mod.on_groupchat_message(mock_bot, mock_msg)
    mock_bot.bot_plugins.plugins = {"rooms": types.SimpleNamespace(bot_has_privilege=lambda room: True)}
    mock_bot.plugin = {"xep_0045": types.SimpleNamespace(get_jid_property=lambda *a: None)}
    await users_mod.on_groupchat_message(mock_bot, mock_msg)
    mock_bot.plugin = {"xep_0045": types.SimpleNamespace(get_jid_property=lambda *a: "self@example.org")}
    await users_mod.on_groupchat_message(mock_bot, mock_msg)


@pytest.mark.asyncio
async def test_on_load_initializes_or_skips(mock_bot):
    mock_bot.db = None
    await users_mod.on_load(mock_bot)

    store = AsyncMock()
    store.get_global = AsyncMock(return_value=None)
    mock_bot.db = types.SimpleNamespace(
        users=types.SimpleNamespace(plugin=MagicMock(return_value=store))
    )
    await users_mod.on_load(mock_bot)
    assert mock_bot.db.users._nick_index == {}
    assert mock_bot.bot_plugins.register_event.call_count >= 2


@pytest.mark.asyncio
async def test_role_helper_permission_guard_branches(mock_bot, monkeypatch):
    monkeypatch.setitem(users_mod.config, "owner", "owner@example.org")
    assert users_mod._parse_user_jid("owner@example.org/resource") == "owner@example.org"
    assert users_mod._parse_user_jid("not-a-jid") is None
    assert users_mod._owner_jid() == "owner@example.org"
    assert users_mod._is_config_owner("owner@example.org/resource") is True
    assert users_mod._is_config_owner("someone@example.org") is False
    assert users_mod._role_from_user(None) == users_mod.Role.USER
    assert users_mod._role_from_user({"role": "not-an-int"}) == users_mod.Role.USER
    assert users_mod._role_from_user({"role": users_mod.Role.OWNER.value}) == users_mod.Role.USER
    assert users_mod._role_from_user({"role": users_mod.Role.NONE.value}) == users_mod.Role.USER
    assert users_mod._role_label(users_mod.Role.ADMIN) == "admin"
    assert "owner" not in users_mod.ROLE_NAMES
    assert "none" not in users_mod.ROLE_NAMES

    mock_bot.get_user_role = AsyncMock(side_effect=RuntimeError("boom"))
    assert await users_mod._actor_role(mock_bot, "actor@example.org") == users_mod.Role.NONE

    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
    denied_cases = (
        ("actor@example.org", "owner@example.org", users_mod.Role.USER, users_mod.Role.USER, "owner"),
        ("actor@example.org", "target@example.org", users_mod.Role.USER, users_mod.Role.OWNER, "cannot be assigned"),
        ("actor@example.org", "target@example.org", users_mod.Role.USER, users_mod.Role.NONE, "cannot be assigned"),
        ("actor@example.org", "actor@example.org", users_mod.Role.ADMIN, users_mod.Role.USER, "own role"),
        ("actor@example.org", "actor@example.org", users_mod.Role.ADMIN, users_mod.Role.SUPERADMIN, "own role"),
        ("actor@example.org", "target@example.org", users_mod.Role.USER, users_mod.Role.SUPERADMIN, "superadmin"),
        ("actor@example.org", "target@example.org", users_mod.Role.SUPERADMIN, users_mod.Role.ADMIN, "superadmin"),
        ("actor@example.org", "target@example.org", users_mod.Role.ADMIN, users_mod.Role.USER, "equal"),
        ("actor@example.org", "target@example.org", users_mod.Role.USER, users_mod.Role.ADMIN, "below"),
    )
    for actor, target, old_role, new_role, fragment in denied_cases:
        allowed, reason = await users_mod._can_change_role(mock_bot, actor, target, old_role, new_role)
        assert allowed is False
        assert fragment.lower() in reason.lower()

    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.USER)
    allowed, reason = await users_mod._can_change_role(
        mock_bot,
        "user@example.org",
        "target@example.org",
        users_mod.Role.USER,
        users_mod.Role.NEW,
    )
    assert allowed is False
    assert "not allowed" in reason

    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.OWNER)
    allowed, reason = await users_mod._can_change_role(
        mock_bot,
        "owner@example.org",
        "target@example.org",
        users_mod.Role.USER,
        users_mod.Role.SUPERADMIN,
    )
    assert allowed is True
    assert reason == ""


@pytest.mark.asyncio
async def test_delete_permission_guard_branches(mock_bot, monkeypatch):
    monkeypatch.setitem(users_mod.config, "owner", "owner@example.org")
    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)

    denied_cases = (
        ("actor@example.org", "owner@example.org", users_mod.Role.USER, "owner"),
        ("actor@example.org", "actor@example.org", users_mod.Role.USER, "own"),
        ("actor@example.org", "target@example.org", users_mod.Role.SUPERADMIN, "superadmin"),
        ("actor@example.org", "target@example.org", users_mod.Role.ADMIN, "equal"),
    )
    for actor, target, role, fragment in denied_cases:
        allowed, reason = await users_mod._can_delete_user(mock_bot, actor, target, role)
        assert allowed is False
        assert fragment.lower() in reason.lower()

    allowed, reason = await users_mod._can_delete_user(
        mock_bot, "actor@example.org", "target@example.org", users_mod.Role.USER
    )
    assert allowed is True
    assert reason == ""


@pytest.mark.asyncio
async def test_users_list_error_branches(mock_bot, mock_msg):
    await users_mod.users_list(mock_bot, "sender", "nick", [], mock_msg, False)
    assert "Rooms plugin" in mock_bot.reply.call_args.args[1]

    rooms = types.SimpleNamespace(JOINED_ROOMS={"room@example.org": {"nicks": {}}})
    mock_bot.bot_plugins.plugins = {"rooms": rooms}
    await users_mod.users_list(mock_bot, "sender", "nick", [], mock_msg, True)
    assert "private chat" in mock_bot.reply.call_args.args[1]

    mock_msg["from"].bare = "missing@example.org"
    await users_mod.users_list(mock_bot, "sender", "nick", [], mock_msg, False)
    assert "Not joined" in mock_bot.reply.call_args.args[1]

    await users_mod.users_list(mock_bot, "sender", "nick", ["missing@example.org"], mock_msg, False)
    assert "Not joined" in mock_bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_users_update_and_delete_command_edge_branches(mock_bot, mock_msg, monkeypatch):
    monkeypatch.setitem(users_mod.config, "owner", "owner@example.org")
    mock_bot.reply_usage = MagicMock()

    await users_mod.users_update(mock_bot, "admin@example.org", "nick", [], mock_msg, False)
    mock_bot.reply_usage.assert_called_once()

    await users_mod.users_update(
        mock_bot, "admin@example.org", "nick", ["target@example.org", "notarole"], mock_msg, False
    )
    assert "Invalid role" in mock_bot.reply.call_args.args[1]

    await users_mod.users_update(
        mock_bot, "admin@example.org", "nick", ["not-a-jid", "user"], mock_msg, False
    )
    assert "Invalid user JID" in mock_bot.reply.call_args.args[1]

    mock_bot.db.users.get = AsyncMock(return_value=None)
    await users_mod.users_update(
        mock_bot, "admin@example.org", "nick", ["missing@example.org", "user"], mock_msg, False
    )
    assert "User not found" in mock_bot.reply.call_args.args[1]

    mock_bot.db.users.get = AsyncMock(return_value={"jid": "target@example.org", "role": users_mod.Role.USER.value})
    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
    await users_mod.users_update(
        mock_bot, "admin@example.org", "nick", ["target@example.org", "user"], mock_msg, False
    )
    assert "already has role" in mock_bot.reply.call_args.args[1]

    await users_mod.users_update(
        mock_bot, "admin@example.org", "nick", ["owner@example.org", "user"], mock_msg, False
    )
    assert "owner" in mock_bot.reply.call_args.args[1].lower()

    mock_bot.db.users.get = AsyncMock(return_value={"jid": "target@example.org", "role": users_mod.Role.ADMIN.value})
    await users_mod.users_delete(
        mock_bot, "admin@example.org", "nick", ["target@example.org"], mock_msg, False
    )
    assert "equal or higher" in mock_bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_users_roles_and_admins_output(mock_bot, mock_msg, monkeypatch):
    monkeypatch.setitem(users_mod.config, "owner", "owner@example.org")
    mock_bot.prefix = ","

    await users_mod.users_roles(mock_bot, "sender", "nick", [], mock_msg, False)
    roles_text = "\n".join(mock_bot.reply.call_args.args[1])
    assert "owner" in roles_text
    assert "superadmin" in roles_text

    monkeypatch.setitem(users_mod.config, "owner", "owner@example.org/resource")
    mock_bot.db.users.list = AsyncMock(return_value=[
        {"jid": "admin@example.org", "role": users_mod.Role.ADMIN.value},
        {"jid": "user@example.org", "role": users_mod.Role.USER.value},
        {"jid": "super@example.org", "role": users_mod.Role.SUPERADMIN.value},
        {"jid": "legacy-owner@example.org", "role": users_mod.Role.OWNER.value},
    ])
    await users_mod.users_admins(mock_bot, "sender", "nick", ["all"], mock_msg, False)
    admins_lines = mock_bot.reply.call_args.args[1]
    admins_text = "\n".join(admins_lines)
    assert admins_lines[0] == "👥 Admin users"
    assert "owner@example.org" in admins_text
    assert "owner@example.org/resource" not in admins_text
    assert "admin@example.org" in admins_text
    assert "super@example.org" in admins_text
    assert "legacy-owner@example.org" not in admins_text
    assert "user@example.org" not in admins_text
    assert admins_text.index("owner@example.org") < admins_text.index(
        "admin@example.org"
    )
    assert admins_text.index("admin@example.org") < admins_text.index(
        "super@example.org"
    )


@pytest.mark.asyncio
async def test_users_role_audit_events(mock_bot, mock_msg):
    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
    mock_bot.db.users.set = AsyncMock()

    mock_bot.db.users.get = AsyncMock(
        return_value={"jid": "target@example.org", "role": users_mod.Role.USER.value}
    )
    await users_mod.users_update(
        mock_bot,
        "admin@example.org",
        "nick",
        ["target@example.org", "trusted"],
        mock_msg,
        False,
    )
    mock_bot.audit.assert_awaited_with(
        "user_role_changed",
        actor="admin@example.org",
        target="target@example.org",
        details={"plugin": "users", "old_role": "user", "new_role": "trusted"},
    )

    mock_bot.audit.reset_mock()
    mock_bot.db.users.get = AsyncMock(
        return_value={"jid": "target@example.org", "role": users_mod.Role.ADMIN.value}
    )
    await users_mod.users_update(
        mock_bot,
        "admin@example.org",
        "nick",
        ["target@example.org", "user"],
        mock_msg,
        False,
    )
    event, kwargs = mock_bot.audit.await_args.args[0], mock_bot.audit.await_args.kwargs
    assert event == "user_role_change_denied"
    assert kwargs["actor"] == "admin@example.org"
    assert kwargs["target"] == "target@example.org"
    assert kwargs["details"]["old_role"] == "admin"
    assert kwargs["details"]["requested_role"] == "user"
    assert "equal or higher" in kwargs["details"]["reason"]

    mock_bot.audit.reset_mock()
    mock_bot.db.users.get = AsyncMock(
        return_value={"jid": "target@example.org", "role": users_mod.Role.USER.value}
    )
    await users_mod.users_update(
        mock_bot,
        "admin@example.org",
        "nick",
        ["target@example.org", "user"],
        mock_msg,
        False,
    )
    mock_bot.audit.assert_awaited_with(
        "user_role_change_noop",
        actor="admin@example.org",
        target="target@example.org",
        details={"plugin": "users", "role": "user"},
    )


@pytest.mark.asyncio
async def test_users_delete_audit_events(mock_bot, mock_msg):
    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
    mock_bot.db.users.delete = AsyncMock()

    mock_bot.db.users.get = AsyncMock(
        return_value={"jid": "target@example.org", "role": users_mod.Role.USER.value}
    )
    await users_mod.users_delete(
        mock_bot,
        "admin@example.org",
        "nick",
        ["target@example.org"],
        mock_msg,
        False,
    )
    mock_bot.audit.assert_awaited_with(
        "user_deleted",
        actor="admin@example.org",
        target="target@example.org",
        details={"plugin": "users", "role": "user"},
    )

    mock_bot.audit.reset_mock()
    mock_bot.db.users.get = AsyncMock(
        return_value={"jid": "target@example.org", "role": users_mod.Role.ADMIN.value}
    )
    await users_mod.users_delete(
        mock_bot,
        "admin@example.org",
        "nick",
        ["target@example.org"],
        mock_msg,
        False,
    )
    event, kwargs = mock_bot.audit.await_args.args[0], mock_bot.audit.await_args.kwargs
    assert event == "user_delete_denied"
    assert kwargs["actor"] == "admin@example.org"
    assert kwargs["target"] == "target@example.org"
    assert kwargs["details"]["role"] == "admin"
    assert "equal or higher" in kwargs["details"]["reason"]

    mock_bot.audit.reset_mock()
    mock_bot.db.users.delete.reset_mock()
    await users_mod.users_delete(
        mock_bot,
        "admin@example.org",
        "nick",
        ["not-a-jid"],
        mock_msg,
        False,
    )
    mock_bot.audit.assert_awaited_with(
        "user_delete_denied",
        actor="admin@example.org",
        target="not-a-jid",
        details={"plugin": "users", "reason": "invalid_user_jid"},
    )
    mock_bot.db.users.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_audit_helper_is_best_effort(monkeypatch, mock_bot):
    async def broken_audit_event(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(users_mod, "audit_event", broken_audit_event)
    await users_mod._write_user_audit(
        mock_bot,
        "user_role_change_denied",
        actor="admin@example.org",
        target="target@example.org",
        details={"reason": "test"},
    )

@pytest.mark.asyncio
async def test_users_plugin_grants_multi_add_show_revoke(monkeypatch, mock_msg):
    class Store:
        def __init__(self):
            self.data = {}

        async def get(self, jid, key):
            return self.data.get((jid, key))

        async def set(self, jid, key, value):
            self.data[(jid, key)] = value

    store = Store()
    bot = MagicMock()
    bot.db.users.get = AsyncMock(return_value={"jid": "alice@example.org"})
    bot.db.users.plugin.return_value = store
    bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
    bot.reply = MagicMock()

    monkeypatch.setattr(users_mod, "audit_event", AsyncMock())

    await users_mod.users_grant(
        bot,
        "admin@example.org",
        "admin",
        ["alice@example.org", "rss", "pin", "poll"],
        mock_msg,
        False,
    )

    assert store.data[("alice@example.org", users_mod.GRANTS_FIELD)] == [
        "pin",
        "poll",
        "rss",
    ]
    assert "pin, poll, rss" in bot.reply.call_args.args[1]

    bot.reply.reset_mock()
    await users_mod.users_grants(
        bot,
        "admin@example.org",
        "admin",
        ["alice@example.org"],
        mock_msg,
        False,
    )
    assert "pin, poll, rss" in bot.reply.call_args.args[1]

    bot.reply.reset_mock()
    await users_mod.users_revoke(
        bot,
        "admin@example.org",
        "admin",
        ["alice@example.org", "pin", "poll"],
        mock_msg,
        False,
    )
    assert store.data[("alice@example.org", users_mod.GRANTS_FIELD)] == ["rss"]
    assert "rss" in bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_room_plugin_grant_requires_live_owner_or_admin_affiliation():
    class Store:
        async def get(self, jid, key):
            assert jid == "alice@example.org"
            assert key == users_mod.GRANTS_FIELD
            return ["rss"]

    class MucPlugin:
        async def get_affiliation_list(self, room, affiliation):
            if affiliation == "owner":
                return []
            if affiliation == "admin":
                return [{"jid": "alice@example.org/resource"}]
            return []

    bot = MagicMock()
    bot.db.users.plugin.return_value = Store()
    bot.plugin = {"xep_0045": MucPlugin()}

    assert await users_mod.user_has_room_plugin_grant(
        bot,
        "alice@example.org",
        "rss",
        "room@conference.example.org",
    ) is True
    assert await users_mod.user_has_room_plugin_grant(
        bot,
        "alice@example.org",
        "pin",
        "room@conference.example.org",
    ) is False


@pytest.mark.asyncio
async def test_users_plugin_grants_respect_role_hierarchy(mock_msg):
    class Store:
        async def get(self, jid, key):
            return []

        async def set(self, jid, key, value):
            raise AssertionError("grant store should not be written")

    bot = MagicMock()
    bot.db.users.get = AsyncMock(return_value={
        "jid": "root@example.org",
        "role": users_mod.Role.ADMIN.value,
    })
    bot.db.users.plugin.return_value = Store()
    bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
    bot.reply = MagicMock()

    await users_mod.users_grant(
        bot,
        "admin@example.org",
        "admin",
        ["root@example.org", "rss"],
        mock_msg,
        False,
    )

    assert "equal or higher role" in bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_room_plugin_grant_falls_back_to_cache_on_partial_query_failure():
    class Store:
        async def get(self, jid, key):
            return ["rss"]

    class MucPlugin:
        async def get_affiliation_list(self, room, affiliation):
            if affiliation == "owner":
                raise RuntimeError("temporary muc query failure")
            return []

    bot = MagicMock()
    bot.db.users.plugin.return_value = Store()
    bot.plugin = {"xep_0045": MucPlugin()}

    room = "room@conference.example.org"
    old_rooms = dict(core_plugins.rooms.JOINED_ROOMS)
    core_plugins.rooms.JOINED_ROOMS.clear()
    core_plugins.rooms.JOINED_ROOMS[room] = {
        "nicks": {
            "Alice": {
                "jid": "alice@example.org/resource",
                "affiliation": "owner",
            },
        },
    }
    try:
        assert await users_mod.user_has_room_plugin_grant(
            bot,
            "alice@example.org",
            "rss",
            room,
        ) is True
    finally:
        core_plugins.rooms.JOINED_ROOMS.clear()
        core_plugins.rooms.JOINED_ROOMS.update(old_rooms)


def test_normalize_affiliation_result_accepts_dict_keys():
    assert users_mod._normalize_affiliation_result({
        "alice@example.org/resource": {},
    }) == {"alice@example.org"}


def test_grantable_plugin_names_are_stable_and_human_readable():
    assert users_mod._grantable_plugin_names() == "rss, pin, poll"
