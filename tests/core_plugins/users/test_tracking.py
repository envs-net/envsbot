from .helpers import *  # noqa: F401,F403


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
    mock_bot.bot_plugins.plugins = {
        'rooms': types.SimpleNamespace(bot_has_privilege=bot_has_priv)
    }
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

    monkeypatch.setattr(users_mod, "MAX_ROOM_NICKS", 2)

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
