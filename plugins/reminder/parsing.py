"""Split module for plugins/reminder.py: parsing."""

import asyncio
import datetime
import logging
import pytz
from utils.command import command, Role
from utils.config import config
from core_plugins._core import (
    handle_room_toggle_command,
    get_user_tzinfo,
    JOINED_ROOMS,
    _is_muc_pm,
    _normalize_bare_jid,
    parse_duration,
)
from utils.task_supervisor import create_plugin_task


def _timezone_lookup_jid(bot, sender_jid, msg, is_room: bool) -> str | None:
    """Return the best real JID to use for vCard TIMEZONE lookup."""
    if not is_room and not _is_muc_pm(msg, is_room):
        try:
            return str(msg["from"].bare)
        except Exception:
            return _normalize_bare_jid(sender_jid)

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
            # DST spring-forward gap: move to the next valid local hour.
            return tz.localize(dt + datetime.timedelta(hours=1), is_dst=True)
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


def parse_absolute_datetime(
    args: list[str],
    user_tz: datetime.tzinfo | None = None,
) -> tuple[datetime.datetime | None, int]:
    """Parse an absolute date/time from the beginning of command arguments.

    Returns (datetime_utc, consumed_arg_count), or (None, 0) if parsing fails.
    """
    if not args:
        return None, 0

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
                return _ensure_utc(dt, user_tz), consumed
            except ValueError:
                continue

    return None, 0


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

    remind_at, consumed = parse_absolute_datetime(args, user_tz)
    if remind_at is None or len(args) <= consumed:
        return None, None, None

    message = " ".join(args[consumed:]).strip()
    if not message:
        return None, None, None

    seconds = int((remind_at - _utcnow()).total_seconds())
    if seconds < 1:
        return None, None, None

    display_when = f"on {_format_local_datetime(
        remind_at, user_tz or _utc_tz())}"
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
