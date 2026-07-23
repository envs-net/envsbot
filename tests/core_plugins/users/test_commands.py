from .helpers import (
    AsyncMock,
    MagicMock,
    assert_reply_contains,
    patch,
    pytest,
    types,
    users_mod,
)
from utils.config import config


@pytest.mark.asyncio
async def test_users_info_jid_and_nick(mock_bot, mock_msg):
    with patch.object(users_mod, "prefix", ","):
        mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
        # 1. Direct JID lookup
        mock_bot.db.users.get = AsyncMock(
            return_value={"jid": "user1@example.com",
                          "nickname": "N", "role": 4})
        with patch("core_plugins.users.commands._send_user_info", new=AsyncMock()) as s_ui:
            await users_mod.users_info(mock_bot, "admin@example.com", "n",
                                       ["user1@example.com"], mock_msg, False)
            s_ui.assert_awaited()
        # 2. Fallback by nick, with single
        mock_bot.db.users.get = AsyncMock(
            return_value={"jid": "user2@example.com",
                          "nickname": "M", "role": 4})
        with patch("core_plugins.users.commands.find_users_by_nick_safe",
                   new=AsyncMock(return_value=["user2@example.com"])), \
                patch("core_plugins.users.commands._send_user_info",
                      new=AsyncMock()) as s_ui:
            await users_mod.users_info(mock_bot, "admin@example.com", "n", ["M"],
                                       mock_msg, False)
            s_ui.assert_awaited_once()
            assert s_ui.await_args.args[2]["jid"] == "user2@example.com"
        # 3. Multiple users match by nick
        with patch("core_plugins.users.commands.find_users_by_nick_safe",
                   new=AsyncMock(return_value=["a@e", "b@e"])), \
                patch.object(mock_bot, "reply") as bot_reply:
            await users_mod.users_info(mock_bot, "admin@example.com", "n", ["foo"],
                                       mock_msg, False)
            assert_reply_contains(bot_reply, "multiple users found")
        # 4. Edge: nick index points to a user that no longer exists
        mock_bot.db.users.get = AsyncMock(side_effect=[None, None])
        with patch("core_plugins.users.commands.find_users_by_nick_safe",
                   new=AsyncMock(return_value=["ghost@example.com"])), \
                patch.object(mock_bot, "reply") as bot_reply:
            await users_mod.users_info(mock_bot, "admin@example.com", "n", ["ghost"],
                                       mock_msg, False)
            assert "not registered" in bot_reply.call_args.args[1].lower()
        # 5. Edge: unknown nick
        mock_bot.db.users.get = AsyncMock(return_value=None)
        with patch("core_plugins.users.commands.find_users_by_nick_safe",
                   new=AsyncMock(return_value=[])), \
                patch.object(mock_bot, "reply") as bot_reply:
            await users_mod.users_info(mock_bot, "admin@example.com", "n",
                                       ["zzznotfound"], mock_msg, False)
            assert "no users found" in bot_reply.call_args.args[1].lower()

        # 6. A valid but unknown JID must not be treated as a nickname.
        mock_bot.db.users.get = AsyncMock(return_value=None)
        find_by_nick = AsyncMock(return_value=["unexpected@example.com"])
        with patch("core_plugins.users.commands.find_users_by_nick_safe",
                   new=find_by_nick), \
                patch.object(mock_bot, "reply") as bot_reply:
            await users_mod.users_info(mock_bot, "admin@example.com", "n",
                                       ["missing@example.com"], mock_msg, False)
            assert bot_reply.call_args.args[1] == (
                "🟡️ User not found: missing@example.com"
            )
        find_by_nick.assert_not_awaited()


