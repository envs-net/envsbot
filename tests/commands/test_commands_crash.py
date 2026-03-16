import pytest
from unittest.mock import AsyncMock
from utils.command import Role


@pytest.mark.asyncio
async def test_commands_do_not_crash(bot, xmpp_msg):
    """
    Ensure that every registered command can be invoked without raising
    an unhandled exception.

    This test runs each command through the normal command handler
    while mocking the permission system so that commands can execute
    in isolation from the full runtime environment.
    """

    # Mock permission system
    bot.get_user_role = AsyncMock(return_value=Role.OWNER)

    for name in bot.commands:

        # Test Direct Message
        xmpp_msg["body"] = f",{name} test"

        try:
            await bot.handle_command(
                xmpp_msg["body"],
                "user@test.local",
                None,
                xmpp_msg,
                False
            )

        except Exception as e:
            pytest.fail(f"Command '{name}' crashed: {e}")

        # Test Group Message
        xmpp_msg["type"] = "groupchat"
        xmpp_msg["body"] = f",{name} test"

        try:
            await bot.handle_command(
                xmpp_msg["body"],
                xmpp_msg["from"],
                "nick",
                xmpp_msg,
                False
            )

        except Exception as e:
            pytest.fail(f"Command '{name}' crashed: {e}")
