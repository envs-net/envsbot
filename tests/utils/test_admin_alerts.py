from __future__ import annotations

import asyncio
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
    assert send.await_args.args[1].startswith("🔴 Still active:")

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


@pytest.mark.asyncio
async def test_event_loop_recovery_reports_current_healthy_lag(monkeypatch):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr("utils.admin_alerts.notify_admin", send)
    state = SimpleNamespace(last_lag_seconds=2.721)
    bot = SimpleNamespace(
        config={"watchdog_lag_warning_seconds": 2.0},
        watchdog=SimpleNamespace(state=state),
    )
    manager = AdminAlertManager(bot)

    await manager.report_event_loop_lag(2.594, 2.0)
    await manager.report_event_loop_lag(2.721, 2.0)
    state.last_lag_seconds = 0.125
    await manager._check_watchdog()

    assert send.await_count == 2
    recovery = send.await_args.args[1]
    assert recovery == (
        "✅ Resolved: Event-loop lag recovered to 0.125s "
        "(warning 2.000s)"
    )
    assert "2.721s" not in recovery


@pytest.mark.asyncio
async def test_alert_worker_waits_for_runtime_ready():
    runtime_ready = asyncio.Event()
    bot = SimpleNamespace(config={}, runtime_ready=runtime_ready)
    manager = AdminAlertManager(bot)
    manager.run_once = AsyncMock()

    task = asyncio.create_task(manager._run())
    await asyncio.sleep(0)

    assert manager.run_once.await_count == 0
    assert task.done() is False

    runtime_ready.set()
    await asyncio.sleep(0)

    assert manager.run_once.await_count == 1
    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)


@pytest.mark.asyncio
async def test_message_cache_degraded_opens_and_resolves_alert(monkeypatch):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr("utils.admin_alerts.notify_admin", send)
    manager = AdminAlertManager(SimpleNamespace(config={}))

    from utils.health import HealthCheck, HealthSnapshot

    unhealthy = HealthSnapshot(
        checked_at="now",
        checks={
            "message_cache": HealthCheck(
                "message_cache",
                "warning",
                "degraded",
                {
                    "pending_writes": 2,
                    "retry_backlog": 1,
                    "dropped_persistence_entries": 3,
                    "degraded": True,
                    "last_persistence_error": "disk busy",
                },
                "disk busy",
            )
        },
    )
    healthy = HealthSnapshot(
        checked_at="later",
        checks={
            "message_cache": HealthCheck(
                "message_cache",
                "ok",
                "healthy",
                {"degraded": False},
            )
        },
    )

    await manager._check_message_cache(unhealthy)
    assert manager._states["message-cache"].active is True
    assert "disk busy" in manager._states["message-cache"].summary

    await manager._check_message_cache(healthy)
    assert manager._states["message-cache"].active is False
    assert send.await_count == 2


@pytest.mark.asyncio
async def test_run_once_isolates_individual_alert_check_failures(monkeypatch):
    from utils.health import HealthCheck, HealthSnapshot

    snapshot = HealthSnapshot(
        checked_at="now",
        checks={
            key: HealthCheck(key, "ok", "ok")
            for key in (
                "outbox",
                "tasks",
                "rooms",
                "backup",
                "message_cache",
                "database",
                "idlerpg_export",
                "watchdog",
            )
        },
    )
    monkeypatch.setattr(
        "utils.admin_alerts.collect_health_snapshot",
        AsyncMock(return_value=snapshot),
    )
    manager = AdminAlertManager(SimpleNamespace(config={}))
    manager._check_outbox = AsyncMock(side_effect=RuntimeError("outbox boom"))
    manager._check_tasks = AsyncMock()
    manager._check_rooms = AsyncMock()
    manager._check_backup = AsyncMock()
    manager._check_message_cache = AsyncMock()
    manager._check_database = AsyncMock()
    manager._check_idlerpg_export = AsyncMock()
    manager._check_watchdog = AsyncMock()

    await manager.run_once()

    manager._check_tasks.assert_awaited_once_with(snapshot)
    manager._check_watchdog.assert_awaited_once_with(snapshot)
    state = manager.runtime_state()
    assert state["checks"] == 1
    assert state["check_errors"]["outbox"] == "RuntimeError: outbox boom"
    assert "outbox boom" in state["last_error"]
