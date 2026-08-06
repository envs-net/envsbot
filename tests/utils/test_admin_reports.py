from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils.admin_reports import build_daily_admin_report


@pytest.mark.asyncio
async def test_daily_admin_report_contains_internal_health_only(monkeypatch):
    monkeypatch.setattr(
        "utils.admin_reports._backup_state",
        AsyncMock(return_value=("backup.zip", "ok")),
    )
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
    )

    report = await build_daily_admin_report(bot)

    assert "EnvsBot daily health" in report
    assert "rooms: 1/1 joined" in report
    assert "backup: backup.zip (ok)" in report
    assert "commands (24h): 7 use(s), 0 failed" in report
    assert "http://" not in report and "https://" not in report
