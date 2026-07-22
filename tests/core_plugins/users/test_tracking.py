from .helpers import (
    AsyncMock,
    FakeUserManager,
    MagicMock,
    patch,
    pytest,
    types,
    users_mod,
)
from core_plugins.users import tracking as tracking_module


@pytest.mark.asyncio
async def test_on_muc_presence_adds_and_tracks_nick(mock_bot, mock_msg):
    pres = {
        "type": "available",
        "muc": {"room": "room1@conference.x", "nick": "john", "jid":
                MagicMock(bare="john@foo.bar")},
        "from": MagicMock(),
    }
    with patch("core_plugins.users.tracking.track_room_nick", new=AsyncMock()) as track, \
            patch("core_plugins.users.tracking.update_last_seen",
                  new=AsyncMock()) as last_seen:
        await users_mod.on_muc_presence(mock_bot, pres)
        track.assert_awaited()
        last_seen.assert_awaited()


@pytest.mark.asyncio
async def test_on_groupchat_message_updates_last_seen(mock_bot, mock_msg):
    bot_has_priv = MagicMock(return_value=True)
    mock_bot.bot_plugins.plugins = {
        'rooms': types.SimpleNamespace(bot_has_privilege=bot_has_priv)
    }
    mock_msg['muc'] = {"room": "room-A", "nick": "Nick"}
    mock_bot.plugin = {"xep_0045": MagicMock(
        get_jid_property=lambda r, n, s: "realjid@x")}
    with patch("core_plugins.users.tracking.update_last_seen",
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

    with patch("core_plugins.users.tracking.track_room_nick", new=AsyncMock()) as track, \
            patch("core_plugins.users.tracking.update_last_seen",
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

    with patch("core_plugins.users.tracking.update_last_seen",
               new=AsyncMock()) as last_seen:
        await users_mod.on_groupchat_message(mock_bot, mock_msg)

    last_seen.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_private_message_creates_and_tracks_direct_user(mock_bot):
    mock_bot.boundjid = types.SimpleNamespace(bare="bot@example.org")
    mock_bot._is_muc_private_message = MagicMock(return_value=False)
    mock_bot.db.users.get = AsyncMock(return_value=None)
    mock_bot.db.users.create = AsyncMock()
    msg = {
        "type": "chat",
        "from": "member@example.org/phone",
        "get": lambda key, default=None: (
            "chat" if key == "type" else default
        ),
    }

    with patch(
        "core_plugins.users.tracking.update_last_seen",
        new=AsyncMock(),
    ) as last_seen:
        await users_mod.on_private_message(mock_bot, msg)

    mock_bot.db.users.create.assert_awaited_once_with("member@example.org")
    last_seen.assert_awaited_once_with(mock_bot, "member@example.org")


@pytest.mark.asyncio
async def test_on_private_message_skips_muc_pm_and_own_messages(mock_bot):
    mock_bot.boundjid = types.SimpleNamespace(bare="bot@example.org")
    mock_bot.db.users.get = AsyncMock()
    mock_bot.db.users.create = AsyncMock()
    msg = {
        "type": "chat",
        "from": "room@conference.example.org/member",
        "get": lambda key, default=None: (
            "chat" if key == "type" else default
        ),
    }

    mock_bot._is_muc_private_message = MagicMock(return_value=True)
    await users_mod.on_private_message(mock_bot, msg)
    mock_bot.db.users.get.assert_not_awaited()

    mock_bot._is_muc_private_message = MagicMock(return_value=False)
    msg["from"] = "bot@example.org/resource"
    await users_mod.on_private_message(mock_bot, msg)
    mock_bot.db.users.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_users_on_load_registers_direct_message_runtime_handler(mock_bot):
    store = AsyncMock()
    store.get_global = AsyncMock(return_value={})
    mock_bot.db.users.plugin = MagicMock(return_value=store)

    await users_mod.on_load(mock_bot)

    mock_bot.bot_plugins.register_runtime_event.assert_called_once()
    args = mock_bot.bot_plugins.register_runtime_event.call_args.args
    assert args[:2] == ("users", "private_message_received")


@pytest.mark.asyncio
async def test_track_room_nick(build_mock_bot, monkeypatch):
    bot = build_mock_bot()
    plugin_store = AsyncMock()
    plugin_store.get = AsyncMock(return_value={
        "roomY": ["oldnick", "oldernick"],
        "roomZ": ["sharednick"],
    })
    plugin_store.set = AsyncMock()
    user_store = FakeUserManager(
        plugin_store=plugin_store,
        nick_index={
            "nickname": ["other@x"],
            "oldnick": ["jid@x", "other@x"],
            "stale": ["jid@x"],
        },
    )
    bot.db.users = user_store

    monkeypatch.setattr(tracking_module, "MAX_ROOM_NICKS", 2)

    await users_mod.track_room_nick(bot, "jid@x", "roomY", "nickname")

    user_store.create.assert_awaited_once_with("jid@x", "nickname")
    plugin_store.set.assert_awaited_once_with(
        "jid@x",
        "roomnicks",
        {
            "roomY": ["nickname", "oldnick"],
            "roomZ": ["sharednick"],
        },
    )
    assert user_store.nick_index == {
        "nickname": ["other@x", "jid@x"],
        "oldnick": ["other@x", "jid@x"],
        "sharednick": ["jid@x"],
    }


@pytest.mark.asyncio
async def test_update_last_seen_newer_skipped(build_mock_bot):
    bot = build_mock_bot()
    bot.db.users.get = AsyncMock(
        return_value={"last_seen": "2099-01-01T01:01:01+00:00"})
    await users_mod.update_last_seen(bot, "jidtoignore@x")


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
    with patch("core_plugins.users.tracking.update_last_seen", new=AsyncMock()) as last_seen:
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
