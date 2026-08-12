"""Central timezone and UTC helpers for envsbot.

Internal timestamps should be timezone-aware and use UTC.  User-facing IANA
zone names are resolved through :mod:`zoneinfo`; fixed-offset reminder aliases
remain handled by the reminder parser itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

UTC_ZONE = UTC


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


def utc_timestamp() -> float:
    """Return the current Unix timestamp."""
    return utc_now().timestamp()


def datetime_from_timestamp(value: float | int) -> datetime:
    """Return one Unix timestamp as a timezone-aware UTC datetime."""
    return datetime.fromtimestamp(float(value), tz=UTC)


def timezone_from_name(name: str | None) -> ZoneInfo | None:
    """Resolve one IANA timezone name, returning ``None`` when invalid."""
    cleaned = str(name or "").strip()
    if not cleaned:
        return None
    try:
        return ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def timezone_or_utc(name: str | None) -> tzinfo:
    """Resolve one IANA timezone name and fall back to UTC."""
    return timezone_from_name(name) or UTC


def is_timezone_name(name: str | None) -> bool:
    """Return whether *name* is a valid IANA timezone identifier."""
    return timezone_from_name(name) is not None


def timezone_names() -> frozenset[str]:
    """Return known IANA timezone identifiers from the system tz database."""
    return frozenset(available_timezones())


def normalize_timezone_name(name: str | None, *, default: str = "UTC") -> str:
    """Return a canonical valid IANA name or *default*."""
    zone = timezone_from_name(name)
    if zone is not None:
        return zone.key
    fallback = timezone_from_name(default)
    return fallback.key if fallback is not None else "UTC"


def localize_wall_time(value: datetime, zone: tzinfo) -> datetime:
    """Attach *zone* to a naive wall-clock datetime safely.

    ``zoneinfo`` deliberately does not raise for ambiguous or nonexistent wall
    times.  envsbot keeps the historical reminder behavior explicitly:

    * for an ambiguous fall-back time, choose standard time;
    * for a nonexistent spring-forward time, choose the daylight-saving side.

    Fixed-offset timezones have no transition ambiguity and are attached
    directly.
    """
    if value.tzinfo is not None:
        return value.astimezone(zone)
    if not isinstance(zone, ZoneInfo):
        return value.replace(tzinfo=zone)

    first = value.replace(tzinfo=zone, fold=0)
    second = value.replace(tzinfo=zone, fold=1)
    if first.utcoffset() == second.utcoffset():
        return first

    def round_trips(candidate: datetime) -> bool:
        local = candidate.astimezone(UTC).astimezone(zone)
        return local.replace(tzinfo=None) == value

    first_valid = round_trips(first)
    second_valid = round_trips(second)

    if first_valid and second_valid:
        # Ambiguous fall-back hour: prefer the standard-time occurrence.
        first_dst = first.dst()
        second_dst = second.dst()
        if first_dst is not None and second_dst is not None:
            return first if first_dst <= second_dst else second
        return second
    if first_valid:
        return first
    if second_valid:
        return second

    # Nonexistent spring-forward wall time: fold=1 selects the post-transition
    # (daylight-saving) offset, matching the former pytz ``is_dst=True`` path.
    return second


def ensure_utc(value: datetime, *, assume_tz: tzinfo | None = UTC) -> datetime:
    """Return *value* as timezone-aware UTC.

    Naive values are interpreted in *assume_tz*.  Pass ``None`` to interpret
    one legacy naive value in the host's local timezone.  This is intentionally
    explicit so historical local timestamps are not silently relabelled as UTC.
    """
    if value.tzinfo is None:
        if assume_tz is None:
            value = value.astimezone()
        else:
            value = localize_wall_time(value, assume_tz)
    return value.astimezone(UTC)
