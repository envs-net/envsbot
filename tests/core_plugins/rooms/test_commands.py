from .helpers import (
    AsyncMock,
    BOT_NICK,
    MagicMock,
    ROOM_JID,
    patch,
    patch_reply_methods,
    pytest,
    rooms,
    types,
)
from core_plugins.rooms import commands as commands_module
from core_plugins.rooms import settings as settings_module
from core_plugins.rooms import state as state_module
from utils.command import Role


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
async def test_rooms_add(fake_bot, fake_msg):
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.db.rooms.add = AsyncMock()
    with patch("core_plugins.rooms.commands.set_room_control_defaults", AsyncMock()):
        with patch("core_plugins.rooms.commands.is_valid_room_jid",
                   AsyncMock(return_value=True)):
            msg = dict(fake_msg)
            msg["from"].bare = "room@conference.domain"
            await rooms.rooms_add(fake_bot, "s", "s",
                                  ["room@conference.domain", "BotNick"],
                                  msg, False)


@pytest.mark.asyncio
async def test_rooms_add_already_exists(fake_bot, fake_msg):
    fake_bot.db.rooms.get = AsyncMock(return_value=(1, 2, 3, 4))
    with patch("core_plugins.rooms.commands.is_valid_room_jid",
               AsyncMock(return_value=True)):
        await rooms.rooms_add(fake_bot, "s", "s",
                              ["room@conference.domain", "BotNick"],
                              fake_msg, False)


