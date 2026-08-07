import pytest
import asyncio
import datetime
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
import pytz
import re
import plugins.reminder as reminder
import plugins.reminder.runtime as reminder_runtime
from utils.command import Role


MY_TZ = pytz.timezone("Europe/Berlin")  # UTC+2 DST


@pytest.fixture(autouse=True)
def _reset_reminder_module_state():
    """Reset reminder module globals so tests remain isolated."""
    old_enabled = reminder_runtime.REMINDER_ENABLED
    old_active = dict(reminder_runtime.ACTIVE_REMINDERS)

    reminder_runtime.REMINDER_ENABLED = True
    reminder_runtime.ACTIVE_REMINDERS.clear()
    try:
        yield
    finally:
        reminder_runtime.REMINDER_ENABLED = old_enabled
        reminder_runtime.ACTIVE_REMINDERS.clear()
        reminder_runtime.ACTIVE_REMINDERS.update(old_active)


@pytest.fixture
def dummy_bot():
    # Mock bot, plugin, db, and config access
    bot = MagicMock()
    bot.plugin = {}
    bot.db = MagicMock()
    bot.db.execute = AsyncMock(return_value=MagicMock(lastrowid=1))
    bot.db.write = AsyncMock(return_value=MagicMock(lastrowid=1))
    bot.db.fetch_one = AsyncMock(return_value=None)
    bot.db.fetch_all = AsyncMock(return_value=[])

    @asynccontextmanager
    async def transaction(*, label="test"):
        del label
        yield bot.db

    bot.db.transaction = transaction
    # plugin("reminder") returns bot.db
    bot.db.users.plugin = MagicMock(return_value=bot.db)
    bot.db.users.get = AsyncMock(return_value={})
    bot.db.users.create = AsyncMock(return_value=True)
    # Needed for some command helpers
    bot.get_user_role = AsyncMock(return_value=Role.OWNER)
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


class _ReminderPendingTask:
    def done(self):
        return False


class _ReminderDoneTask:
    def done(self):
        return True


__all__ = [
    "pytest",
    "asyncio",
    "datetime",
    "AsyncMock",
    "MagicMock",
    "patch",
    "pytz",
    "re",
    "reminder",
    "MY_TZ",
    "_reset_reminder_module_state",
    "dummy_bot",
    "dummy_msg",
    "_ReminderPendingTask",
    "_ReminderDoneTask",
]
