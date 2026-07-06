from .helpers import *  # noqa: F401,F403


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
