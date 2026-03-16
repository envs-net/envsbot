import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_private_message_triggers_command(bot, xmpp_msg):

    bot.handle_command = AsyncMock()

    xmpp_msg["body"] = ",help"

    await bot.on_private_message(xmpp_msg)

    assert bot.handle_command.called


@pytest.mark.asyncio
async def test_groupchat_command_execution(bot, xmpp_msg):
    """
    Ensure commands work correctly when received in a groupchat.
    """

    xmpp_msg["type"] = "groupchat"
    xmpp_msg["body"] = ",_ping"

    bot._reply_rate = {}

    await bot.handle_command(
        xmpp_msg["body"],
        xmpp_msg["from"].bare,
        "nick",
        xmpp_msg,
        True
    )

    assert "test pong" in xmpp_msg.replies


@pytest.mark.asyncio
async def test_bot_does_not_reply_to_itself(bot, xmpp_msg):
    """
    Ensure the bot ignores its own messages.
    """

    xmpp_msg["body"] = ",_ping"
    xmpp_msg["type"] = "groupchat"
    xmpp_msg["mucnick"] = xmpp_msg["from"].resource

    bot.presence.joined_rooms[xmpp_msg["from"].bare] = xmpp_msg["from"].resource

    await bot.on_muc_message(xmpp_msg)

    assert not xmpp_msg.replies
