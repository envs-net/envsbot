"""Split module for plugins/reminder.py: parsing."""

import datetime
import logging
import re

import pytz
from utils.config import config
from core_plugins._core import JOINED_ROOMS, _is_muc_pm, _normalize_bare_jid, parse_duration


log = logging.getLogger(__name__)

REMINDER_DEFAULT_TIMEZONE = str(
    config.get("reminder_default_timezone", "UTC") or "UTC"
)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _utc_tz():
    return pytz.UTC


_FIXED_TIMEZONE_ALIASES: dict[str, datetime.tzinfo] = {
    "Z": datetime.timezone.utc,
    "UTC": datetime.timezone.utc,
    "GMT": datetime.timezone.utc,
    "CET": datetime.timezone(datetime.timedelta(hours=1), "CET"),
    "MEZ": datetime.timezone(datetime.timedelta(hours=1), "CET"),
    "CEST": datetime.timezone(datetime.timedelta(hours=2), "CEST"),
    "MESZ": datetime.timezone(datetime.timedelta(hours=2), "CEST"),
}

_OFFSET_TIMEZONE_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


def _timezone_from_token(token: str) -> datetime.tzinfo | None:
    """Resolve one command-line timezone token.

    Supports IANA names such as ``Europe/Berlin``, common explicit reminder
    abbreviations (UTC/CET/CEST/MEZ/MESZ), and numeric offsets such as ``+0200``
    or ``+02:00``.  The abbreviation handling is intentionally fixed-offset:
    when a user writes CEST, they explicitly requested UTC+02:00.
    """
    cleaned = str(token or "").strip()
    if not cleaned:
        return None

    upper = cleaned.upper()
    if upper in _FIXED_TIMEZONE_ALIASES:
        return _FIXED_TIMEZONE_ALIASES[upper]

    match = _OFFSET_TIMEZONE_RE.match(cleaned)
    if match:
        sign, hour_s, minute_s = match.groups()
        hours = int(hour_s)
        minutes = int(minute_s)
        if hours > 23 or minutes > 59:
            return None
        delta = datetime.timedelta(hours=hours, minutes=minutes)
        if sign == "-":
            delta = -delta
        return datetime.timezone(delta, cleaned)

    if cleaned in pytz.all_timezones:
        return pytz.timezone(cleaned)

    return None


def _reminder_default_tzinfo() -> datetime.tzinfo:
    """Return the reminder fallback timezone from config, defaulting to UTC."""
    timezone_name = str(REMINDER_DEFAULT_TIMEZONE or "UTC")
    timezone = _timezone_from_token(timezone_name)
    if timezone is not None:
        return timezone

    log.warning(
        "[REMINDER] Invalid reminder_default_timezone %r; falling back to UTC",
        timezone_name,
    )
    return pytz.timezone("UTC")


async def get_reminder_tzinfo(bot, timezone_jid: str | None) -> datetime.tzinfo:
    """Return a user's vCard timezone or the reminder config fallback.

    The generic core helper falls back to UTC when no user TIMEZONE is stored.
    For reminders we want a configurable bot-side default while still respecting
    an explicitly configured user timezone, including an explicit UTC setting.
    """
    if timezone_jid:
        try:
            store = bot.db.users.plugin("vcard")
            timezone_name = await store.get(str(timezone_jid), "TIMEZONE")
        except Exception as exc:
            log.warning(
                "[REMINDER] Could not read TIMEZONE for %s: %s; using default",
                timezone_jid,
                exc,
            )
        else:
            timezone = _timezone_from_token(str(timezone_name or ""))
            if timezone is not None:
                return timezone
            if timezone_name:
                log.warning(
                    "[REMINDER] Invalid TIMEZONE for %s: %s; using default",
                    timezone_jid,
                    timezone_name,
                )

    return _reminder_default_tzinfo()


