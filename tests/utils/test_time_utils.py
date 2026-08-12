from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from utils.time_utils import (
    datetime_from_timestamp,
    ensure_utc,
    is_timezone_name,
    localize_wall_time,
    normalize_timezone_name,
    timezone_from_name,
    timezone_or_utc,
    utc_now,
    utc_timestamp,
)


def test_utc_helpers_are_timezone_aware_and_round_trip():
    now = utc_now()
    assert now.tzinfo is UTC
    stamp = utc_timestamp()
    converted = datetime_from_timestamp(stamp)
    assert converted.tzinfo is UTC
    assert abs(converted.timestamp() - stamp) < 0.001


def test_timezone_name_helpers_validate_and_fall_back():
    berlin = timezone_from_name("Europe/Berlin")
    assert isinstance(berlin, ZoneInfo)
    assert berlin.key == "Europe/Berlin"
    assert timezone_from_name("Mars/Base") is None
    assert is_timezone_name("Europe/Berlin") is True
    assert is_timezone_name("Mars/Base") is False
    assert timezone_or_utc("Mars/Base") is UTC
    assert normalize_timezone_name("Europe/Berlin") == "Europe/Berlin"
    assert normalize_timezone_name("Mars/Base") == "UTC"


def test_localize_wall_time_preserves_historical_dst_policy():
    berlin = ZoneInfo("Europe/Berlin")

    ambiguous = localize_wall_time(datetime(2026, 10, 25, 2, 30), berlin)
    assert ambiguous.utcoffset() == timedelta(hours=1)
    assert ambiguous.fold == 1

    nonexistent = localize_wall_time(datetime(2026, 3, 29, 2, 30), berlin)
    assert nonexistent.utcoffset() == timedelta(hours=2)
    assert nonexistent.fold == 1


def test_localize_fixed_offset_and_ensure_utc_for_naive_legacy_values():
    plus_two = timezone(timedelta(hours=2))
    localized = localize_wall_time(datetime(2026, 7, 1, 12, 0), plus_two)
    assert localized.utcoffset() == timedelta(hours=2)
    assert ensure_utc(datetime(2026, 7, 1, 12, 0), assume_tz=plus_two) == datetime(
        2026, 7, 1, 10, 0, tzinfo=UTC
    )
    assert ensure_utc(datetime(2026, 7, 1, 12, 0, tzinfo=UTC)) == datetime(
        2026, 7, 1, 12, 0, tzinfo=UTC
    )


def test_ensure_utc_can_interpret_legacy_naive_local_time(monkeypatch):
    import os
    import time

    if not hasattr(time, "tzset"):
        return

    old_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    try:
        converted = ensure_utc(datetime(2026, 7, 1, 12, 0), assume_tz=None)
        assert converted == datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    finally:
        if old_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", old_tz)
        time.tzset()