@pytest.mark.asyncio
async def test_rooms_update(fake_bot, fake_msg):
    fake_bot.db.rooms.update = AsyncMock()
    with patch("core_plugins.rooms.commands.is_valid_room_jid",
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
    with patch("core_plugins.rooms.commands.is_valid_room_jid",
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


@pytest.mark.asyncio
async def test_rooms_delete_reports_not_used_without_delete_log(fake_bot, fake_msg):
    room_jid = "room@conference.domain"
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.db.rooms.delete = AsyncMock()

    with patch("core_plugins.rooms.commands.is_valid_room_jid", AsyncMock(return_value=True)), \
            patch("core_plugins.rooms.commands.audit_event", AsyncMock()) as audit, \
            patch("core_plugins.rooms.commands.log.info") as log_info:
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
    assert "MUC rooms (2): stored=2 | joined=1" in listing
    room_a_lines = [line for line in listing if "room@conference.a" in line]
    room_b_lines = [line for line in listing if "room@conference.b" in line]
    assert len(room_a_lines) == 1
    assert len(room_b_lines) == 1
    assert "✅" in room_a_lines[0]
    assert "affiliation=admin" in room_a_lines[0]
    assert "⚪" in room_b_lines[0]
    assert "status=" not in room_b_lines[0]

    # Test with no rows and no joined rooms.
    fake_bot.db.rooms.list = AsyncMock(return_value=[])
    rooms.JOINED_ROOMS.clear()
    await rooms.rooms_list(fake_bot, "jid", "nick", [], MagicMock(), False)
    listing = fake_bot.reply.call_args.args[1]
    assert "MUC rooms (0): stored=0 | joined=0" in listing
    assert "• none" in listing


@pytest.mark.asyncio
async def test_rooms_list_merges_presence_only_runtime_rooms(fake_bot):
    fake_bot.db.rooms.list = AsyncMock(return_value=[
        ("stored@conference.test", "StoredBot", True, None),
    ])
    fake_bot.presence.joined_rooms = {
        "runtime@conference.test": "RuntimeBot",
    }

    await rooms.rooms_list(fake_bot, "jid", "nick", ["muc", "all"], MagicMock(), False)

    listing = fake_bot.reply.call_args.args[1]
    assert "MUC rooms (2): stored=1 | joined=1" in listing
    runtime_line = next(line for line in listing if "runtime@conference.test" in line)
    assert "✅" in runtime_line
    assert "nick=RuntimeBot" in runtime_line
    assert "stored=no" in runtime_line


@pytest.mark.asyncio
async def test_rooms_list_dm_shows_roster_contacts(fake_bot):
    fake_bot.client_roster = {
        "bot@domain": {
            "subscription": "both",
            "resources": {"BotNick": {}},
        },
        "alice@example.org": {
            "subscription": "both",
            "name": "Alice",
            "resources": {"desktop": {"show": "chat"}},
        },
        "bob@example.org": {
            "subscription": "from",
            "pending_out": True,
            "resources": {},
        },
        "removed@example.org": {
            "subscription": "remove",
        },
    }

    await rooms.rooms_list(fake_bot, "jid", "nick", ["1:1", "all"], MagicMock(), False)

    listing = fake_bot.reply.call_args.args[1]
    assert listing[0] == "💬 Direct contacts"
    assert "Direct contacts (2): online=1" in listing
    assert any(
        "🟢 alice@example.org" in line
        and "subscription=both" in line
        and "name=Alice" in line
        for line in listing
    )
    assert any(
        "⚪ bob@example.org" in line
        and "subscription=from" in line
        and "pending=out" in line
        for line in listing
    )
    assert not any("bot@domain" in line for line in listing)
    assert not any("removed@example.org" in line for line in listing)
    fake_bot.db.rooms.list.assert_not_awaited()


@pytest.mark.asyncio
async def test_rooms_list_dm_handles_missing_roster_and_bad_args(fake_bot):
    fake_bot.client_roster = None
    msg = MagicMock()

    await rooms.rooms_list(fake_bot, "jid", "nick", ["dm"], msg, False)
    listing = fake_bot.reply.call_args.args[1]
    assert "Direct contacts (0): online=0" in listing
    assert "• none" in listing

    fake_bot.reply.reset_mock()
    await rooms.rooms_list(fake_bot, "jid", "nick", ["dm", "all", "extra"], msg, False)
    fake_bot.reply.assert_not_called()
    fake_bot.reply_usage.assert_called_once_with(
        msg,
        "!rooms list [muc|dm|1:1] [<page>|last|all]",
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
    with patch("core_plugins.rooms.lifecycle.autojoin_rooms", AsyncMock()) as autojoin:
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
    monkeypatch.setattr(settings_module, "get_room_feature", AsyncMock(side_effect=KeyError))
    await rooms._handle_room_feature_toggle(fake_bot, "admin@example.org", fake_msg, False, ["unknown"], enabled=True)
    assert "Unknown room plugin" in fake_bot.reply_warn.call_args.args[1]

    previous = types.SimpleNamespace(name="pin", enabled=True)
    state = types.SimpleNamespace(name="pin", enabled=True)
    monkeypatch.setattr(settings_module, "get_room_feature", AsyncMock(return_value=previous))
    monkeypatch.setattr(settings_module, "set_room_feature", AsyncMock(return_value=state))
    monkeypatch.setattr(settings_module, "format_room_feature_line", lambda state: "pin: enabled")
    await rooms._handle_room_feature_toggle(fake_bot, "admin@example.org", fake_msg, False, ["pin"], enabled=True)
    assert "already enabled" in fake_bot.reply_info.call_args.args[1]

    state = types.SimpleNamespace(name="pin", enabled=False)
    monkeypatch.setattr(settings_module, "set_room_feature", AsyncMock(return_value=state))
    monkeypatch.setattr(settings_module, "audit_event", AsyncMock())
    await rooms._handle_room_feature_toggle(fake_bot, "admin@example.org", fake_msg, False, ["pin"], enabled=False)
    settings_module.audit_event.assert_awaited_once()
    assert "pin is now disabled" in fake_bot.reply_ok.call_args.args[1]


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
    fake_bot.get_user_role = AsyncMock(return_value=Role.NONE)
    fake_bot.db.rooms.get = AsyncMock(return_value=(target_room, "BotNick", True, None))
    previous = types.SimpleNamespace(name="pin", enabled=True)
    state = types.SimpleNamespace(name="pin", enabled=False)
    monkeypatch.setattr(settings_module, "get_room_feature", AsyncMock(return_value=previous))
    monkeypatch.setattr(settings_module, "set_room_feature", AsyncMock(return_value=state))
    monkeypatch.setattr(settings_module, "audit_event", AsyncMock())

    await rooms.cmd_room_disable(
        fake_bot,
        "owner@example.org",
        None,
        [target_room, "pin"],
        fake_msg,
        False,
    )

    settings_module.set_room_feature.assert_awaited_once_with(fake_bot, target_room, "pin", False)
    assert f"pin is now disabled for {target_room}" in fake_bot.reply_ok.call_args.args[1]


@pytest.mark.asyncio
async def test_room_settings_explicit_admin_room_allows_bot_admin(fake_bot, fake_msg, monkeypatch):
    patch_reply_methods(fake_bot)
    fake_msg["type"] = "groupchat"
    fake_msg["from"].bare = "admins@conference.test"
    fake_msg["from"].resource = "AdminNick"
    target_room = "target@conference.test"
    fake_bot.get_user_role = AsyncMock(return_value=Role.ADMIN)
    fake_bot.db.rooms.get = AsyncMock(return_value=(target_room, "BotNick", True, None))
    previous = types.SimpleNamespace(name="weather", enabled=False)
    state = types.SimpleNamespace(name="weather", enabled=True)
    monkeypatch.setattr(settings_module, "get_room_feature", AsyncMock(return_value=previous))
    monkeypatch.setattr(settings_module, "set_room_feature", AsyncMock(return_value=state))
    monkeypatch.setattr(settings_module, "audit_event", AsyncMock())

    await rooms.cmd_room_enable(
        fake_bot,
        "admin@example.org",
        "AdminNick",
        [target_room, "weather"],
        fake_msg,
        True,
    )

    settings_module.set_room_feature.assert_awaited_once_with(fake_bot, target_room, "weather", True)
    assert f"weather is now enabled for {target_room}" in fake_bot.reply_ok.call_args.args[1]


@pytest.mark.asyncio
async def test_room_settings_public_room_without_target_uses_current_room(fake_bot, fake_msg, monkeypatch):
    patch_reply_methods(fake_bot)
    fake_msg["type"] = "groupchat"
    fake_msg["from"].bare = ROOM_JID
    rooms.JOINED_ROOMS[ROOM_JID] = {"nick": "BotNick", "nicks": {}}
    fake_bot.get_user_role = AsyncMock(return_value=Role.MODERATOR)
    monkeypatch.setattr(
        commands_module,
        "list_room_features",
        AsyncMock(return_value=[types.SimpleNamespace(name="pin", enabled=True, default=True, modified=False)]),
    )
    monkeypatch.setattr(commands_module, "format_room_feature_line", lambda state: f"• {state.name}: on")

    await rooms.cmd_room_plugins(fake_bot, "mod@example.org", "ModNick", ["all"], fake_msg, True)

    commands_module.list_room_features.assert_awaited_once_with(fake_bot, ROOM_JID)
    assert f"Plugin settings for room '{ROOM_JID}'" in fake_bot.reply.call_args.args[1][0]


@pytest.mark.asyncio
async def test_room_diagnose_lines_handles_missing_room_and_bad_row(fake_bot, monkeypatch):
    room_jid = "missing@conference.test"
    fake_bot.db.rooms.get = AsyncMock(return_value=None)
    fake_bot.presence.joined_rooms = {}
    fake_bot.pending_room_invites = {}
    monkeypatch.setattr(state_module, "list_room_features", AsyncMock(return_value=[]))

    lines = await rooms._room_diagnose_lines(fake_bot, room_jid)

    assert "Known in DB: no" in lines
    assert "Currently joined: no" in lines
    assert "Presence joined: no" in lines
    assert "Pending invites: 0" in lines
    assert "Enabled room plugins (0): none" in lines
    assert "Disabled room plugins (0): none" in lines
    assert rooms._yes_no(object()) == "yes"
    assert rooms._yes_no(None) == "no"