def _timezone_lookup_jid(bot, sender_jid, msg, is_room: bool) -> str | None:
    """Return the best real JID to use for vCard TIMEZONE lookup."""
    is_muc_private = _is_muc_pm(msg)

    # Direct 1:1 chat: the sender bare JID is already the real account.
    if not is_room and not is_muc_private:
        try:
            return str(msg["from"].bare)
        except Exception:
            return _normalize_bare_jid(sender_jid)

    # MUC context, either public room message or MUC PM: resolve room nick to
    # the real JID before looking up the sender's vCard TIMEZONE.
    try:
        muc = getattr(bot, "plugin", {}).get("xep_0045", None)
        if muc:
            room = msg["from"].bare
            nick = msg["from"].resource
            real_jid = muc.get_jid_property(room, nick, "jid")
            if real_jid:
                return _normalize_bare_jid(real_jid)
    except Exception as exc:
        log.debug("[REMINDER] Could not resolve MUC real JID for timezone: %s",
                  exc)

    try:
        room = msg["from"].bare
        muc_nick = msg["from"].resource
        joined = JOINED_ROOMS.get(room, {})
        nick_info = joined.get("nicks", {}).get(muc_nick, {})
        real_jid = nick_info.get("jid")
        if real_jid:
            return _normalize_bare_jid(real_jid)
    except Exception as exc:
        log.debug(
            "[REMINDER] Could not resolve JOINED_ROOMS JID for timezone: %s",
            exc)

    return _normalize_bare_jid(sender_jid)


def _localize_naive_datetime(
    dt: datetime.datetime,
    tz: datetime.tzinfo,
) -> datetime.datetime:
    """Attach timezone to a naive datetime, handling pytz timezones safely."""
    if dt.tzinfo is not None:
        return dt

    if hasattr(tz, "localize"):
        try:
            return tz.localize(dt, is_dst=None)
        except pytz.NonExistentTimeError:
            # DST spring-forward gap: prefer the daylight-saving side of the
            # transition without assuming the gap is exactly one hour long.
            return tz.localize(dt, is_dst=True)
        except pytz.AmbiguousTimeError:
            # DST fall-back duplicate hour: choose standard time.
            return tz.localize(dt, is_dst=False)

    return dt.replace(tzinfo=tz)


