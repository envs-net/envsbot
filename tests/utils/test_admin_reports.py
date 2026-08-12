from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils.admin_reports import build_daily_admin_report
from utils.health import HealthCheck


def _patch_backup_health(monkeypatch, *, name="backup.zip", status="verified", age=3600):
    async def _fake_backup(_bot, *, verify, smoke_test=False):
        assert verify is True
        effective_status = "verified+restore-smoke" if smoke_test and status == "verified" else status
        return HealthCheck(
            "backup",
            "ok" if effective_status.startswith("verified") else "warning",
            "test backup",
            {
                "name": name,
                "status": effective_status,
                "age_seconds": age,
                "path": None if name == "none" else SimpleNamespace(resolve=lambda: name),
                "valid": effective_status.startswith("verified"),
            },
        )

    monkeypatch.setattr("utils.health._backup_check", _fake_backup)


@pytest.mark.asyncio
async def test_daily_admin_report_contains_internal_health_only(monkeypatch):
    _patch_backup_health(monkeypatch, age=3600)
    tasks = SimpleNamespace(
        summary=lambda: (3, 0, 1),
        snapshot=lambda include_done=True: [],
    )
    bot = SimpleNamespace(
        connection_start_time=datetime.now(timezone.utc),
        config={},
        presence=SimpleNamespace(joined_rooms={"room@conf": {}}),
        tasks=tasks,
        outbox=SimpleNamespace(runtime_state=AsyncMock(return_value={
            "pending": 0,
            "dead": 0,
            "oldest_pending_age_seconds": 0,
            "last_error": None,
        })),
        db=SimpleNamespace(
            rooms=SimpleNamespace(list=AsyncMock(return_value=[{"room_jid": "room@conf"}])),
            maintenance_state={"runs": 1, "failures": 0, "last_duration_ms": 3},
            command_usage=SimpleNamespace(
                totals_since=AsyncMock(return_value={"uses": 7, "failures": 0})
            ),
        ),
        bot_plugins=SimpleNamespace(failed_plugins={}),
        watchdog=SimpleNamespace(runtime_state=lambda: {
            "last_lag_seconds": 0.01,
            "max_lag_seconds": 0.02,
            "last_error": None,
        }),
        alerts=SimpleNamespace(runtime_state=lambda: {
            "active": 0,
            "active_keys": [],
        }),
        message_cache=SimpleNamespace(stats=lambda: {
            "messages": 12,
            "pending_writes": 0,
            "retry_backlog": 0,
            "dropped_persistence_entries": 0,
            "last_persistence_error": None,
            "persistent": True,
            "degraded": False,
        }),
    )

    report = await build_daily_admin_report(bot)

    assert "EnvsBot daily health" in report
    assert "rooms: 1/1 autojoin rooms joined" in report
    assert "backup: backup.zip · 1h 0m 0s old · verified" in report
    assert "message cache: 12 messages, 0 pending, 0 retry, 0 dropped · persistent · healthy" in report
    assert "commands (24h): 7 use(s), 0 failed" in report
    assert "overall: ✅ no current operational errors" in report
    assert "http://" not in report and "https://" not in report


@pytest.mark.asyncio
async def test_daily_admin_report_handles_legacy_naive_local_start_time(monkeypatch):
    _patch_backup_health(monkeypatch, age=3600)
    bot = SimpleNamespace(
        connection_start_time=datetime.now() - timedelta(hours=2),
        config={},
        presence=SimpleNamespace(joined_rooms={}),
        tasks=None,
        outbox=None,
        db=SimpleNamespace(rooms=None, maintenance_state={}, command_usage=None),
        bot_plugins=SimpleNamespace(failed_plugins={}),
        watchdog=None,
        alerts=None,
    )

    report = await build_daily_admin_report(bot)

    assert "• uptime: 0s" not in report
    assert "• uptime: unknown" not in report

@pytest.mark.asyncio
async def test_daily_admin_report_distinguishes_completed_one_shots(monkeypatch):
    _patch_backup_health(monkeypatch, age=3600)
    tasks = SimpleNamespace(
        summary_by_kind=lambda: {
            "services_running": 24,
            "one_shots_running": 0,
            "one_shots_completed": 1,
            "services_finished": 0,
            "failed": 0,
            "cancelled": 0,
        },
        snapshot=lambda include_done=True: [],
    )
    bot = SimpleNamespace(
        connection_start_time=datetime.now(timezone.utc),
        config={},
        presence=SimpleNamespace(joined_rooms={}),
        tasks=tasks,
        outbox=None,
        db=SimpleNamespace(rooms=None, maintenance_state={}, command_usage=None),
        bot_plugins=SimpleNamespace(failed_plugins={}),
        watchdog=None,
        alerts=None,
    )

    report = await build_daily_admin_report(bot)

    assert (
        "tasks: 24 services running, 0 one-shots running, "
        "1 one-shots completed, 0 failed, 0 open circuit(s)"
    ) in report


@pytest.mark.asyncio
async def test_daily_admin_report_surfaces_alert_causes_manual_rooms_and_attention(monkeypatch):
    _patch_backup_health(monkeypatch, age=7200)
    tasks = SimpleNamespace(
        summary=lambda: (2, 0, 0),
        snapshot=lambda include_done=True: [],
    )
    bot = SimpleNamespace(
        connection_start_time=datetime.now(timezone.utc),
        config={},
        presence=SimpleNamespace(joined_rooms={"auto@conf": {}, "manual@conf": {}}),
        tasks=tasks,
        outbox=SimpleNamespace(runtime_state=AsyncMock(return_value={
            "pending": 0,
            "dead": 0,
            "oldest_pending_age_seconds": 0,
            "last_error": None,
        })),
        db=SimpleNamespace(
            rooms=SimpleNamespace(list=AsyncMock(return_value=[
                {"room_jid": "auto@conf", "autojoin": 1},
                {"room_jid": "manual@conf", "autojoin": 0},
            ])),
            maintenance_state={},
            command_usage=None,
        ),
        bot_plugins=SimpleNamespace(failed_plugins={}),
        watchdog=None,
        alerts=SimpleNamespace(runtime_state=lambda: {
            "active": 3,
            "active_keys": [
                "backup-age",
                "room-missing:first@conf",
                "room-missing:second@conf",
            ],
        }),
        message_cache=SimpleNamespace(stats=lambda: {
            "messages": 4,
            "pending_writes": 0,
            "retry_backlog": 0,
            "dropped_persistence_entries": 0,
            "last_persistence_error": None,
            "persistent": True,
            "degraded": False,
        }),
    )

    report = await build_daily_admin_report(bot)

    assert "rooms: 1/1 autojoin rooms joined · 1 intentionally/manual" in report
    assert "immediate alerts: 3 active — backup-age, room-missing×2" in report
    assert "first@conf" not in report and "second@conf" not in report
    assert "overall: ⚠️ attention required" in report
