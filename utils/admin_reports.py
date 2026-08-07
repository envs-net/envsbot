"""Build compact operational reports for XMPP administrators."""

from __future__ import annotations

import asyncio
import logging
import time
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


async def _room_counts(bot: Any) -> tuple[int, int]:
    joined = len(getattr(getattr(bot, "presence", None), "joined_rooms", {}) or {})
    rooms = getattr(getattr(bot, "db", None), "rooms", None)
    list_rooms = getattr(rooms, "list", None)
    configured = 0
    if callable(list_rooms):
        try:
            configured = len(await list_rooms())
        except Exception:
            configured = 0
    return joined, configured


async def _backup_state(*, smoke_test: bool = False) -> tuple[str, str]:
    try:
        from utils.backups import list_backups, smoke_test_backup, verify_backup

        backups = await asyncio.to_thread(list_backups)
        if not backups:
            return "none", "missing"
        latest = backups[0]
        checker = smoke_test_backup if smoke_test else verify_backup
        result = await asyncio.to_thread(checker, latest.path)
        suffix = "+restore-smoke" if smoke_test else ""
        return latest.name, ("ok" + suffix) if result.get("ok") else "failed"
    except Exception as exc:
        return "unknown", f"error:{type(exc).__name__}"


async def build_daily_admin_report(bot: Any) -> str:
    """Build the daily report without exposing private JIDs or message bodies."""
    now = int(time.time())
    started = getattr(bot, "connection_start_time", None)
    if isinstance(started, datetime):
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        uptime = _duration(datetime.now(timezone.utc).timestamp() - started.timestamp())
    else:
        uptime = "unknown"

    joined, configured = await _room_counts(bot)
    tasks = getattr(bot, "tasks", None)
    failed = finished = 0
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

    outbox_state = {}
    outbox = getattr(bot, "outbox", None)
    if outbox is not None:
        try:
            outbox_state = await outbox.runtime_state()
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
    backup_name, backup_status = await _backup_state(
        smoke_test=bool(config.get("admin_report_backup_smoke_test", False))
    )
    plugin_failures = len(getattr(getattr(bot, "bot_plugins", None), "failed_plugins", {}) or {})
    watchdog = getattr(bot, "watchdog", None)
    watchdog_state = watchdog.runtime_state() if watchdog is not None else {}
    alerts = getattr(bot, "alerts", None)
    alert_state = alerts.runtime_state() if alerts is not None else {}

    lines = [
        "🩺 EnvsBot daily health",
        f"• uptime: {uptime}",
        f"• rooms: {joined}/{configured or joined} joined",
        f"• plugins: {plugin_failures} load failure(s)",
        f"• tasks: {task_label}, {circuits} open circuit(s)",
        f"• immediate alerts: {int(alert_state.get('active', 0))} active",
        (
            "• outbox: "
            f"{int(outbox_state.get('pending', 0))} pending, "
            f"{int(outbox_state.get('dead', 0))} dead, "
            f"oldest {_duration(int(outbox_state.get('oldest_pending_age_seconds', 0)))}"
        ),
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
        f"• backup: {backup_name} ({backup_status})",
        f"• commands (24h): {int(usage.get('uses', 0))} use(s), {int(usage.get('failures', 0))} failed",
    ]
    last_errors = [
        str(outbox_state.get("last_error") or "").strip(),
        str(maintenance.get("last_error") or "").strip(),
        str(watchdog_state.get("last_error") or "").strip(),
    ]
    last_errors = [value for value in last_errors if value]
    if last_errors:
        lines.append("• attention: " + " | ".join(last_errors)[:500])
    else:
        lines.append("• overall: ✅ no current operational errors")
    return "\n".join(lines)
