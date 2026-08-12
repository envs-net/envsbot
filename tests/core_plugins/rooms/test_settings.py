from .helpers import (
    AsyncMock,
    BOT_NICK,
    DummyPluginStore,
    patch,
    patch_reply_methods,
    pin_plugin,
    poll_plugin,
    pytest,
    rooms,
    rss_plugin,
    types,
    xkcd_plugin,
)
from core_plugins.rooms import commands as commands_module
from core_plugins.rooms import state as state_module
from plugins.rss import lifecycle as rss_lifecycle
from utils.command import Role
from utils.config import config


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
        config,
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
        config,
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
    with patch("core_plugins.rooms.commands.set_room_control_defaults", AsyncMock()):
        await rooms.cmd_room_setdefaults(fake_bot, "jid", "nick", [],
                                         fake_msg, False)
        # Error case: trigger inside the try/except block!
        with patch("core_plugins.rooms.commands.set_room_control_defaults",
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


def test_cmd_room_plugins_registers_list_aliases():
    assert "rooms plugins list" in rooms.cmd_room_plugins._command_names
    assert "room plugins list" in rooms.cmd_room_plugins._command_names


@pytest.mark.asyncio
async def test_cmd_room_plugins_accepts_list_all_page_args(
    fake_bot, fake_msg, monkeypatch
):
    room_jid = fake_msg["from"].bare
    rooms.JOINED_ROOMS[room_jid] = {"nick": BOT_NICK, "nicks": {}}
    features = [
        types.SimpleNamespace(
            name=f"plugin_{i:02d}",
            enabled=True,
            default=True,
            modified=False,
        )
        for i in range(13)
    ]
    monkeypatch.setattr(
        commands_module, "list_room_features", AsyncMock(return_value=features)
    )
    monkeypatch.setattr(
        commands_module,
        "format_room_feature_line",
        lambda state: f"• {state.name}: enabled",
    )

    await rooms.cmd_room_plugins(
        fake_bot,
        "jid",
        "nick",
        ["list", "all"],
        fake_msg,
        True,
    )

    reply_lines = fake_bot.reply.call_args.args[1]
    assert reply_lines[0] == f"📋 Plugin settings for room '{room_jid}'"
    assert "Use " not in reply_lines[-1]
    assert sum(1 for line in reply_lines if line.startswith("• plugin_")) == 13
    assert any("plugin_12" in line for line in reply_lines)


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
    monkeypatch.setattr(rss_lifecycle, "_cancel_feed_task", cancel_feed_task)

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

    with patch("core_plugins.rooms.commands.is_valid_room_jid", AsyncMock(return_value=True)):
        await rooms.rooms_delete(fake_bot, "jid", "nick", [room_jid], fake_msg, False)

    assert stores["rss"]["RSS"] == {
        feed_keep: {"feed_no": 1, "rooms": [other_room], "period": 42},
        "https://example.org/other.xml": {"feed_no": 3, "rooms": [other_room]},
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

    with patch("core_plugins.rooms.commands.is_valid_room_jid", AsyncMock(return_value=True)), \
            patch("core_plugins.rooms.commands.audit_event", AsyncMock()) as audit, \
            patch("core_plugins.rooms.commands.log.info") as log_info:
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
async def test_room_setdefaults_explicit_target_from_dm(fake_bot, fake_msg, monkeypatch):
    patch_reply_methods(fake_bot)
    target_room = "target@conference.test"
    fake_msg["type"] = "chat"
    fake_msg["from"].bare = "admin@example.org"
    fake_bot.get_user_role = AsyncMock(return_value=Role.ADMIN)
    fake_bot.db.rooms.get = AsyncMock(return_value=(target_room, "BotNick", True, None))
    defaults = AsyncMock()
    monkeypatch.setattr(commands_module, "set_room_control_defaults", defaults)
    monkeypatch.setattr(commands_module, "audit_event", AsyncMock())

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


def test_plugin_cleanup_summary_helpers_cover_generic_plugin_hook_shapes():
    plugin_summary = {
        "rss": {"subscriptions": "2", "feeds": 1},
        "xkcd": {"legacy_rooms": "3"},
        "pin": {"rooms": 1, "data": "4"},
        "reminder": {"reminders": 2, "tasks": "ignored"},
        "bad": {"rooms": "nope"},
        "plain": "ignored",
    }

    summary = {"toggles": 0, "plugin_hooks": plugin_summary}

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
        state_module,
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
    assert not any("Presence routing" in line for line in lines)
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
