import pytest
import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytz
import re
import plugins.reminder as reminder


MY_TZ = pytz.timezone("Europe/Berlin")  # UTC+2 DST


@pytest.fixture(autouse=True)
def _reset_reminder_module_state():
    """Reset reminder module globals so tests remain isolated."""
    old_enabled = getattr(reminder, "REMINDER_ENABLED", None)
    old_active = getattr(reminder, "ACTIVE_REMINDERS", None)

    reminder.REMINDER_ENABLED = True
    reminder.ACTIVE_REMINDERS = {}
    try:
        yield
    finally:
        if old_enabled is None:
            delattr(reminder, "REMINDER_ENABLED")
        else:
            reminder.REMINDER_ENABLED = old_enabled

        if old_active is None:
            delattr(reminder, "ACTIVE_REMINDERS")
        else:
            reminder.ACTIVE_REMINDERS = old_active


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
