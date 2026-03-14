"""
Bot command integration tests.

These tests verify that the bot command pipeline works correctly.
They exercise the real command resolver, permission checks, and
plugin command handlers using the test plugin.
"""

import pytest
from unittest.mock import AsyncMock
from command import Role


@pytest.mark.asyncio
async def test_ping_command(bot, xmpp_msg):

    bot.get_user_role = AsyncMock(return_value=Role.USER)

    xmpp_msg["body"] = ",ping"

    replies = []

    def capture_reply(msg, text, **kwargs):
        replies.append(text)

    bot.reply = capture_reply

    await bot.handle_command(
        xmpp_msg["body"],
        "user@test.local",
        None,
        xmpp_msg,
        False
    )

    assert replies
    assert replies[0] == "pong"

@pytest.mark.asyncio
async def test_unknown_command(bot, xmpp_msg):
    """
    Test that unknown commands are ignored.
    """

    bot.get_user_role = AsyncMock(return_value=1)

    xmpp_msg["body"] = ",doesnotexist"

    bot.reply = lambda *args, **kwargs: pytest.fail("Bot replied unexpectedly")

    await bot.handle_command(
        xmpp_msg["body"],
        "user@test.local",
        None,
        xmpp_msg,
        False
    )


@pytest.mark.asyncio
async def test_no_prefix_ignored(bot, xmpp_msg):
    """
    Messages without the command prefix should be ignored.
    """

    xmpp_msg["body"] = "ping"

    bot.reply = lambda *args, **kwargs: pytest.fail("Bot replied unexpectedly")

    await bot.handle_command(
        xmpp_msg["body"],
        "user@test.local",
        None,
        xmpp_msg,
        False
    )


@pytest.mark.asyncio
async def test_private_message_triggers_command(bot, xmpp_msg):
    """
    Test that private messages are routed into handle_command().
    """

    bot.handle_command = AsyncMock()

    xmpp_msg["body"] = ",ping"

    await bot.on_private_message(xmpp_msg)

    bot.handle_command.assert_called_once()


@pytest.mark.asyncio
async def test_groupchat_message_triggers_command(bot, xmpp_msg):
    """
    Test that groupchat messages are routed into handle_command().
    """

    bot.handle_command = AsyncMock()

    xmpp_msg["type"] = "groupchat"
    xmpp_msg["body"] = ",ping"
    xmpp_msg["mucnick"] = "tester"

    xmpp_msg["from"].bare = "room@test"
    xmpp_msg["from"].resource = "tester"

    bot.presence.joined_rooms["room@test"] = "bot"

    await bot.on_muc_message(xmpp_msg)

    bot.handle_command.assert_called_once()
