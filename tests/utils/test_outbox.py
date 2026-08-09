import asyncio
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

    store.recover_inflight.assert_awaited_once_with(older_than_seconds=0)
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


@pytest.mark.asyncio
async def test_outbox_stop_signals_worker_and_waits_for_clean_exit():
    runtime = PersistentOutbox(SimpleNamespace(config={}))

    async def worker():
        await runtime.stop_event.wait()

    task = asyncio.create_task(worker())
    runtime.task = task

    await runtime.stop(timeout=0.5)

    assert runtime.stop_event.is_set()
    assert runtime.wakeup.is_set()
    assert runtime.task is None
    assert task.done()
    assert task.cancelled() is False


@pytest.mark.asyncio
async def test_outbox_stop_uses_default_timeout(monkeypatch):
    runtime = PersistentOutbox(SimpleNamespace(config={}))
    task = asyncio.get_running_loop().create_future()
    task.set_result(None)
    runtime.task = task
    seen = {}

    async def wait_for(awaitable, timeout):
        seen["timeout"] = timeout
        return await awaitable

    monkeypatch.setattr("utils.outbox.asyncio.wait_for", wait_for)

    await runtime.stop()

    assert seen == {"timeout": 10.0}


@pytest.mark.asyncio
async def test_outbox_enqueue_uses_defaults_and_wakes_worker():
    alerts = SimpleNamespace(report_outbox_capacity=AsyncMock())
    store = SimpleNamespace(enqueue=AsyncMock(return_value=42))
    bot = SimpleNamespace(config={}, alerts=alerts)
    runtime = PersistentOutbox(bot)
    runtime.store = store

    result = await runtime.enqueue(
        destination="user@example.org",
        body="hello",
        message_type="chat",
    )

    assert result == 42
    store.enqueue.assert_awaited_once_with(
        destination="user@example.org",
        body="hello",
        message_type="chat",
        category="message",
        dedupe_key=message_dedupe_key("message", "user@example.org", "hello"),
        origin_id=None,
        max_attempts=12,
        available_at=None,
        max_pending=10000,
        max_bytes=50 * 1024 * 1024,
        max_per_destination=1000,
        max_per_category=5000,
    )
    assert runtime.wakeup.is_set()
    alerts.report_outbox_capacity.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbox_enqueue_capacity_failure_is_reported_without_wakeup():
    from database.outbox import OutboxCapacityError

    report = AsyncMock()
    store = SimpleNamespace(
        enqueue=AsyncMock(side_effect=OutboxCapacityError("queue full"))
    )
    runtime = PersistentOutbox(
        SimpleNamespace(
            config={},
            alerts=SimpleNamespace(report_outbox_capacity=report),
        )
    )
    runtime.store = store

    assert await runtime.enqueue(
        destination="user@example.org", body="hello", message_type="chat"
    ) is None
    assert runtime.capacity_rejections == 1
    assert runtime.last_error == "OutboxCapacityError: queue full"
    assert runtime.wakeup.is_set() is False
    report.assert_awaited_once_with("queue full")


@pytest.mark.asyncio
async def test_outbox_enqueue_message_uses_default_type_and_options():
    runtime = PersistentOutbox(SimpleNamespace(config={}))
    runtime.enqueue = AsyncMock(return_value=9)
    message = {"to": "user@example.org", "body": "hello"}

    result = await runtime.enqueue_message(message)

    assert result == 9
    runtime.enqueue.assert_awaited_once_with(
        destination="user@example.org",
        body="hello",
        message_type="chat",
        category="message",
        dedupe_key=None,
        max_attempts=None,
        origin_id=None,
    )


@pytest.mark.asyncio
async def test_outbox_enqueue_message_rejects_unserializable_message():
    runtime = PersistentOutbox(SimpleNamespace(config={}))
    runtime.enqueue = AsyncMock(return_value=9)

    assert await runtime.enqueue_message({"body": "missing destination"}) is None
    runtime.enqueue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "expected_timeout", "expected_batch"),
    [
        ({}, 300, 20),
        ({"outbox_inflight_timeout_seconds": 17, "outbox_batch_size": 7}, 17, 7),
    ],
)
async def test_outbox_run_once_recovers_stale_inflight_before_claiming_due(
    config, expected_timeout, expected_batch
):
    events: list[object] = []

    async def recover_inflight(*, older_than_seconds):
        events.append(("recover", older_than_seconds))
        return 2

    async def claim_due(*, limit):
        events.append(("claim", limit))
        return []

    runtime = PersistentOutbox(SimpleNamespace(config=config))
    runtime.store = SimpleNamespace(
        recover_inflight=recover_inflight,
        claim_due=claim_due,
    )

    assert await runtime.run_once() == 0
    assert events == [
        ("recover", expected_timeout),
        ("claim", expected_batch),
    ]
