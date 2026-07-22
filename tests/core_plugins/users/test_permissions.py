from .helpers import (
    AsyncMock,
    MagicMock,
    core_plugins,
    patch,
    pytest,
    users_mod,
)
from utils.config import config
from core_plugins.users import formatting as formatting_module


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
async def test_users_role_creates_unknown_user_after_permission_check(mock_bot, mock_msg):
    mock_bot.db.users.get = AsyncMock(return_value=None)
    mock_bot.db.users.create = AsyncMock()
    mock_bot.db.users.set = AsyncMock()
    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)

    await users_mod.users_update(
        mock_bot,
        "admin@example.org",
        "nick",
        ["new@example.org", "trusted"],
        mock_msg,
        False,
    )

    mock_bot.db.users.create.assert_awaited_once_with("new@example.org")
    mock_bot.db.users.set.assert_awaited_once_with(
        "new@example.org",
        "role",
        users_mod.Role.TRUSTED.value,
    )
    assert "Created user new@example.org with role trusted" in mock_bot.reply.call_args.args[1]
    mock_bot.audit.assert_awaited_with(
        "user_role_changed",
        actor="admin@example.org",
        target="new@example.org",
        details={
            "plugin": "users",
            "old_role": "user",
            "new_role": "trusted",
            "created": True,
        },
    )


@pytest.mark.asyncio
async def test_users_role_does_not_create_unknown_user_when_change_is_denied(mock_bot, mock_msg):
    mock_bot.db.users.get = AsyncMock(return_value=None)
    mock_bot.db.users.create = AsyncMock()
    mock_bot.get_user_role = AsyncMock(return_value=users_mod.Role.ADMIN)

    await users_mod.users_update(
        mock_bot,
        "admin@example.org",
        "nick",
        ["new@example.org", "superadmin"],
        mock_msg,
        False,
    )

    mock_bot.db.users.create.assert_not_awaited()
    assert "Only the owner" in mock_bot.reply.call_args.args[1]


@pytest.mark.asyncio
async def test_role_helper_permission_guard_branches(mock_bot, monkeypatch):
    monkeypatch.setitem(config, "owner", "owner@example.org")
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
        users_mod.Role.ADMIN,
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
    monkeypatch.setitem(config, "owner", "owner@example.org")
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
async def test_users_roles_and_admins_output(mock_bot, mock_msg, monkeypatch):
    monkeypatch.setitem(config, "owner", "owner@example.org")
    mock_bot.prefix = ","

    await users_mod.users_roles(mock_bot, "sender", "nick", [], mock_msg, False)
    roles_text = "\n".join(mock_bot.reply.call_args.args[1])
    assert "owner" in roles_text
    assert "superadmin" in roles_text

    monkeypatch.setitem(config, "owner", "owner@example.org/resource")
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

    monkeypatch.setattr(formatting_module, "audit_event", AsyncMock())

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


@pytest.mark.asyncio
async def test_users_permissions_rejects_unknown_jid(mock_msg):
    bot = MagicMock()
    bot.db.users.get = AsyncMock(return_value=None)
    bot.db.users.plugin = MagicMock()
    bot.reply = MagicMock()

    await users_mod.users_permissions(
        bot,
        "admin@example.org",
        "admin",
        ["missing@example.org"],
        mock_msg,
        False,
    )

    assert bot.reply.call_args.args[1] == "🟡️ User not found: missing@example.org"
    bot.db.users.plugin.assert_not_called()


@pytest.mark.asyncio
async def test_users_permissions_allows_unstored_config_owner(mock_msg, monkeypatch):
    class Store:
        async def get(self, jid, key):
            assert jid == "owner@example.org"
            assert key == users_mod.GRANTS_FIELD
            return []

    monkeypatch.setitem(config, "owner", "owner@example.org/resource")
    bot = MagicMock()
    bot.db.users.get = AsyncMock(return_value=None)
    bot.db.users.plugin.return_value = Store()
    bot.reply = MagicMock()

    await users_mod.users_permissions(
        bot,
        "admin@example.org",
        "admin",
        ["owner@example.org"],
        mock_msg,
        False,
    )

    reply = bot.reply.call_args.args[1]
    assert "Permission diagnostics" in reply
    assert "Bot role: owner" in reply


@pytest.mark.asyncio
async def test_users_permissions_reports_role_grants_and_room_access(mock_msg):
    class Store:
        async def get(self, jid, key):
            assert jid == "alice@example.org"
            assert key == users_mod.GRANTS_FIELD
            return ["rss"]

    class MucPlugin:
        async def get_affiliation_list(self, room, affiliation):
            assert room == "room@conference.example.org"
            if affiliation == "owner":
                return []
            if affiliation == "admin":
                return [{"jid": "alice@example.org/resource"}]
            return []

    bot = MagicMock()
    bot.db.users.get = AsyncMock(return_value={
        "jid": "alice@example.org",
        "role": users_mod.Role.USER.value,
    })
    bot.db.users.plugin.return_value = Store()
    bot.plugin = {"xep_0045": MucPlugin()}
    bot.prefix = ","
    bot.reply = MagicMock()

    await users_mod.users_permissions(
        bot,
        "admin@example.org",
        "admin",
        ["alice@example.org", "room@conference.example.org"],
        mock_msg,
        False,
    )

    reply = bot.reply.call_args.args[1]
    assert "Permission diagnostics" in reply
    assert "Bot role: user" in reply
    assert "Plugin grants: rss" in reply
    assert "Room admin/owner: yes (live)" in reply
    assert "• rss: yes (grant + room admin/owner)" in reply
    assert "• pin: no (missing grant or room affiliation)" in reply


def test_grantable_plugin_names_are_stable_and_human_readable():
    assert users_mod._grantable_plugin_names() == "rss, pin, poll"
