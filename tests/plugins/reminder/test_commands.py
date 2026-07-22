from types import SimpleNamespace
from unittest.mock import Mock

from utils import message_cache

from .helpers import (
    AsyncMock,
    datetime,
    pytest,
    re,
    reminder,
)
from utils.command import Role
from plugins.reminder import runtime as reminder_runtime
from plugins.reminder import commands as reminder_commands
from plugins.reminder import parsing as reminder_parsing
from plugins.reminder import events as reminder_events


@pytest.mark.asyncio
async def test_remind_command_and_status_controls(dummy_bot, dummy_msg):
    # Room-enabled and plugin ON by default
    reminder_runtime.REMINDER_ENABLED = True
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
    text += "Or reply to a message with: ,remind <duration|date time>\n"
    text += "Example: ,remind 30m Take a break\n"
    text += "Reply example: ,remind 1h\n"
    text += "Example: ,remind 2026-05-01 14:30 Take a break\n"
    text += "Example: ,remind 2026-05-01 14:30 CEST Take a break\n"
    text += "Example: ,remind 01.05.2026 14:30 Take a break\n"
    text += "Formats: 10s, 5m, 1h, 2d, 1h30m,"
    text += " YYYY-MM-DD HH:MM, DD.MM.YYYY HH:MM, optional TZ (max 365 days)"
    dummy_bot.reply.assert_any_call(
        dummy_msg, text)

    # Plugin disbled
    reminder_runtime.REMINDER_ENABLED = False
    await reminder.remind_command(dummy_bot, "a@b", "TestNick", ["10s", "msg"],
                                  dummy_msg, False)
    dummy_bot.reply.assert_any_call(
        dummy_msg, "⏸️ Reminder plugin is globally off."
        " Use ,remind on in a DM to enable it.")

    # Enable via command in DM
    dummy_bot.reply.reset_mock()
    reminder_runtime.REMINDER_ENABLED = False
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
        reminder.remind_status_command: (
            "remind status",
            ["rem status", "reminder status"],
        ),
        reminder.remind_on_command: (
            "remind on",
            ["rem on", "reminder on"],
        ),
        reminder.remind_off_command: (
            "remind off",
            ["rem off", "reminder off"],
        ),
        reminder.list_reminders: ("reminders", ["rems", "remind list"]),
        reminder.delete_reminder: (
            "remind delete",
            ["remind rm", "remind cancel"],
        ),
    }

    for handler, (command_name, aliases) in expected.items():
        assert handler._command == command_name
        assert handler._aliases == aliases
        assert handler._required_role is Role.USER


@pytest.mark.asyncio
async def test_remind_control_commands_delegate_to_base_command(dummy_bot, dummy_msg, monkeypatch):
    calls = []

    async def fake_remind_command(bot, sender_jid, nick, args, msg, is_room):
        calls.append((sender_jid, nick, list(args), msg, is_room))

    monkeypatch.setattr(reminder_commands, "remind_command", fake_remind_command)

    await reminder.remind_status_command(
        dummy_bot, "a@b", "TestNick", [], dummy_msg, False
    )
    await reminder.remind_on_command(
        dummy_bot, "a@b", "TestNick", [], dummy_msg, False
    )
    await reminder.remind_off_command(
        dummy_bot, "a@b", "TestNick", [], dummy_msg, False
    )

    assert [call[2] for call in calls] == [["status"], ["on"], ["off"]]


class _ReplyFrom:
    def __init__(self, bare: str, resource: str | None = None):
        self.bare = bare
        self.resource = resource

    def __str__(self):
        if self.resource:
            return f"{self.bare}/{self.resource}"
        return self.bare


@pytest.mark.asyncio
async def test_remind_command_uses_replied_message_from_shared_cache(
    dummy_bot,
    monkeypatch,
):
    room = "room@conference.example.org"
    msg = {
        "body": ",remind 1h",
        "type": "groupchat",
        "from": _ReplyFrom(room, "alice"),
        "mucnick": "alice",
        "id": "reminder-command",
        "reply": {"id": "source-message"},
    }
    dummy_bot.message_cache = message_cache.MessageCache(max_messages=20)
    await dummy_bot.message_cache.add_entry({
        "conversation": room,
        "stanza_id": "source-message",
        "nick": "bob",
        "body": "xxx",
    })
    monkeypatch.setattr(
            reminder_commands,
        "_is_reminder_enabled_for_context",
        AsyncMock(return_value=True),
    )
    create = AsyncMock(return_value=42)
    schedule = Mock()
    monkeypatch.setattr(reminder_commands, "_create_reminder", create)
    monkeypatch.setattr(reminder_commands, "_schedule_task", schedule)

    await reminder.remind_command(
        dummy_bot,
        "alice@example.org",
        "alice",
        ["1h"],
        msg,
        True,
    )

    assert create.await_args.kwargs["message"] == "xxx"
    assert schedule.call_args.args[4] == "xxx"
    assert schedule.call_args.args[5] == 3600
    dummy_bot.reply.assert_called_once_with(
        msg,
        "✅ Reminder set! I'll remind you in 1h",
    )


