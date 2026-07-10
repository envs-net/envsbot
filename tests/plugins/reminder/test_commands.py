from .helpers import (
    AsyncMock,
    datetime,
    pytest,
    re,
    reminder,
)


@pytest.mark.asyncio
async def test_remind_command_and_status_controls(dummy_bot, dummy_msg):
    # Room-enabled and plugin ON by default
    reminder.REMINDER_ENABLED = True
    dummy_msg["from"].bare = "rome@conf"
    dummy_msg["from"].resource = "TestUser"
    # Accept normal DM
    await reminder.remind_command(dummy_bot, "a@b", "TestNick",
                                  ["10s", "hello"], dummy_msg, False)
    dummy_bot.reply.assert_any_call(
        dummy_msg, "✅ Reminder set! I'll remind you in 10s")

    # Too few args
    await reminder.remind_command(dummy_bot, "a@b", "TestNick", [],
                                  dummy_msg, False)
    text = "ℹ️ Usage: ,remind <duration|date time> <message>\n"
    text += "Example: ,remind 30m Take a break\n"
    text += "Example: ,remind 2026-05-01 14:30 Take a break\n"
    text += "Example: ,remind 2026-05-01 14:30 CEST Take a break\n"
    text += "Example: ,remind 01.05.2026 14:30 Take a break\n"
    text += "Formats: 10s, 5m, 1h, 2d, 1h30m,"
    text += " YYYY-MM-DD HH:MM, DD.MM.YYYY HH:MM, optional TZ (max 365 days)"
    dummy_bot.reply.assert_any_call(
        dummy_msg, text)

    # Plugin disbled
    reminder.REMINDER_ENABLED = False
    await reminder.remind_command(dummy_bot, "a@b", "TestNick", ["10s", "msg"],
                                  dummy_msg, False)
    dummy_bot.reply.assert_any_call(
        dummy_msg, "⏸️ Reminder plugin is globally off."
        " Use ,remind on in a DM to enable it.")

    # Enable via command in DM
    dummy_bot.reply.reset_mock()
    reminder.REMINDER_ENABLED = False
    await reminder.remind_command(dummy_bot, "a@b", "TestNick", ["on"],
                                  dummy_msg, False)
    dummy_bot.reply.assert_any_call(
        dummy_msg, "▶️ Reminder plugin enabled globally."
        " Restored 0 pending reminder task(s).")

    # Disable global
    await reminder.remind_command(dummy_bot, "a@b", "TestNick",
                                  ["off"], dummy_msg, False)
    assert any(
        re.match(
            r"⏸️ Reminder plugin disabled globally\. " +
            r"Pending reminders stay saved\. " +
            r"Cancelled \d+ active task\(s\)\.", call[0][1])
        for call in dummy_bot.reply.call_args_list
    )
    # Status
    await reminder.remind_command(dummy_bot, "a@b", "TestNick", ["status"],
                                  dummy_msg, False)
    dummy_bot.reply.assert_any_call(
        dummy_msg, "ℹ️ Reminder plugin global: off. "
        "Active scheduled reminders: 0.")


@pytest.mark.asyncio
async def test_reminders_list_and_delete(dummy_bot, dummy_msg):
    # List reminders: None
    dummy_bot.db.fetch_all = AsyncMock(return_value=[])
    await reminder.list_reminders(dummy_bot, "a@b", "TestNick", [],
                                  dummy_msg, False)
    dummy_bot.reply.assert_any_call(dummy_msg, "✅ No pending reminders.")

    # List reminders: few exist
    now = datetime.datetime.now()
    dummy_bot.db.fetch_all = AsyncMock(return_value=[
        {"id": 1, "message": "hi", "remind_at": now +
            datetime.timedelta(seconds=31)},
        {"id": 2, "message": "hi2", "remind_at": now +
            datetime.timedelta(seconds=71)},
    ])
    await reminder.list_reminders(dummy_bot, "a@b", "TestNick", [],
                                  dummy_msg, False)
    # check reply called
    assert dummy_bot.reply.call_count > 0

    # Reminder delete, wrong/missing id
    await reminder.delete_reminder(dummy_bot, "a@b", "TestNick", [],
                                   dummy_msg, False)
    dummy_bot.reply.assert_any_call(dummy_msg,
                                    "ℹ️ Usage: ,remind delete <id>")
    await reminder.delete_reminder(dummy_bot, "a@b", "TestNick", ["x"],
                                   dummy_msg, False)
    dummy_bot.reply.assert_any_call(
        dummy_msg, "❌ Reminder ID must be a number.")

    # Reminder not found
    dummy_bot.db.fetch_all = AsyncMock(return_value=[])
    await reminder.delete_reminder(dummy_bot, "a@b", "TestNick",
                                   ["13"], dummy_msg, False)
    dummy_bot.reply.assert_any_call(dummy_msg, "❌ Reminder not found.")

    # Reminder found, but not owned
    dummy_bot.db.fetch_all = AsyncMock(
        return_value=[{"id": 4, "user_jid": "other@user"}])
    await reminder.delete_reminder(dummy_bot, "a@b", "TestNick",
                                   ["4"], dummy_msg, False)
    dummy_bot.reply.assert_any_call(
        dummy_msg, "❌ You can only delete your own reminders.")

    # Reminder delete OK
    dummy_bot.db.fetch_all = AsyncMock(
        return_value=[{"id": 5, "user_jid": "a@b"}])
    await reminder.delete_reminder(dummy_bot, "a@b", "TestNick",
                                   ["5"], dummy_msg, False)
    dummy_bot.reply.assert_any_call(dummy_msg, "✅ Reminder 5 deleted.")


def test_reminder_split_commands_preserve_command_metadata():
    expected = {
        reminder.remind_command: ("remind", ["rem", "reminder"]),
        reminder.list_reminders: ("reminders", ["rems", "remind list"]),
        reminder.delete_reminder: (
            "remind delete",
            ["remind rm", "remind cancel"],
        ),
    }

    for handler, (command_name, aliases) in expected.items():
        assert handler._command == command_name
        assert handler._aliases == aliases
        assert handler._required_role is reminder.Role.USER
