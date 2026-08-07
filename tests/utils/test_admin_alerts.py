from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils.admin_alerts import AdminAlertManager


@pytest.mark.asyncio
async def test_alert_state_transitions_are_deduplicated(monkeypatch):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr("utils.admin_alerts.notify_admin", send)
    manager = AdminAlertManager(SimpleNamespace(config={"admin_alert_cooldown_seconds": 3600}))

    await manager._set("demo", True, "Demo failed", fingerprint="same")
    await manager._set("demo", True, "Demo still failed", fingerprint="same")
    assert send.await_count == 1

    await manager._set("demo", True, "Demo changed", fingerprint="changed")
    assert send.await_count == 2
    assert send.await_args.args[1].startswith("🟡")

    await manager._set("demo", False, "Demo recovered")
    assert send.await_count == 3
    assert send.await_args.args[1].startswith("✅ Resolved:")
    assert manager.active_count() == 0


@pytest.mark.asyncio
async def test_outbox_alert_includes_per_destination_capacity(monkeypatch):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr("utils.admin_alerts.notify_admin", send)
    store = SimpleNamespace(
        counts=AsyncMock(return_value={"pending": 8, "inflight": 0, "dead": 0}),
        queue_usage=AsyncMock(
            return_value={
                "queued": 8,
                "bytes": 100,
                "largest_destination_count": 8,
                "largest_category_count": 8,
            }
        ),
        oldest_pending_age=AsyncMock(return_value=0),
    )
    bot = SimpleNamespace(
        config={
            "outbox_max_pending": 100,
            "outbox_max_bytes": 10000,
            "outbox_max_per_destination": 10,
            "outbox_max_per_category": 100,
            "admin_alert_outbox_oldest_seconds": 1800,
        },
        db=SimpleNamespace(outbox=store),
        outbox=SimpleNamespace(),
    )
    manager = AdminAlertManager(bot)

    await manager._check_outbox()

    assert manager._states["outbox-capacity"].active is True
    assert "80% threshold" in manager._states["outbox-capacity"].summary
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_task_circuit_hook_sends_immediate_alert(monkeypatch):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr("utils.admin_alerts.notify_admin", send)
    manager = AdminAlertManager(SimpleNamespace(config={}))

    await manager.report_task_circuit("rss", "feed-worker", "RuntimeError: boom")

    assert send.await_count == 1
    assert "rss/feed-worker" in send.await_args.args[1]
    assert manager.runtime_state()["active"] == 1
