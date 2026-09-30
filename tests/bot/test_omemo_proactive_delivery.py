"""Proactive 1:1 delivery must honor active OMEMO without task context."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import messages as messages_module
from bot.messages import MessageMixin


class FakeMessage:
    def __init__(self, mtype: str = "chat") -> None:
        self.fields = {"type": mtype, "to": "alice@example.test", "body": "private notice",
                       "origin_id": {"id": ""}, "id": ""}
        self.plain_sends = 0

    def __getitem__(self, key: str):
        return self.fields[key]

    def __setitem__(self, key: str, value):
        self.fields[key] = value

    def send(self):
        self.plain_sends += 1
        return None


class Bot(MessageMixin):
    omemo_enabled = True
    omemo_plaintext_fallback = False

    def __init__(self):
        self.crypto = AsyncMock(return_value=None)
        self.outbox = SimpleNamespace(enqueue_message=AsyncMock(return_value=123))

    async def _send_omemo_message_object(self, message):
        return await self.crypto(message)


@pytest.fixture(autouse=True)
def ready(monkeypatch):
    monkeypatch.setattr(messages_module, "session_is_ready", lambda _bot: True)


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["rss", "admin_report", "version-update", "restart"])
async def test_scheduled_direct_chat_defaults_to_omemo(category):
    bot = Bot()
    message = FakeMessage()
    assert await bot._safe_send_message(message, persist=True, category=category) is True
    bot.crypto.assert_awaited_once_with(message)
    bot.outbox.enqueue_message.assert_not_awaited()
    assert message.plain_sends == 0


@pytest.mark.asyncio
async def test_replayed_prior_plaintext_outbox_row_is_encrypted():
    bot = Bot()
    message = FakeMessage()
    assert await bot._safe_send_message(message, persist=False) is True
    bot.crypto.assert_awaited_once_with(message)
    assert message.plain_sends == 0


@pytest.mark.asyncio
async def test_failed_proactive_dm_is_not_plaintext_or_queued():
    bot = Bot()
    bot.crypto.side_effect = RuntimeError("no trusted device")
    message = FakeMessage()
    assert await bot._safe_send_message(message, persist=True, category="rss") is False
    bot.outbox.enqueue_message.assert_not_awaited()
    assert message.plain_sends == 0


@pytest.mark.asyncio
async def test_disconnected_dm_is_not_queued_as_plaintext(monkeypatch):
    monkeypatch.setattr(messages_module, "session_is_ready", lambda _bot: False)
    bot = Bot()
    message = FakeMessage()
    assert await bot._safe_send_message(message, persist=True, category="admin_report") is False
    bot.outbox.enqueue_message.assert_not_awaited()
    assert message.plain_sends == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mtype, expect_crypto", [("groupchat", False), ("chat", True), ("normal", True)])
async def test_proactive_transport_uses_message_type(mtype, expect_crypto):
    bot = Bot()
    message = FakeMessage(mtype)
    assert await bot._safe_send_message(message) is True
    assert bot.crypto.await_count == int(expect_crypto)
    assert message.plain_sends == int(not expect_crypto)


@pytest.mark.asyncio
async def test_omemo_disabled_keeps_original_plaintext_behavior():
    bot = Bot()
    bot.omemo_enabled = False
    message = FakeMessage()
    assert await bot._safe_send_message(message) is True
    bot.crypto.assert_not_awaited()
    assert message.plain_sends == 1


@pytest.mark.asyncio
async def test_explicit_plaintext_choice_preserved():
    bot = Bot()
    message = FakeMessage()
    assert await bot._safe_send_message(message, encrypted=False) is True
    bot.crypto.assert_not_awaited()
    assert message.plain_sends == 1


@pytest.mark.asyncio
async def test_unknown_private_message_type_does_not_silently_downgrade():
    bot = Bot()
    message = FakeMessage("mystery")
    assert await bot._safe_send_message(message) is False
    bot.crypto.assert_not_awaited()
    assert message.plain_sends == 0


@pytest.mark.asyncio
async def test_identity_reset_does_not_send_proactive_private_message_in_cleartext():
    bot = Bot()
    bot.omemo_enabled = False
    bot.omemo_reset_pending_restart = True
    message = FakeMessage()
    assert await bot._safe_send_message(message, persist=True, category="rss") is False
    bot.crypto.assert_not_awaited()
    bot.outbox.enqueue_message.assert_not_awaited()
    assert message.plain_sends == 0