@pytest.mark.asyncio
async def test_users_info_self_in_direct_message_and_permission_guard(mock_bot, mock_msg):
    self_user = {
        "jid": "member@example.org",
        "nickname": None,
        "role": users_mod.Role.USER.value,
    }
    mock_bot.db.users.get = AsyncMock(return_value=self_user)

    with patch("core_plugins.users.commands._send_user_info", new=AsyncMock()) as send_info:
        await users_mod.users_info(
            mock_bot,
            "member@example.org",
            None,
            [],
            mock_msg,
            False,
        )
    send_info.assert_awaited_once_with(mock_bot, mock_msg, self_user)

    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.USER)
    await users_mod.users_info(
        mock_bot,
        "member@example.org",
        None,
        ["other@example.org"],
        mock_msg,
        False,
    )
    assert "only view your own" in mock_bot.reply.call_args.args[1]

    await users_mod.users_info(
        mock_bot,
        "member@example.org",
        None,
        [],
        mock_msg,
        True,
    )
    assert "private chat or MUC PM" in mock_bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_users_list_groups_known_users_by_source(mock_bot, mock_msg):
    mock_bot.client_roster = None
    mock_bot.boundjid = types.SimpleNamespace(bare="bot@example.org")
    mock_bot.db.users._direct_users = {"active@example.org"}
    mock_bot.db.users._room_users = {
        "active@example.org",
        "passive@example.org",
    }
    mock_bot.db.users.list = AsyncMock(return_value=[
        {
            "jid": "active@example.org",
            "nickname": "Active",
            "role": users_mod.Role.TRUSTED.value,
        },
        {
            "jid": "passive@example.org",
            "nickname": "Passive",
            "role": users_mod.Role.USER.value,
        },
        {
            "jid": "stored@example.org",
            "nickname": None,
            "role": users_mod.Role.ADMIN.value,
        },
        {"jid": "__GLOBAL__", "role": users_mod.Role.USER.value},
    ])
    joined_rooms = {
        "room@example.org": {
            "nicks": {
                "ActiveRoomNick": {
                    "jid": "active@example.org",
                    "affiliation": "member",
                    "role": "participant",
                },
                "PassiveRoomNick": {
                    "jid": "passive@example.org",
                    "affiliation": "member",
                    "role": "participant",
                },
            },
        },
    }
    mock_bot.bot_plugins.plugins = {
        "rooms": types.SimpleNamespace(JOINED_ROOMS=joined_rooms),
    }

    await users_mod.users_list(mock_bot, "admin@example.org", "nick", [], mock_msg, False)

    reply_text = mock_bot.reply.call_args.args[1]
    assert "Known users (3): active=1 | passive=1 | stored-only=1" in reply_text
    assert "💬 active@example.org | role=trusted | nick=Active | rooms=1" in reply_text
    assert "👥 passive@example.org | role=user | nick=Passive | rooms=1" in reply_text
    assert "⚪ stored@example.org | role=admin" in reply_text
    assert reply_text.count("active@example.org") == 1
    assert "__GLOBAL__" not in reply_text


@pytest.mark.asyncio
async def test_users_list_filters_and_explicit_room(mock_bot, mock_msg):
    mock_bot.client_roster = None
    mock_bot.boundjid = types.SimpleNamespace(bare="bot@example.org")
    mock_bot.db.users._direct_users = {"active@example.org"}
    mock_bot.db.users._room_users = {"passive@example.org"}
    mock_bot.db.users.list = AsyncMock(return_value=[
        {"jid": "active@example.org", "role": users_mod.Role.USER.value},
        {"jid": "passive@example.org", "role": users_mod.Role.USER.value},
    ])
    joined_rooms = {
        "room@example.org": {
            "nicks": {
                "B": {"jid": "b@example.org", "affiliation": "member", "role": "admin"},
                "A": {"jid": "a@example.org", "affiliation": "member", "role": "user"},
            },
        },
        "empty@example.org": {"nicks": {}},
    }
    mock_bot.bot_plugins.plugins = {
        "rooms": types.SimpleNamespace(JOINED_ROOMS={}),
    }

    await users_mod.users_list(
        mock_bot, "admin@example.org", "nick", ["active"], mock_msg, False
    )
    active_reply = mock_bot.reply.call_args.args[1]
    assert "Active/direct users (1):" in active_reply
    assert "active@example.org" in active_reply
    assert "passive@example.org" not in active_reply

    await users_mod.users_list(
        mock_bot, "admin@example.org", "nick", ["passive", "all"], mock_msg, False
    )
    passive_reply = mock_bot.reply.call_args.args[1]
    assert "Passive/room users (1):" in passive_reply
    assert "passive@example.org" in passive_reply
    assert "active@example.org" not in passive_reply

    mock_bot.bot_plugins.plugins = {
        "rooms": types.SimpleNamespace(JOINED_ROOMS=joined_rooms),
    }

    await users_mod.users_list(
        mock_bot, "admin@example.org", "nick", ["room@example.org"], mock_msg, False
    )
    room_reply = mock_bot.reply.call_args.args[1]
    assert "📋 Users in room@example.org:" in room_reply
    assert room_reply.index("[member/admin] B") < room_reply.index("[member/user] A")

    await users_mod.users_list(
        mock_bot, "admin@example.org", "nick", ["empty@example.org"], mock_msg, False
    )
    assert mock_bot.reply.call_args.args[1] == (
        "ℹ️ No users found in room: empty@example.org"
    )


