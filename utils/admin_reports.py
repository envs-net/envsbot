"""Build compact operational reports for XMPP administrators."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any


log = logging.getLogger(__name__)


def _duration(seconds: int | float) -> str:
    value = max(0, int(seconds))
    days, value = divmod(value, 86400)
    hours, value = divmod(value, 3600)
    minutes, seconds = divmod(value, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    """Read a mapping/sqlite row value without assuming ``dict.get`` exists."""
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


async def _room_counts(bot: Any) -> tuple[int, int, int]:
    """Return joined autojoin, configured autojoin and manual room counts."""
    joined_raw = getattr(getattr(bot, "presence", None), "joined_rooms", {}) or {}
    joined_values = joined_raw.keys() if hasattr(joined_raw, "keys") else joined_raw
    joined = {str(room) for room in joined_values}

    rooms = getattr(getattr(bot, "db", None), "rooms", None)
    list_rooms = getattr(rooms, "list", None)
    if not callable(list_rooms):
        return len(joined), len(joined), 0

    try:
        rows = tuple(await list_rooms())
    except Exception:
        return len(joined), len(joined), 0

    autojoin = {
        str(_row_value(row, "room_jid", ""))
        for row in rows
        if bool(_row_value(row, "autojoin", True)) and _row_value(row, "room_jid")
    }
    manual = sum(1 for row in rows if not bool(_row_value(row, "autojoin", True)))
    return len(joined & autojoin), len(autojoin), manual


def _backup_age_seconds(latest: Any) -> int | None:
    """Return backup age from its manifest timestamp, falling back to mtime."""
    created_at = str(getattr(latest, "created_at", "") or "").strip()
    if created_at and created_at != "unknown":
        text = created_at[:-1] + "+00:00" if created_at.endswith("Z") else created_at
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(
                0,
                int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()),
            )
        except ValueError:
            pass

    try:
        modified = float(latest.path.stat().st_mtime)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    return max(0, int(time.time() - modified))


async def _backup_state(*, smoke_test: bool = False) -> tuple[str, str, int | None]:
    try:
        from utils.backups import list_backups, smoke_test_backup, verify_backup

        backups = await asyncio.to_thread(list_backups)
        if not backups:
            return "none", "missing", None
        latest = backups[0]
        checker = smoke_test_backup if smoke_test else verify_backup
        result = await asyncio.to_thread(checker, latest.path)
        suffix = "+restore-smoke" if smoke_test else ""
        status = ("verified" + suffix) if result.get("ok") else "failed"
        return latest.name, status, _backup_age_seconds(latest)
    except Exception as exc:
        return "unknown", f"error:{type(exc).__name__}", None


def _alert_labels(alert_state: dict[str, Any]) -> str:
    """Summarize active alert categories without exposing room/user identifiers."""
    keys = [str(key) for key in alert_state.get("active_keys", ()) or () if key]
    if not keys:
        return ""
    counts = Counter(key.split(":", 1)[0] for key in keys)
    labels = [f"{key}×{count}" if count > 1 else key for key, count in sorted(counts.items())]
    return ", ".join(labels)


def _message_cache_state(bot: Any) -> dict[str, Any]:
    """Return privacy-safe message-cache counters for the report."""
    cache = getattr(bot, "message_cache", None)
    stats = getattr(cache, "stats", None)
    if not callable(stats):
        return {}
    try:
        return dict(stats() or {})
    except Exception:
        log.debug("[ADMIN_REPORT] Could not read message-cache stats", exc_info=True)
        return {}


async def build_daily_admin_report(bot: Any) -> str:
    """Build the daily report without exposing private JIDs or message bodies."""
    now = int(time.time())
    started = getattr(bot, "connection_start_time", None)
    if isinstance(started, datetime):
        if started.tzinfo is None:
            started = started.astimezone()
        uptime = _duration(
            (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()
        )
    else:
        uptime = "unknown"

    joined_autojoin, autojoin_total, manual_rooms = await _room_counts(bot)
    tasks = getattr(bot, "tasks", None)
    failed = finished = service_finished = 0
    task_label = "0 services running, 0 one-shots completed, 0 failed"
    circuits = 0
    if tasks is not None:
        details = getattr(tasks, "summary_by_kind", None)
        if callable(details):
            counts = details()
            failed = int(counts.get("failed", 0))
            finished = int(counts.get("one_shots_completed", 0))
            task_label = (
                f"{int(counts.get('services_running', 0))} services running, "
                f"{int(counts.get('one_shots_running', 0))} one-shots running, "
                f"{finished} one-shots completed, {failed} failed"
            )
            service_finished = int(counts.get("services_finished", 0))
            if service_finished:
                task_label += f", {service_finished} services finished unexpectedly"
        else:
            running, failed, finished = tasks.summary()
            task_label = f"{running} running, {failed} failed, {finished} finished"
        circuits = sum(
            1
            for info in tasks.snapshot(include_done=True)
            if getattr(info, "circuit_state", "closed") == "open"
        )

    outbox_state: dict[str, Any] = {}
    outbox = getattr(bot, "outbox", None)
    if outbox is not None:
        try:
            outbox_state = dict(await outbox.runtime_state() or {})
        except Exception:
            outbox_state = {}

    db = getattr(bot, "db", None)
    maintenance = dict(getattr(db, "maintenance_state", {}) or {})
    usage = {"uses": 0, "failures": 0}
    command_usage = getattr(db, "command_usage", None)
    if command_usage is not None:
        try:
            usage = await command_usage.totals_since(now - 86400)
        except Exception:
            log.debug(
                "[ADMIN_REPORT] Could not read command usage totals",
                exc_info=True,
            )
            usage = {"uses": 0, "failures": 0}

    config = getattr(bot, "config", {}) or {}
    backup_name, backup_status, backup_age = await _backup_state(
        smoke_test=bool(config.get("admin_report_backup_smoke_test", False))
    )
    plugin_failures = len(getattr(getattr(bot, "bot_plugins", None), "failed_plugins", {}) or {})
    watchdog = getattr(bot, "watchdog", None)
    watchdog_state = watchdog.runtime_state() if watchdog is not None else {}
    alerts = getattr(bot, "alerts", None)
    alert_state = alerts.runtime_state() if alerts is not None else {}
    active_alerts = int(alert_state.get("active", 0) or 0)
    alert_labels = _alert_labels(alert_state)
    message_cache = _message_cache_state(bot)

    room_line = f"• rooms: {joined_autojoin}/{autojoin_total or joined_autojoin} autojoin rooms joined"
    if manual_rooms:
        room_line += f" · {manual_rooms} intentionally/manual"

    alert_line = f"• immediate alerts: {active_alerts} active"
    if active_alerts and alert_labels:
        alert_line += f" — {alert_labels}"

    if backup_age is None:
        backup_line = f"• backup: {backup_name} · {backup_status}"
    else:
        backup_line = f"• backup: {backup_name} · {_duration(backup_age)} old · {backup_status}"

    if message_cache:
        persistence = "persistent" if message_cache.get("persistent") else "memory-only"
        cache_health = "degraded" if message_cache.get("degraded") else "healthy"
        message_cache_line = (
            "• message cache: "
            f"{int(message_cache.get('messages', 0) or 0)} messages, "
            f"{int(message_cache.get('pending_writes', 0) or 0)} pending, "
            f"{int(message_cache.get('retry_backlog', 0) or 0)} retry, "
            f"{int(message_cache.get('dropped_persistence_entries', 0) or 0)} dropped · "
            f"{persistence} · {cache_health}"
        )
    else:
        message_cache_line = "• message cache: unavailable"

    lines = [
        "🩺 EnvsBot daily health",
        f"• uptime: {uptime}",
        room_line,
        f"• plugins: {plugin_failures} load failure(s)",
        f"• tasks: {task_label}, {circuits} open circuit(s)",
        alert_line,
        (
            "• outbox: "
            f"{int(outbox_state.get('pending', 0))} pending, "
            f"{int(outbox_state.get('dead', 0))} dead, "
            f"oldest {_duration(int(outbox_state.get('oldest_pending_age_seconds', 0)))}"
        ),
        message_cache_line,
        (
            "• event loop: "
            f"last lag {float(watchdog_state.get('last_lag_seconds', 0.0)):.3f}s, "
            f"max {float(watchdog_state.get('max_lag_seconds', 0.0)):.3f}s"
        ),
        (
            "• database maintenance: "
            f"{int(maintenance.get('runs', 0))} run(s), "
            f"{int(maintenance.get('failures', 0))} failed, "
            f"last {int(maintenance.get('last_duration_ms', 0))}ms"
        ),
        backup_line,
        f"• commands (24h): {int(usage.get('uses', 0))} use(s), {int(usage.get('failures', 0))} failed",
    ]

    last_errors = [
        str(outbox_state.get("last_error") or "").strip(),
        str(maintenance.get("last_error") or "").strip(),
        str(watchdog_state.get("last_error") or "").strip(),
        str(message_cache.get("last_persistence_error") or "").strip(),
    ]
    last_errors = [value for value in last_errors if value]
    if last_errors:
        lines.append("• attention: " + " | ".join(last_errors)[:500])

    needs_attention = any((
        active_alerts > 0,
        plugin_failures > 0,
        failed > 0,
        service_finished > 0,
        circuits > 0,
        int(outbox_state.get("dead", 0) or 0) > 0,
        bool(str(outbox_state.get("last_error") or "").strip()),
        not backup_status.startswith("verified"),
        bool(message_cache.get("degraded", False)),
        bool(str(maintenance.get("last_error") or "").strip()),
        bool(str(watchdog_state.get("last_error") or "").strip()),
    ))
    lines.append(
        "• overall: ⚠️ attention required"
        if needs_attention
        else "• overall: ✅ no current operational errors"
    )
    return "\n".join(lines)
