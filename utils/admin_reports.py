"""Build compact operational reports for XMPP administrators."""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from utils.health import collect_health_snapshot

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


def _alert_labels(alert_state: dict[str, Any]) -> str:
    """Summarize active alert categories without exposing room/user identifiers."""
    keys = [str(key) for key in alert_state.get("active_keys", ()) or () if key]
    if not keys:
        return ""
    counts = Counter(key.split(":", 1)[0] for key in keys)
    labels = [f"{key}×{count}" if count > 1 else key for key, count in sorted(counts.items())]
    return ", ".join(labels)


async def build_daily_admin_report(bot: Any) -> str:
    """Build the daily report from the same health snapshot as status/doctor."""
    now = int(time.time())
    started = getattr(bot, "connection_start_time", None)
    if isinstance(started, datetime):
        if started.tzinfo is None:
            started = started.astimezone()
        uptime = _duration(
            (datetime.now(UTC) - started.astimezone(UTC)).total_seconds()
        )
    else:
        uptime = "unknown"

    config = getattr(bot, "config", {}) or {}
    health = await collect_health_snapshot(
        bot,
        verify_backup=True,
        backup_smoke_test=bool(config.get("admin_report_backup_smoke_test", False)),
    )
    room = health.check("rooms")
    tasks = health.check("tasks")
    outbox = health.check("outbox")
    database = health.check("database")
    backup = health.check("backup")
    plugins = health.check("plugins")
    watchdog = health.check("watchdog")
    alerts = health.check("alerts")
    message_cache = health.check("message_cache")

    room_data = room.data
    joined_autojoin = int(room_data.get("autojoin_joined", 0) or 0)
    autojoin_total = int(room_data.get("autojoin_total", 0) or 0)
    manual_rooms = int(room_data.get("manual_total", 0) or 0)
    room_line = f"• rooms: {joined_autojoin}/{autojoin_total} autojoin rooms joined"
    if manual_rooms:
        room_line += f" · {manual_rooms} intentionally/manual"

    task_data = tasks.data
    failed = int(task_data.get("failed", 0) or 0)
    service_finished = int(task_data.get("services_finished", 0) or 0)
    circuits = len(task_data.get("open_circuits", ()) or ())
    if task_data:
        task_label = (
            f"{int(task_data.get('services_running', 0) or 0)} services running, "
            f"{int(task_data.get('one_shots_running', 0) or 0)} one-shots running, "
            f"{int(task_data.get('one_shots_completed', 0) or 0)} one-shots completed, "
            f"{failed} failed"
        )
        if service_finished:
            task_label += f", {service_finished} services finished unexpectedly"
    else:
        task_label = "unavailable"

    alert_data = alerts.data
    active_alerts = int(alert_data.get("active", 0) or 0)
    alert_labels = _alert_labels(alert_data)
    alert_line = f"• immediate alerts: {active_alerts} active"
    if active_alerts and alert_labels:
        alert_line += f" — {alert_labels}"

    backup_data = backup.data
    backup_name = str(backup_data.get("name") or "unknown")
    backup_status = str(backup_data.get("status") or backup.status)
    backup_age = backup_data.get("age_seconds")
    if backup_age is None:
        backup_line = f"• backup: {backup_name} · {backup_status}"
    else:
        backup_line = f"• backup: {backup_name} · {_duration(int(backup_age))} old · {backup_status}"

    cache_data = message_cache.data
    if cache_data:
        persistence = "persistent" if cache_data.get("persistent") else "memory-only"
        cache_health = "degraded" if message_cache.needs_attention else "healthy"
        message_cache_line = (
            "• message cache: "
            f"{int(cache_data.get('messages', 0) or 0)} messages, "
            f"{int(cache_data.get('pending_writes', 0) or 0)} pending, "
            f"{int(cache_data.get('retry_backlog', 0) or 0)} retry, "
            f"{int(cache_data.get('dropped_persistence_entries', 0) or 0)} dropped · "
            f"{persistence} · {cache_health}"
        )
    else:
        message_cache_line = "• message cache: unavailable"

    usage = {"uses": 0, "failures": 0}
    command_usage = getattr(getattr(bot, "db", None), "command_usage", None)
    if command_usage is not None:
        try:
            usage = await command_usage.totals_since(now - 86400)
        except Exception:
            log.debug("[ADMIN_REPORT] Could not read command usage totals", exc_info=True)

    outbox_data = outbox.data
    maintenance = dict(database.data.get("maintenance", {}) or {})
    watchdog_data = watchdog.data
    plugin_failures = int(plugins.data.get("failed_count", 0) or 0)

    lines = [
        "🩺 EnvsBot daily health",
        f"• uptime: {uptime}",
        room_line,
        f"• plugins: {plugin_failures} load failure(s)",
        f"• tasks: {task_label}, {circuits} open circuit(s)",
        alert_line,
        (
            "• outbox: "
            f"{int(outbox_data.get('pending', 0) or 0)} pending, "
            f"{int(outbox_data.get('dead', 0) or 0)} dead, "
            f"oldest {_duration(int(outbox_data.get('oldest_pending_age_seconds', 0) or 0))}"
        ),
        message_cache_line,
        (
            "• event loop: "
            f"last lag {float(watchdog_data.get('last_lag_seconds', 0.0) or 0.0):.3f}s, "
            f"max {float(watchdog_data.get('max_lag_seconds', 0.0) or 0.0):.3f}s"
        ),
        (
            "• database maintenance: "
            f"{int(maintenance.get('runs', 0) or 0)} run(s), "
            f"{int(maintenance.get('failures', 0) or 0)} failed, "
            f"last {int(maintenance.get('last_duration_ms', 0) or 0)}ms"
        ),
        backup_line,
        f"• commands (24h): {int(usage.get('uses', 0))} use(s), {int(usage.get('failures', 0))} failed",
    ]

    last_errors = [
        check.error or ""
        for check in (outbox, database, watchdog, message_cache, backup)
    ]
    last_errors = [value.strip() for value in last_errors if value and value.strip()]
    if last_errors:
        lines.append("• attention: " + " | ".join(last_errors)[:500])

    lines.append(
        "• overall: ⚠️ attention required"
        if health.needs_attention
        else "• overall: ✅ no current operational errors"
    )
    return "\n".join(lines)
