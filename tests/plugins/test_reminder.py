# ----------------------------------------------------------------------
# The following tests FAIL as STANDALONE or when only running this file:
# test_reminder.py::test_remind_command_and_status_controls
# test_reminder.py::test_reminders_list_and_delete
# ----------------------------------------------------------------------
import pytest
import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytz
import re

import plugins.reminder as reminder

# Utility TZ for tests
MY_TZ = pytz.timezone("Europe/Berlin")  # UTC+2 DST


@pytest.fixture
def dummy_bot():
    # Mock bot, plugin, db, and config access
    bot = MagicMock()
    bot.plugin = {}
    bot.db = MagicMock()
    bot.db.execute = AsyncMock(return_value=MagicMock(lastrowid=1))
    bot.db.fetch_all = AsyncMock(return_value=[])
    # plugin("reminder") returns bot.db
    bot.db.users.plugin = MagicMock(return_value=bot.db)
    bot.db.users.get = AsyncMock(return_value={})
    bot.db.users.create = AsyncMock(return_value=True)
    # Needed for some command helpers
    bot.get_user_role = AsyncMock(return_value=reminder.Role.OWNER)
    bot.boundjid = MagicMock()
    bot.boundjid.bare = "bot@xmpp.test"
    bot.make_message = MagicMock(return_value=MagicMock(send=AsyncMock()))
    bot._safe_send_message = AsyncMock()
    bot.reply = MagicMock()
    return bot


@pytest.fixture
def dummy_msg():
    # Minimal message object for testing
    msg = MagicMock()
    msg.__getitem__.side_effect = lambda k: {
        "type": "chat",
        "from": MagicMock(bare="rome@conf", resource="TestUser"),
        "to": MagicMock(bare="bot@xmpp.test")
    }[k]
    msg.get = lambda x, default=None: getattr(msg, x, default)
    msg["from"].bare = "rome@conf"
    msg["from"].resource = "TestUser"
    msg["to"].bare = "bot@xmpp.test"
    return msg

# ---------------
# Duration Parsing
# ---------------


@pytest.mark.parametrize("s,seconds", [
    ("5s", 5), ("2m", 120), ("1h", 3600), ("3d", 259200),
    ("1h30m", 5400), ("2d2h3m4s", 2*86400 + 2*3600 + 3*60 + 4),
    ("", None), ("bad", None), ("0s", None), ("xx3d", None)
])
def test_parse_duration(s, seconds):
    assert reminder.parse_duration(s) == seconds

# ---------------
# Absolute datetime parsing
# ---------------


def test_parse_absolute_datetime():
    # Use a fixed TZ
    dt, count = reminder.parse_absolute_datetime(
        ["2026-05-01", "14:30"], MY_TZ)
    assert dt is not None and count == 2
    assert dt.astimezone(pytz.UTC).hour == 12  # 14:30+0200 == 12:30Z
    dt2, count2 = reminder.parse_absolute_datetime(
        ["01.05.2026", "14:30"], MY_TZ)
    assert dt2 is not None and count2 == 2
    # Invalid
    dt, count = reminder.parse_absolute_datetime(["bad"], MY_TZ)
    assert dt is None


@pytest.mark.asyncio
async def test_parse_reminder_when_duration_and_datetime():
    # Duration, with message
    sec, msg, when = reminder.parse_reminder_when(["1h", "test"], MY_TZ)
    assert sec is not None and msg == "test" and when.startswith("in ")
    # Absolute datetime, in future
    utcnow = datetime.datetime.now(pytz.UTC)
    # Convert to your test's timezone
    local_now = utcnow.astimezone(MY_TZ)
    local_dt = local_now + datetime.timedelta(hours=1)
    future = local_dt.strftime("%Y-%m-%d %H:%M")
    args = future.split() + ["something"]
    sec, msg, when = reminder.parse_reminder_when(args, MY_TZ)
    assert sec is not None and msg == "something"
    # Invalid cases
    assert reminder.parse_reminder_when([], MY_TZ) == (None, None, None)
    assert reminder.parse_reminder_when(["5s"], MY_TZ) == (None, None, None)


def test_format_seconds():
    assert reminder.format_seconds(3661) == "1h 1m 1s"
    assert reminder.format_seconds(61) == "1m 1s"
    assert reminder.format_seconds(-1) == "overdue"


def test_format_overdue():
    assert reminder._format_overdue(-59) == "59s ago"
    assert reminder._format_overdue(-61) == "1m ago"
    assert reminder._format_overdue(-3700) == "1.0h ago"
    assert reminder._format_overdue(-90000) == "1.0d ago"

# ---------------
# DB Setup, Insert/Query/Delete
# ---------------


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

# ---------------
# Create/Trigger Reminder Task, Delivery, Cancel, Restore
# ---------------



