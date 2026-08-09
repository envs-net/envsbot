from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils import admin_notify


@pytest.mark.asyncio
async def test_notify_admin_sends_groupchat_durably(monkeypatch):
    durable = AsyncMock(return_value=True)
    monkeypatch.setattr(admin_notify, "durable_send", durable)
    message = object()
    bot = SimpleNamespace(
        config={"admin_report_jid": "admins@conference.example.org"},
        make_message=MagicMock(return_value=message),
    )

    assert await admin_notify.notify_admin(
        bot, "health warning", category="health", dedupe_key="health:1"
    ) is True

    bot.make_message.assert_called_once_with(
        mto="admins@conference.example.org",
        mbody="health warning",
        mtype="groupchat",
    )
    durable.assert_awaited_once_with(
        bot,
        message,
        category="health",
        dedupe_key="health:1",
    )


@pytest.mark.asyncio
async def test_notify_admin_uses_chat_and_skips_missing_target(monkeypatch):
    durable = AsyncMock(return_value=True)
    monkeypatch.setattr(admin_notify, "durable_send", durable)
    message = object()
    bot = SimpleNamespace(
        config={"owner": "owner@example.org"},
        make_message=MagicMock(return_value=message),
    )

    assert await admin_notify.notify_admin(bot, "hello") is True
    bot.make_message.assert_called_once_with(
        mto="owner@example.org",
        mbody="hello",
        mtype="chat",
    )
    durable.assert_awaited_once_with(
        bot,
        message,
        category="admin",
        dedupe_key=None,
    )

    missing = SimpleNamespace(config={}, make_message=MagicMock())
    assert await admin_notify.notify_admin(missing, "ignored") is False
    missing.make_message.assert_not_called()
    assert durable.await_count == 1
