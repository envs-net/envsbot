from .helpers import *  # noqa: F401,F403


@pytest.mark.asyncio
async def test_bot_has_privilege():
    rooms.JOINED_ROOMS["room"] = {"affiliation": "owner"}
    assert rooms.bot_has_privilege("room") is True
    rooms.JOINED_ROOMS["room"] = {"affiliation": "member"}
    assert rooms.bot_has_privilege("room") is False
    assert rooms.bot_has_privilege("room_notexist") is False


@pytest.mark.asyncio
async def test_room_settings_rejects_unprivileged_explicit_target(fake_bot, fake_msg):
    patch_reply_methods(fake_bot)
    target_room = "target@conference.test"
    fake_msg["type"] = "chat"
    fake_msg["from"].bare = "user@example.org"
    rooms.JOINED_ROOMS[target_room] = {
        "nick": "BotNick",
        "nicks": {"UserNick": {"jid": "user@example.org", "affiliation": "member"}},
    }
    fake_bot.get_user_role = AsyncMock(return_value=rooms.Role.USER)
    fake_bot.db.rooms.get = AsyncMock(return_value=(target_room, "BotNick", True, None))

    await rooms.cmd_room_enable(
        fake_bot,
        "user@example.org",
        None,
        [target_room, "pin"],
        fake_msg,
        False,
    )

    assert "Only room admins/owners" in fake_bot.reply_error.call_args.args[1]