@pytest.mark.asyncio
async def test_users_list_includes_direct_roster_contacts(mock_bot, mock_msg):
    mock_bot.boundjid = types.SimpleNamespace(bare="bot@example.org")
    mock_bot.db.users._direct_users = set()
    mock_bot.db.users._room_users = set()
    mock_bot.db.users.list = AsyncMock(return_value=[
        {"jid": "room@conference.test", "role": users_mod.Role.USER.value},
    ])
    mock_bot.bot_plugins.plugins = {
        "rooms": types.SimpleNamespace(
            JOINED_ROOMS={"room@conference.test": {"nicks": {}}},
        ),
    }
    mock_bot.client_roster = {
        "bot@example.org": {
            "subscription": "both",
            "resources": {"server": {}},
        },
        "alice@example.org": {
            "subscription": "both",
            "name": "Alice",
            "resources": {"phone": {"show": "chat"}},
        },
        "room@conference.test": {
            "subscription": "both",
            "resources": {"EnvBot": {}},
        },
        "removed@example.org": {"subscription": "remove"},
    }

    await users_mod.users_list(
        mock_bot,
        "admin@example.org",
        "nick",
        ["dm", "all"],
        mock_msg,
        False,
    )

    reply_text = mock_bot.reply.call_args.args[1]
    assert "Active/direct users (1):" in reply_text
    assert (
        "💬 alice@example.org | role=user | nick=Alice | online=yes | stored=no"
        in reply_text
    )
    assert "bot@example.org" not in reply_text
    assert "room@conference.test" not in reply_text
    assert "removed@example.org" not in reply_text


@pytest.mark.asyncio
async def test_users_delete_hides_stale_roster_contact(mock_bot, mock_msg):
    target = "dan@example.org"
    values = {
        "_direct_users": [target],
        "_room_users": [],
        "_deleted_users": [],
    }

    async def update_global(key, updater, default=None):
        values[key] = updater(values.get(key, default))
        return values[key]

    store = types.SimpleNamespace(update_global=AsyncMock(side_effect=update_global))
    mock_bot.db.users.plugin = MagicMock(return_value=store)
    mock_bot.db.users._direct_users = {target}
    mock_bot.db.users._room_users = set()
    mock_bot.db.users._deleted_users = set()
    mock_bot.db.users.get = AsyncMock(
        return_value={"jid": target, "role": users_mod.Role.USER.value}
    )
    mock_bot.db.users.delete = AsyncMock()
    mock_bot.db.users.list = AsyncMock(return_value=[])
    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
    mock_bot.boundjid = types.SimpleNamespace(bare="bot@example.org")
    mock_bot.client_roster = {
        target: {
            "subscription": "none",
            "resources": {},
        },
    }
    mock_bot.bot_plugins.plugins = {
        "rooms": types.SimpleNamespace(JOINED_ROOMS={}),
    }

    await users_mod.users_delete(
        mock_bot,
        "admin@example.org",
        "nick",
        [target],
        mock_msg,
        False,
    )
    await users_mod.users_list(
        mock_bot,
        "admin@example.org",
        "nick",
        ["active", "all"],
        mock_msg,
        False,
    )

    reply_text = mock_bot.reply.call_args.args[1]
    assert "Active/direct users (0):" in reply_text
    assert target not in reply_text
    assert mock_bot.db.users._direct_users == set()
    assert mock_bot.db.users._room_users == set()
    assert mock_bot.db.users._deleted_users == {target}
    assert values == {
        "_direct_users": [],
        "_room_users": [],
        "_deleted_users": [target],
    }


@pytest.mark.asyncio
async def test_users_delete_logic(mock_bot, mock_msg):
    with patch.object(users_mod, "prefix", ","):
        mock_bot.db.users.get = AsyncMock(
            return_value={"jid": "to@delete",
                          "role": users_mod.Role.USER.value})
        mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
        mock_bot.db.users.delete = AsyncMock()
        mock_bot.db.users._direct_users = set()
        mock_bot.db.users._room_users = set()
        mock_bot.db.users._deleted_users = set()
        store = types.SimpleNamespace(
            update_global=AsyncMock(
                side_effect=lambda key, updater, default=None: updater(default)
            )
        )
        mock_bot.db.users.plugin = MagicMock(return_value=store)
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
            assert_reply_contains(bot_reply, "usage:")
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
            mock_bot,
            "sender@example.org",
            "nick",
            ["one@example.org", "two@example.org"],
            mock_msg,
            False,
        )
        assert bot_reply.call_args.args[1].endswith("Usage: !users info [jid|nick]")

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
        assert bot_reply.call_args.args[1].endswith("Usage: !users delete <jid>")