def _format_local_datetime(
    dt: datetime.datetime,
    tz: datetime.tzinfo,
) -> str:
    """Format a UTC datetime in the user's local timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")


def format_seconds(total_seconds: float) -> str:
    """Convert seconds to a human-readable duration."""
    if total_seconds < 0:
        return "overdue"

    days = int(total_seconds // 86400)
    remaining = total_seconds % 86400

    hours = int(remaining // 3600)
    remaining %= 3600

    minutes = int(remaining // 60)
    seconds = int(remaining % 60)

    parts = []

    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


def _ensure_utc(
    dt: datetime.datetime,
    assume_tz: datetime.tzinfo | None = None,
) -> datetime.datetime:
    """Return timezone-aware UTC datetime.

    Naive datetime values are interpreted in assume_tz. If no timezone is
    supplied, UTC is used as fallback.
    """
    if dt.tzinfo is None:
        dt = _localize_naive_datetime(dt, assume_tz or _utc_tz())

    return dt.astimezone(datetime.timezone.utc)


def _parse_absolute_datetime_with_timezone(
    args: list[str],
    user_tz: datetime.tzinfo | None = None,
) -> tuple[datetime.datetime | None, int, datetime.tzinfo | None]:
    """Parse absolute date/time and optional timezone from command args."""
    if not args:
        return None, 0, None

    candidates: list[tuple[str, int]] = [(args[0], 1)]

    if len(args) >= 2:
        candidates.append((" ".join(args[:2]), 2))

    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%y %H:%M",
        "%d.%m.%y %H:%M:%S",
    ]

    for candidate, consumed in candidates:
        for fmt in formats:
            try:
                dt = datetime.datetime.strptime(candidate, fmt)
            except ValueError:
                continue

            explicit_tz = None
            if len(args) > consumed:
                explicit_tz = _timezone_from_token(args[consumed])
                if explicit_tz is not None:
                    consumed += 1

            display_tz = explicit_tz or user_tz or _reminder_default_tzinfo()
            return _ensure_utc(dt, display_tz), consumed, display_tz

    return None, 0, None


def parse_absolute_datetime(
    args: list[str],
    user_tz: datetime.tzinfo | None = None,
) -> tuple[datetime.datetime | None, int]:
    """Parse an absolute date/time from the beginning of command arguments.

    Returns (datetime_utc, consumed_arg_count), or (None, 0) if parsing fails.
    An optional timezone token after the time is consumed when present, e.g.
    ``2026-07-10 13:23 CEST`` or ``2026-07-10 13:23 Europe/Berlin``.
    """
    remind_at, consumed, _display_tz = _parse_absolute_datetime_with_timezone(
        args,
        user_tz,
    )
    return remind_at, consumed


def _seconds_until_reminder(remind_at: datetime.datetime) -> int | None:
    """Return seconds until a reminder, with a small minute-grace window.

    Absolute reminder commands only accept minute precision in the common
    formats.  When a user sends ``09:30`` at ``09:30:xx``, the target
    timestamp is technically already in the past.  Treat that same-minute case
    as an immediate reminder instead of rejecting it as invalid.
    """
    seconds_float = (remind_at - _utcnow()).total_seconds()
    if seconds_float >= 1:
        return int(seconds_float)
    if seconds_float > -60:
        return 1
    return None


def explain_invalid_reminder_time(
    args: list[str],
    user_tz: datetime.tzinfo | None = None,
) -> str | None:
    """Return a specific user-facing parse error, when one is known."""
    remind_at, consumed, display_tz = _parse_absolute_datetime_with_timezone(
        args,
        user_tz,
    )
    if remind_at is None:
        return None

    timezone = display_tz or user_tz or _reminder_default_tzinfo()

    if len(args) <= consumed or not " ".join(args[consumed:]).strip():
        return (
            "❌ Missing reminder text after the time.\n"
            "Example: ,remind 2026-05-01 14:30 CEST Take a break"
        )

    if _seconds_until_reminder(remind_at) is None:
        parsed = _format_local_datetime(remind_at, timezone)
        now = _format_local_datetime(_utcnow(), timezone)
        return (
            "❌ Reminder time must be in the future.\n"
            f"Parsed target: {parsed}\n"
            f"Current time: {now}\n"
            "Use a later time or a relative duration like 10m or 1h30m."
        )

    return None


def parse_reminder_when(
    args: list[str],
    user_tz: datetime.tzinfo | None = None,
) -> tuple[int | None, str | None, str | None]:
    """Parse relative duration or absolute date/time from reminder args.

    Returns (seconds_until_reminder, message, display_when). If parsing fails,
    returns (None, None, None).
    """
    if len(args) < 2:
        return None, None, None

    seconds = parse_duration(args[0])
    if seconds is not None:
        message = " ".join(args[1:]).strip()
        if not message:
            return None, None, None

        return seconds, message, f"in {format_seconds(seconds)}"

    remind_at, consumed, display_tz = _parse_absolute_datetime_with_timezone(
        args,
        user_tz,
    )
    if remind_at is None or len(args) <= consumed:
        return None, None, None

    message = " ".join(args[consumed:]).strip()
    if not message:
        return None, None, None

    seconds = _seconds_until_reminder(remind_at)
    if seconds is None:
        return None, None, None

    display_timezone = display_tz or user_tz or _reminder_default_tzinfo()
    formatted_remind_at = _format_local_datetime(remind_at, display_timezone)
    display_when = f"on {formatted_remind_at}"
    return seconds, message, display_when


def _format_overdue(seconds: float) -> str:
    overdue_seconds = abs(seconds)

    if overdue_seconds < 60:
        return f"{int(overdue_seconds)}s ago"
    if overdue_seconds < 3600:
        return f"{int(overdue_seconds / 60)}m ago"
    if overdue_seconds < 86400:
        return f"{overdue_seconds / 3600:.1f}h ago"

    return f"{overdue_seconds / 86400:.1f}d ago"


def _parse_datetime(value) -> datetime.datetime:
    """Handle DB values returned as datetime or ISO string."""
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        dt = datetime.datetime.fromisoformat(str(value))

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    return dt
