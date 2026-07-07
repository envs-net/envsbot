from .helpers import (
    AsyncMock,
    FakeUserManager,
    pytest,
    users_mod,
)


@pytest.mark.asyncio
async def test_find_users_by_nick_safe_sorts_and_handles_missing(build_mock_bot):
    bot = build_mock_bot()
    bot.db.users = FakeUserManager(
        plugin_store=AsyncMock(),
        nick_index={
            "Nick": ["z@example.net", "a@example.net"],
            "Other": ["other@example.net"],
        },
    )

    assert await users_mod.find_users_by_nick_safe(bot, "Nick") == [
        "a@example.net",
        "z@example.net",
    ]
    assert await users_mod.find_users_by_nick_safe(bot, "Missing") == []