@pytest.mark.asyncio
async def test__send_user_info_display_full(mock_bot, mock_msg):
    user_data = {
        "jid": "x@y", "nickname": "nn", "role": users_mod.Role.ADMIN.value,
        "created_at": "2024-01-01T01:00:00", "last_seen": "2024-05-01T17:00:00"
    }
    with patch.object(users_mod, "prefix", ","):
        await users_mod._send_user_info(mock_bot, mock_msg, user_data)
        assert mock_bot.reply.called


@pytest.mark.asyncio
async def test_users_list_error_branches(mock_bot, mock_msg):
    mock_bot.reply_usage = MagicMock()
    await users_mod.users_list(mock_bot, "sender", "nick", [], mock_msg, True)
    assert "private chat" in mock_bot.reply.call_args.args[1]

    await users_mod.users_list(
        mock_bot, "sender", "nick", ["active", "all", "extra"], mock_msg, False
    )
    mock_bot.reply_usage.assert_called_once()

    mock_bot.bot_plugins.plugins = {
        "rooms": types.SimpleNamespace(JOINED_ROOMS={"room@example.org": {"nicks": {}}}),
    }
    await users_mod.users_list(
        mock_bot, "sender", "nick", ["missing@example.org"], mock_msg, False
    )
    assert "Not joined" in mock_bot.reply.call_args.args[1]

    mock_bot.bot_plugins.plugins = {}
    await users_mod.users_list(
        mock_bot, "sender", "nick", ["room@example.org"], mock_msg, False
    )
    assert "Rooms plugin" in mock_bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_users_update_and_delete_command_edge_branches(mock_bot, mock_msg, monkeypatch):
    monkeypatch.setitem(config, "owner", "owner@example.org")
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
    mock_bot.db.users.create = AsyncMock()
    mock_bot.db.users.set = AsyncMock()
    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
    await users_mod.users_update(
        mock_bot, "admin@example.org", "nick", ["missing@example.org", "trusted"], mock_msg, False
    )
    assert "Created user" in mock_bot.reply.call_args.args[1]

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
async def test_users_delete_audit_events(mock_bot, mock_msg):
    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)
    mock_bot.db.users.delete = AsyncMock()
    mock_bot.db.users._direct_users = set()
    mock_bot.db.users._room_users = set()
    mock_bot.db.users._deleted_users = set()
    store = types.SimpleNamespace(
        update_global=AsyncMock(
            side_effect=lambda key, updater, default=None: updater(default)
        )
    )
    mock_bot.db.users.plugin = MagicMock(return_value=store)

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


def test_users_split_commands_preserve_command_metadata():
    expected = {
        users_mod.users_info: ("users info", ["user info"]),
        users_mod.users_list: ("users list", ["user list"]),
        users_mod.users_update: ("users role", ["user role"]),
        users_mod.users_revoke: (
            "users revoke",
            ["user revoke", "users plugin revoke", "user plugin revoke"],
        ),
        users_mod.users_delete: (
            "users delete",
            [
                "user delete",
                "users del",
                "user del",
                "users remove",
                "user remove",
                "users rm",
                "user rm",
            ],
        ),
        users_mod.users_roles: ("users roles", ["user roles"]),
        users_mod.users_permissions: (
            "users permissions",
            ["user permissions", "users perms", "user perms"],
        ),
        users_mod.users_grant: (
            "users grant",
            ["user grant", "users plugin grant", "user plugin grant"],
        ),
        users_mod.users_grants: (
            "users grants",
            ["user grants", "users plugin grants", "user plugin grants"],
        ),
        users_mod.users_admins: (
            "users admins",
            ["user admins", "users admin", "user admin"],
        ),
    }

    for handler, (command_name, aliases) in expected.items():
        assert handler._command == command_name
        assert handler._aliases == aliases
        expected_role = (
            users_mod.Role.USER
            if handler is users_mod.users_info
            else users_mod.Role.ADMIN
        )
        assert handler._required_role is expected_role
