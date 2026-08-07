from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.room_state import JOINED_ROOMS
from utils.outbox import PersistentOutbox, message_dedupe_key


def test_message_dedupe_key_is_stable_and_hides_content():
    key = message_dedupe_key("rss", "room@example.org", "secret body")
    assert key == message_dedupe_key("rss", "room@example.org", "secret body")
    assert "secret body" not in key
    assert key.startswith("rss:")


@pytest.mark.asyncio
async def test_outbox_defers_unjoined_room_without_failure_attempt():
    JOINED_ROOMS.clear()
    bot = SimpleNamespace(config={})
    runtime = PersistentOutbox(bot)
    runtime.store = SimpleNamespace(defer=AsyncMock(), mark_failed=AsyncMock())
    queued = SimpleNamespace(
        id=1,
        destination="room@conference.example.org",
        message_type="groupchat",
        attempts=0,
        origin_id="origin-defer",
    )

    await runtime._send_one(queued)

    runtime.store.defer.assert_awaited_once()
    runtime.store.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbox_sends_and_deletes_claimed_message():
    JOINED_ROOMS["room@conference.example.org"] = {}
    message = MagicMock()
    bot = SimpleNamespace(
        config={},
        make_message=MagicMock(return_value=message),
        _safe_send_message=AsyncMock(return_value=True),
    )
    runtime = PersistentOutbox(bot)
    runtime.store = SimpleNamespace(mark_sent=AsyncMock(), mark_failed=AsyncMock())
    queued = SimpleNamespace(
        id=2,
        destination="room@conference.example.org",
        body="hello",
        message_type="groupchat",
        category="rss",
        attempts=0,
        origin_id="origin-send",
    )

    await runtime._send_one(queued)

    runtime.store.mark_sent.assert_awaited_once_with(2)
    runtime.store.mark_failed.assert_not_awaited()
    assert runtime.delivered == 1

@pytest.mark.asyncio
async def test_outbox_uses_resilient_service_supervision():
    supervisor = SimpleNamespace(create_resilient=MagicMock(return_value=MagicMock()))
    bot = SimpleNamespace(config={}, tasks=supervisor)
    runtime = PersistentOutbox(bot)
    store = SimpleNamespace(recover_inflight=AsyncMock())

    await runtime.start(store)

    supervisor.create_resilient.assert_called_once_with(
        "_runtime",
        runtime._supervised_run,
        name="persistent-outbox",
        service=True,
    )

@pytest.mark.asyncio
async def test_outbox_graceful_stop_is_expected_service_exit():
    from utils.task_supervisor import ExpectedTaskExit

    runtime = PersistentOutbox(SimpleNamespace(config={}))
    runtime.stop_event.set()

    with pytest.raises(ExpectedTaskExit):
        await runtime._supervised_run()

def test_ensure_message_origin_id_reuses_explicit_id():
    from utils.outbox import ensure_message_origin_id

    class Message:
        def __init__(self):
            self.data = {"origin_id": {}}

        def __getitem__(self, key):
            return self.data[key]

        def __setitem__(self, key, value):
            self.data[key] = value

    message = Message()
    assert ensure_message_origin_id(message, "stable-123") == "stable-123"
    assert message.data["id"] == "stable-123"
    assert message.data["origin_id"]["id"] == "stable-123"
