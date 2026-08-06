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