@pytest.mark.asyncio
async def test_schedule_and_cancel_task(dummy_bot, dummy_msg):
    # Setup
    reminder.REMINDER_ENABLED = True
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
    # Patch sender for full coverage
    with patch("plugins.reminder._send_reminder_message", new=fake_send):
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
    with patch("plugins.reminder._get_room_reminder_state",
               side_effect=lambda bot, rjid: rjid != "rome@conf"):
        # Should skip id=3,4 due to room state
        restored = await reminder._restore_pending_reminders(dummy_bot)
        # Test races, if reminder2 (overdue, no room) is allowed
        assert restored == 1 or restored == 2

# ---------------
# Command: remind, reminders, remind delete (happy and error paths)
# ---------------


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
    text += "Example: ,remind 01.05.2026 14:30 Take a break\n"
    text += "Formats: 10s, 5m, 1h, 2d, 1h30m,"
    text += " YYYY-MM-DD HH:MM, DD.MM.YYYY HH:MM (max 365 days)"
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


@pytest.mark.asyncio
async def test_reminder_lifecycle(dummy_bot):
    # Plugin startup loads DB and schedules
    with patch("plugins.reminder._restore_pending_reminders",
               new=AsyncMock(return_value=1)):
        await reminder.on_ready(dummy_bot)
    # Plugin unload cancels all active
    with patch("plugins.reminder._cancel_all_active_tasks",
               new=AsyncMock(return_value=2)):
        await reminder.on_unload(dummy_bot)


def test_timezone_lookup_jid_direct_muc_plugin_joined_and_fallback(dummy_bot, monkeypatch):
    msg = MagicMock()
    from_jid = MagicMock(bare="user@example.org", resource="Nick")
    msg.__getitem__.side_effect = lambda key: {"from": from_jid, "type": "chat"}[key]

    assert reminder._timezone_lookup_jid(dummy_bot, "sender@example.org/res", msg, False) == "user@example.org"

    muc = MagicMock()
    muc.get_jid_property.return_value = "real@example.org/resource"
    dummy_bot.plugin = {"xep_0045": muc}
    from_jid.bare = "room@conf"
    from_jid.resource = "Nick"
    assert reminder._timezone_lookup_jid(dummy_bot, "sender@example.org/res", msg, True) == "real@example.org"
    muc.get_jid_property.assert_called_once_with("room@conf", "Nick", "jid")

    muc.get_jid_property.side_effect = RuntimeError("lookup failed")
    reminder.JOINED_ROOMS["room@conf"] = {
        "nicks": {"Nick": {"jid": "joined@example.org/resource"}}
    }
    try:
        assert reminder._timezone_lookup_jid(dummy_bot, "sender@example.org/res", msg, True) == "joined@example.org"
    finally:
        reminder.JOINED_ROOMS.pop("room@conf", None)

    dummy_bot.plugin = {}
    assert reminder._timezone_lookup_jid(dummy_bot, "sender@example.org/res", msg, True) == "sender@example.org"

    monkeypatch.setattr(reminder, "_is_muc_pm", lambda _msg, _is_room: False)
    msg.__getitem__.side_effect = KeyError("from")
    assert reminder._timezone_lookup_jid(dummy_bot, "fallback@example.org/res", msg, False) == "fallback@example.org"


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
async def test_room_reminder_state_and_send_message(monkeypatch):
    class Store:
        def __init__(self, state):
            self.state = state

        async def get_global(self, key, default=None):
            assert key == reminder.REMINDER_KEY
            return self.state

    bot = MagicMock()
    monkeypatch.setattr(reminder, "get_reminder_store", AsyncMock(return_value=Store({"room@conf": True})))
    assert await reminder._get_room_reminder_state(bot, "room@conf") is True
    assert await reminder._get_room_reminder_state(bot, "other@conf") is False

    monkeypatch.setattr(reminder, "get_reminder_store", AsyncMock(return_value=Store(["bad"])))
    assert await reminder._get_room_reminder_state(bot, "room@conf") is False

    monkeypatch.setattr(reminder, "get_reminder_store", AsyncMock(side_effect=RuntimeError("db")))
    assert await reminder._get_room_reminder_state(bot, "room@conf") is False

    sent = []

    class Message:
        def send(self):
            sent.append("fallback")

    bot.make_message.return_value = Message()
    bot._safe_send_message = AsyncMock(side_effect=lambda msg: sent.append("safe"))
    await reminder._send_reminder_message(bot, "user@example.org", "body", "chat")
    assert sent == ["safe"]

    delattr(bot, "_safe_send_message")
    await reminder._send_reminder_message(bot, "room@conf", "body", "groupchat")
    assert sent[-1] == "fallback"

@pytest.mark.asyncio
async def test_reminder_store_getter_uses_plugin_store():
    marker = object()
    bot = MagicMock()
    bot.db.users.plugin.return_value = marker
    assert await reminder.get_reminder_store(bot) is marker
    bot.db.users.plugin.assert_called_once_with("reminder")
