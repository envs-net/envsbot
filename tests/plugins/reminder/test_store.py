from .helpers import (
    AsyncMock,
    MagicMock,
    _ReminderDoneTask,
    _ReminderPendingTask,
    datetime,
    patch,
    pytest,
    reminder,
)
from plugins.reminder import lifecycle as reminder_lifecycle
from plugins.reminder import runtime as reminder_runtime
from plugins.reminder import store as reminder_store


@pytest.mark.asyncio
async def test_reminder_db_helpers(dummy_bot):
    # Create (also tests init)
    rid = await reminder._create_reminder(dummy_bot, "a@b", "hi",
                                          datetime.datetime.now(
                                            datetime.timezone.utc),
                                          (datetime.datetime.now(
                                           datetime.timezone.utc)
                                           + datetime.timedelta(seconds=30)))
    assert rid == 1
    # Get reminder returns None by default
    r = await reminder._get_reminder(dummy_bot, 123)
    assert r is None
    # Pending for user
    dummy_bot.db.fetch_all = AsyncMock(return_value=[
        {"id": 1, "user_jid": "a@b", "room_jid": None, "message": "test",
            "remind_at": datetime.datetime.now(datetime.timezone.utc)}
    ])
    rows = await reminder._get_pending_reminders(dummy_bot, "a@b")
    assert isinstance(rows, list)
    # All pending reminders
    allrows = await reminder._get_all_pending_reminders(dummy_bot)
    assert isinstance(allrows, list)
    # Delete reminder
    await reminder._delete_reminder(dummy_bot, 1)
    dummy_bot.db.execute.assert_called()


@pytest.mark.asyncio
async def test_restore_pending_reminders(dummy_bot):
    # Overdue, groupchat/room, and skipping
    now = datetime.datetime.now(datetime.timezone.utc)
    dummy_bot.db.fetch_all = AsyncMock(return_value=[
        {"id": 2, "user_jid": "a@b", "room_jid": None, "message": "overdue",
            "remind_at": (now-datetime.timedelta(seconds=10)).isoformat()},
        {"id": 3, "user_jid": "a@b", "room_jid": "rome@conf",
         "message": "future",
            "remind_at": (now+datetime.timedelta(seconds=3600)).isoformat()},
        {"id": 4, "user_jid": "b@c", "room_jid": "rome@conf",
         "message": "skip",
            "remind_at": (now+datetime.timedelta(hours=1)).isoformat()}
    ])
    # _get_room_reminder_state returns True for id==3, False for id==4
    with patch("plugins.reminder.tasks._get_room_reminder_state",
               side_effect=lambda bot, rjid: rjid != "rome@conf"):
        # Should skip id=3,4 due to room state
        restored = await reminder._restore_pending_reminders(dummy_bot)
        # Test races, if reminder2 (overdue, no room) is allowed
        assert restored == 1 or restored == 2


@pytest.mark.asyncio
async def test_room_reminder_state_and_send_message(monkeypatch):
    bot = MagicMock()
    async def feature_state(_bot, room_jid, plugin):
        assert plugin == "reminder"
        return MagicMock(enabled=room_jid == "room@conf")

    monkeypatch.setattr(reminder_store, "get_room_feature", feature_state)
    assert await reminder._get_room_reminder_state(bot, "room@conf") is True
    assert await reminder._get_room_reminder_state(bot, "other@conf") is False

    monkeypatch.setattr(
        reminder_store,
        "get_room_feature",
        AsyncMock(side_effect=RuntimeError("db")),
    )
    assert await reminder._get_room_reminder_state(bot, "room@conf") is False

    sent = []

    class Message:
        def send(self):
            sent.append("fallback")

    bot.make_message.return_value = Message()
    bot._safe_send_message = AsyncMock(
        side_effect=lambda msg: sent.append("safe") or True
    )
    assert await reminder._send_reminder_message(
        bot, "user@example.org", "body", "chat"
    ) is True
    assert sent == ["safe"]

    bot._safe_send_message = AsyncMock(return_value=False)
    assert await reminder._send_reminder_message(
        bot, "user@example.org", "body", "chat"
    ) is False

    delattr(bot, "_safe_send_message")
    assert await reminder._send_reminder_message(
        bot, "room@conf", "body", "groupchat"
    ) is True
    assert sent[-1] == "fallback"

    awaited = []

    class AsyncMessage:
        async def send(self):
            awaited.append("async-fallback")

    bot.make_message.return_value = AsyncMessage()
    assert await reminder._send_reminder_message(
        bot, "room@conf", "body", "groupchat"
    ) is True
    assert awaited == ["async-fallback"]


@pytest.mark.asyncio
async def test_reminder_store_getter_uses_plugin_store():
    marker = object()
    bot = MagicMock()
    bot.db.users.plugin.return_value = marker
    assert await reminder.get_reminder_store(bot) is marker
    bot.db.users.plugin.assert_called_once_with("reminder")


@pytest.mark.asyncio
async def test_cleanup_room_state_deletes_room_reminders(monkeypatch, dummy_bot):
    pending = [
        {"id": 1, "room_jid": "Room@Conf"},
        {"id": 2, "room_jid": "room@conf/resource"},
        {"id": 3, "room_jid": "other@conf"},
        {"id": 4, "room_jid": None},
    ]
    monkeypatch.setattr(reminder_lifecycle, "_init_reminder_db", AsyncMock())
    monkeypatch.setattr(
        reminder_lifecycle,
        "_get_all_pending_reminders",
        AsyncMock(return_value=pending),
    )
    monkeypatch.setattr(reminder_lifecycle, "_cancel_active_tasks_for_room", AsyncMock(return_value=2))
    monkeypatch.setattr(reminder_lifecycle, "_delete_reminder", AsyncMock())

    summary = await reminder.cleanup_room_state(dummy_bot, "room@conf/nick")

    assert summary == {"reminders": 2, "tasks": 2}
    reminder_lifecycle._delete_reminder.assert_any_await(dummy_bot, 1)
    reminder_lifecycle._delete_reminder.assert_any_await(dummy_bot, 2)
    assert reminder_lifecycle._delete_reminder.await_count == 2


@pytest.mark.asyncio
async def test_reminder_runtime_state_global_and_room(monkeypatch):
    monkeypatch.setattr(reminder_lifecycle, "_init_reminder_db", AsyncMock())
    monkeypatch.setattr(
        reminder_lifecycle,
        "_get_all_pending_reminders",
        AsyncMock(return_value=[
            {"id": 1, "room_jid": "Room@Conf"},
            {"id": 2, "room_jid": "room@conf/nick"},
            {"id": 3, "room_jid": "other@conf"},
        ]),
    )
    monkeypatch.setattr(reminder_runtime, "REMINDER_ENABLED", True)
    reminder.ACTIVE_REMINDERS.clear()
    reminder.ACTIVE_REMINDERS[1] = _ReminderPendingTask()
    reminder.ACTIVE_REMINDERS[2] = _ReminderDoneTask()
    reminder.ACTIVE_REMINDERS[3] = _ReminderPendingTask()

    assert await reminder.get_runtime_state(MagicMock(), "room@conf/SomeNick") == {
        "pending_reminders": 2,
        "active_tasks": 1,
    }
    assert await reminder.get_runtime_state(MagicMock()) == {
        "pending_reminders": 3,
        "active_tasks": 2,
        "enabled": 1,
    }
    reminder.ACTIVE_REMINDERS.clear()
