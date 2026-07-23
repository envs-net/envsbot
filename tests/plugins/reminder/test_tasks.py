from .helpers import (
    AsyncMock,
    asyncio,
    patch,
    pytest,
    reminder,
)
from plugins.reminder import runtime as reminder_runtime


@pytest.mark.asyncio
async def test_schedule_and_cancel_task(dummy_bot, dummy_msg):
    # Setup
    reminder_runtime.REMINDER_ENABLED = True
    called = []

    async def wait_for_delivery(reminder_id: int) -> bool:
        """Wait for a scheduled reminder task without relying on fixed sleeps."""
        deadline = asyncio.get_running_loop().time() + 1.0

        while asyncio.get_running_loop().time() < deadline:
            if called and reminder_id not in reminder.ACTIVE_REMINDERS:
                return True
            await asyncio.sleep(0.01)

        return bool(called and reminder_id not in reminder.ACTIVE_REMINDERS)

    async def fake_send(bot, mto, mbody, mtype):
        called.append((mto, mbody, mtype))
        return True
    # Patch sender for full coverage
    with patch("plugins.reminder.tasks._send_reminder_message", new=fake_send):
        # Schedule an immediate reminder and wait until the task is done.
        _ = reminder._schedule_task(
            dummy_bot, 42, "a@b", "u", "msg", 0.0, dummy_msg)
        assert await wait_for_delivery(42)

    # Cancel/restore path (reminder in future)
    _ = reminder._schedule_task(
        dummy_bot, 99, "a@b", "u", "msg", 2.0, dummy_msg)
    await asyncio.sleep(0.05)
    assert 99 in reminder.ACTIVE_REMINDERS
    await reminder._cancel_all_active_tasks()
    assert 99 not in reminder.ACTIVE_REMINDERS


@pytest.mark.asyncio
async def test_reminder_lifecycle(dummy_bot):
    # Plugin startup loads DB and schedules
    with patch("plugins.reminder.lifecycle._restore_pending_reminders",
               new=AsyncMock(return_value=1)):
        await reminder.on_ready(dummy_bot)
    # Plugin unload cancels all active
    with patch("plugins.reminder.lifecycle._cancel_all_active_tasks",
               new=AsyncMock(return_value=2)):
        await reminder.on_unload(dummy_bot)


@pytest.mark.asyncio
async def test_cancel_active_tasks_for_room_only_cancels_matching_pending(dummy_bot):
    class CancelledTask:
        def __init__(self, done=False):
            self.cancelled = False
            self._done = done

        def done(self):
            return self._done

        def cancel(self):
            self.cancelled = True

        def __await__(self):
            async def _wait():
                raise asyncio.CancelledError
            return _wait().__await__()

    matching = CancelledTask()
    done_task = CancelledTask(done=True)
    other_room = CancelledTask()
    reminder.ACTIVE_REMINDERS.clear()
    reminder.ACTIVE_REMINDERS.update({1: matching, 2: done_task, 3: other_room})
    dummy_bot.db.fetch_all = AsyncMock(return_value=[
        {"id": 1, "room_jid": "room@conf"},
        {"id": 2, "room_jid": "room@conf"},
        {"id": 3, "room_jid": "other@conf"},
    ])

    cancelled = await reminder._cancel_active_tasks_for_room(dummy_bot, "room@conf")
    assert cancelled == 1
    assert matching.cancelled is True
    assert done_task.cancelled is False
    assert other_room.cancelled is False
    assert 1 not in reminder.ACTIVE_REMINDERS
    assert 2 not in reminder.ACTIVE_REMINDERS
    assert 3 in reminder.ACTIVE_REMINDERS
    reminder.ACTIVE_REMINDERS.clear()


@pytest.mark.asyncio
async def test_failed_reminder_send_keeps_database_row_pending(dummy_bot, monkeypatch):
    reminder_runtime.REMINDER_ENABLED = True
    delete = AsyncMock()
    monkeypatch.setattr("plugins.reminder.tasks.asyncio.sleep", AsyncMock())
    monkeypatch.setattr(
        "plugins.reminder.tasks._send_reminder_message",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr("plugins.reminder.tasks._delete_reminder", delete)

    await reminder.schedule_reminder_task(
        dummy_bot,
        77,
        "alice@example.org",
        "Alice",
        "important",
        0,
        None,
    )

    delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_room_tasks_ignores_pending_rows_without_runtime_task(dummy_bot):
    reminder.ACTIVE_REMINDERS.clear()
    dummy_bot.db.fetch_all = AsyncMock(return_value=[
        {"id": 404, "room_jid": "room@conf"},
    ])

    assert await reminder._cancel_active_tasks_for_room(dummy_bot, "room@conf") == 0
    assert reminder.ACTIVE_REMINDERS == {}