@pytest.mark.asyncio
async def test_remind_command_uses_reply_quote_when_cache_entry_is_missing(
    dummy_bot,
    monkeypatch,
):
    room = "room@conference.example.org"
    msg = {
        "body": "> quoted reminder text\n,remind 1h",
        "type": "groupchat",
        "from": _ReplyFrom(room, "alice"),
        "mucnick": "alice",
        "id": "reminder-command",
        "reply": {"id": "missing-source"},
    }
    dummy_bot.message_cache = message_cache.MessageCache(max_messages=20)
    monkeypatch.setattr(
            reminder_commands,
        "_is_reminder_enabled_for_context",
        AsyncMock(return_value=True),
    )
    create = AsyncMock(return_value=43)
    monkeypatch.setattr(reminder_commands, "_create_reminder", create)
    monkeypatch.setattr(reminder_commands, "_schedule_task", Mock())

    await reminder.remind_command(
        dummy_bot,
        "alice@example.org",
        "alice",
        ["1h"],
        msg,
        True,
    )

    assert create.await_args.kwargs["message"] == "quoted reminder text"


@pytest.mark.asyncio
async def test_remind_command_reports_evicted_reply_target(
    dummy_bot,
    monkeypatch,
):
    room = "room@conference.example.org"
    msg = {
        "body": ",remind 1h",
        "type": "groupchat",
        "from": _ReplyFrom(room, "alice"),
        "mucnick": "alice",
        "id": "reminder-command",
        "reply": {"id": "evicted-source"},
    }
    dummy_bot.message_cache = message_cache.MessageCache(max_messages=20)
    monkeypatch.setattr(
        reminder_commands,
        "_is_reminder_enabled_for_context",
        AsyncMock(return_value=True),
    )

    await reminder.remind_command(
        dummy_bot,
        "alice@example.org",
        "alice",
        ["1h"],
        msg,
        True,
    )

    output = dummy_bot.reply.call_args.args[1]
    assert "Could not resolve the replied-to message" in output
    assert "shared message cache" in output


@pytest.mark.asyncio
async def test_reminder_reply_fallback_handler_redispatches_normal_command():
    room = "room@conference.example.org"
    msg = {
        "body": "> xxx\n,remind 1h",
        "type": "groupchat",
        "from": _ReplyFrom(room, "alice"),
        "mucnick": "alice",
        "id": "quoted-reminder-command",
    }
    bot = SimpleNamespace(
        nick="EnvBot",
        presence=SimpleNamespace(joined_rooms={room: "EnvBot"}),
        handle_command=AsyncMock(),
    )

    await reminder._on_groupchat_message(bot, msg)

    bot.handle_command.assert_awaited_once_with(
        ",remind 1h",
        msg["from"],
        "alice",
        msg,
        True,
    )


@pytest.mark.asyncio
async def test_reminder_on_load_registers_reply_fallback_handlers():
    register_event = Mock()
    bot = SimpleNamespace(
        bot_plugins=SimpleNamespace(register_event=register_event),
    )

    await reminder.on_load(bot)

    assert register_event.call_count == 2
    assert register_event.call_args_list[0].args[:2] == (
        "reminder",
        "groupchat_message",
    )
    assert register_event.call_args_list[1].args[:2] == (
        "reminder",
        "message",
    )



@pytest.mark.asyncio
async def test_remind_command_reports_past_absolute_time(dummy_bot, dummy_msg, monkeypatch):
    fixed_now = datetime.datetime(
        2026, 7, 11, 7, 30, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(reminder_commands, "_utcnow", lambda: fixed_now)
    monkeypatch.setattr(reminder_parsing, "_utcnow", lambda: fixed_now)

    await reminder.remind_command(
        dummy_bot,
        "a@b",
        "TestNick",
        ["2026-07-11", "09:30", "+03:00", "Test"],
        dummy_msg,
        False,
    )

    reply = dummy_bot.reply.call_args[0][1]
    assert "Reminder time must be in the future" in reply
    assert "Parsed target: 2026-07-11 09:30 +03:00" in reply
    assert "Current time: 2026-07-11 10:30 +03:00" in reply


@pytest.mark.asyncio
async def test_private_reply_fallback_wrapper_uses_direct_context(monkeypatch):
    redispatch = AsyncMock()
    monkeypatch.setattr(reminder_events, "_redispatch_reply_fallback", redispatch)
    bot = object()
    msg = object()

    assert await reminder_events._on_private_message(bot, msg) is None
    redispatch.assert_awaited_once_with(bot, msg, is_room=False)
