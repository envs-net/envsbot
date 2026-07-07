from .helpers import (
    AsyncMock,
    MagicMock,
    assert_reply_contains,
    patch,
    pytest,
    types,
    users_mod,
)


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
            assert_reply_contains(bot_reply, "multiple users found")
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
            assert_reply_contains(bot_reply, "usage:")


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
    fake_rooms = types.SimpleNamespace(JOINED_ROOMS=users_mod.JOINED_ROOMS)
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
    fake_rooms = types.SimpleNamespace(JOINED_ROOMS=users_mod.JOINED_ROOMS)
    mock_bot.bot_plugins.plugins = {"rooms": fake_rooms}
    with (patch.object(users_mod, "prefix", ","),
          patch.object(mock_bot, "reply") as bot_reply):
        await users_mod.users_list(mock_bot, "send", "nick", ["room-B"],
                                   mock_msg, False)
        assert bot_reply.call_args.args[1] == "ℹ️ No users found in room: room-B"


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
            mock_bot, "sender", "nick", [], mock_msg, False
        )
        assert bot_reply.call_args.args[1].endswith("Usage: !users info <jid|nick>")

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


def test_users_split_commands_preserve_command_metadata():
    expected = {
        users_mod.users_info: ("users info", ["user info"]),
        users_mod.users_list: ("users list", ["user list"]),
        users_mod.users_update: ("users role", ["user role"]),
        users_mod.users_revoke: (
            "users revoke",
            ["user revoke", "users plugin revoke", "user plugin revoke"],
        ),
        users_mod.users_delete: ("users delete", ["user delete"]),
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
        assert handler._required_role is users_mod.Role.ADMIN
