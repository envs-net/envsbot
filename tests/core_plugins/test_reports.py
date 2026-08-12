from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

import core_plugins.reports as reports


def test_next_report_at_uses_configured_timezone_and_next_day():
    bot = SimpleNamespace(config={
        "admin_report_time": "08:00",
        "admin_report_timezone": "Europe/Berlin",
    })
    now = datetime(2026, 8, 6, 9, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    target = reports._next_report_at(bot, now=now)
    assert target.isoformat() == "2026-08-07T08:00:00+02:00"


@pytest.mark.asyncio
async def test_report_now_sends_or_queues(monkeypatch):
    monkeypatch.setattr(reports, "send_report", AsyncMock(return_value=True))
    bot = SimpleNamespace(
        prefix=",",
        reply_ok=MagicMock(),
        reply_error=MagicMock(),
        reply_usage=MagicMock(),
    )
    await reports.report_command(bot, "a", "a", ["now"], MagicMock(), False)
    reports.send_report.assert_awaited_once_with(bot, manual=True)
    bot.reply_ok.assert_called_once()


@pytest.mark.asyncio
async def test_send_report_builds_and_sends_daily_deduped_report(monkeypatch):
    build = AsyncMock(return_value="daily health")
    notify = AsyncMock(return_value=True)
    monkeypatch.setattr(reports, "build_daily_admin_report", build)
    monkeypatch.setattr(reports, "notify_admin", notify)

    monkeypatch.setattr(
        reports,
        "utc_now",
        lambda: datetime(2026, 8, 9, 10, 0, tzinfo=ZoneInfo("UTC")),
    )
    bot = SimpleNamespace(config={"admin_report_timezone": "UTC"})

    assert await reports.send_report(bot) is True

    build.assert_awaited_once_with(bot)
    notify.assert_awaited_once()
    args, kwargs = notify.await_args
    assert args == (bot, "daily health")
    assert kwargs == {
        "category": "admin_report",
        "dedupe_key": "daily-admin-report:2026-08-09",
    }


@pytest.mark.asyncio
async def test_send_report_manual_disables_daily_dedupe(monkeypatch):
    monkeypatch.setattr(
        reports, "build_daily_admin_report", AsyncMock(return_value="manual health")
    )
    notify = AsyncMock(return_value=False)
    monkeypatch.setattr(reports, "notify_admin", notify)
    bot = SimpleNamespace(config={})

    assert await reports.send_report(bot, manual=True) is False
    assert notify.await_args.kwargs == {
        "category": "admin_report",
        "dedupe_key": None,
    }
