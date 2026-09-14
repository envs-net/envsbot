"""Shared runtime-health snapshot used by status, reports, doctor and alerts."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from envs_xmpp_core.runtime.health import (
    HealthCheck,
    HealthSnapshot,
    HealthStatus,
    analyze_room_join_state,
    supervisor_task_health_state,
    watchdog_health_state,
)
from envs_xmpp_core.runtime.health import (
    collect_health_snapshot as collect_shared_health_snapshot,
)

from utils.backups import backup_age_seconds

log = logging.getLogger(__name__)


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


async def _rooms_check(bot: Any) -> HealthCheck:
    joined_raw = getattr(getattr(bot, "presence", None), "joined_rooms", {}) or {}
    joined_values = joined_raw.keys() if hasattr(joined_raw, "keys") else joined_raw
    joined = {str(room) for room in joined_values}
    try:
        from bot.room_state import JOINED_ROOMS

        joined.update(str(room) for room in JOINED_ROOMS)
    except Exception:
        log.debug("[HEALTH] Could not merge legacy JOINED_ROOMS state", exc_info=True)

    rooms = getattr(getattr(bot, "db", None), "rooms", None)
    list_rooms = getattr(rooms, "list", None)
    if not callable(list_rooms):
        return HealthCheck(
            "rooms",
            "unknown",
            "room store unavailable",
            {"joined": len(joined), "joined_rooms": tuple(sorted(joined))},
        )

    rows = tuple(await list_rooms())
    autojoin = {
        str(_row_value(row, "room_jid", ""))
        for row in rows
        if bool(_row_value(row, "autojoin", True)) and _row_value(row, "room_jid")
    }
    manual = {
        str(_row_value(row, "room_jid", ""))
        for row in rows
        if not bool(_row_value(row, "autojoin", True)) and _row_value(row, "room_jid")
    }
    room_state = analyze_room_join_state(
        configured=autojoin | manual,
        expected=autojoin,
        joined=joined,
    )
    missing = room_state.missing_expected
    status: HealthStatus = "warning" if missing else "ok"
    summary = (
        f"{room_state.expected_joined}/{len(room_state.expected_rooms)} autojoin rooms joined"
        if room_state.expected_rooms
        else "no autojoin rooms configured"
    )
    return HealthCheck(
        "rooms",
        status,
        summary,
        {
            "joined": len(room_state.joined_rooms),
            "autojoin_total": len(room_state.expected_rooms),
            "autojoin_joined": room_state.expected_joined,
            "manual_total": len(manual),
            "missing": missing,
            "autojoin_rooms": room_state.expected_rooms,
            "joined_rooms": room_state.joined_rooms,
            "runtime_only_rooms": room_state.runtime_only,
        },
    )


async def _tasks_check(bot: Any) -> HealthCheck:
    supervisor = getattr(bot, "tasks", None)
    if supervisor is None:
        return HealthCheck("tasks", "unknown", "task supervisor unavailable")

    diagnostics = supervisor_task_health_state(supervisor, include_done=True)
    if diagnostics is None:
        return HealthCheck("tasks", "unknown", "task supervisor snapshot unavailable")
    tasks = diagnostics.tasks

    details = getattr(supervisor, "summary_by_kind", None)
    if callable(details):
        counts = dict(details() or {})
    else:
        summary = getattr(supervisor, "summary", None)
        if callable(summary):
            running, failed_count, finished = summary()
            counts = {
                "services_running": int(running),
                "one_shots_running": 0,
                "one_shots_completed": int(finished),
                "services_finished": 0,
                "failed": int(failed_count),
            }
        else:
            counts = diagnostics.counts

    open_circuits = tuple(task.label for task in diagnostics.open_circuits)
    failed = int(counts.get("failed", 0) or 0)
    service_finished = int(counts.get("services_finished", 0) or 0)
    status: HealthStatus = "warning" if failed or service_finished or open_circuits else "ok"
    return HealthCheck(
        "tasks",
        status,
        (
            f"{int(counts.get('services_running', 0) or 0)} services running, "
            f"{int(counts.get('one_shots_running', 0) or 0)} one-shots running, "
            f"{int(counts.get('one_shots_completed', 0) or 0)} one-shots completed, "
            f"{failed} failed, {len(open_circuits)} open circuits"
        ),
        {**counts, "open_circuits": open_circuits, "snapshot": tuple(tasks)},
    )


async def _outbox_check(bot: Any) -> HealthCheck:
    outbox = getattr(bot, "outbox", None)
    runtime_state = getattr(outbox, "runtime_state", None)
    if callable(runtime_state):
        state = dict(await runtime_state() or {})
    else:
        # Keep the health layer useful during early startup and in tooling that
        # only exposes the persistent store, before the runtime worker exists.
        store = getattr(getattr(bot, "db", None), "outbox", None)
        counts = getattr(store, "counts", None)
        queue_usage = getattr(store, "queue_usage", None)
        oldest_pending_age = getattr(store, "oldest_pending_age", None)
        if not (callable(counts) and callable(queue_usage) and callable(oldest_pending_age)):
            return HealthCheck("outbox", "unknown", "persistent outbox unavailable")
        count_data = dict(await counts() or {})
        usage_data = dict(await queue_usage() or {})
        state = {
            **count_data,
            **usage_data,
            "oldest_pending_age_seconds": int(await oldest_pending_age() or 0),
            "worker_running": outbox is not None,
            "last_error": None,
        }

    dead = int(state.get("dead", 0) or 0)
    error = str(state.get("last_error") or "").strip()
    worker_running = bool(state.get("worker_running", True))
    status: HealthStatus = "warning" if dead or error or not worker_running else "ok"
    return HealthCheck(
        "outbox",
        status,
        (
            f"{int(state.get('pending', 0) or 0)} pending, {dead} dead, "
            f"oldest {int(state.get('oldest_pending_age_seconds', 0) or 0)}s"
        ),
        state,
        error or None,
    )


async def _message_cache_check(bot: Any) -> HealthCheck:
    cache = getattr(bot, "message_cache", None)
    stats = getattr(cache, "stats", None)
    if not callable(stats):
        return HealthCheck("message_cache", "unknown", "message cache unavailable")
    state = dict(stats() or {})
    degraded = bool(state.get("degraded", False))
    error = str(state.get("last_persistence_error") or "").strip()
    status: HealthStatus = "warning" if degraded or error else "ok"
    return HealthCheck(
        "message_cache",
        status,
        (
            f"{int(state.get('messages', 0) or 0)} messages, "
            f"{int(state.get('pending_writes', 0) or 0)} pending, "
            f"{int(state.get('retry_backlog', 0) or 0)} retry, "
            f"{int(state.get('dropped_persistence_entries', 0) or 0)} dropped"
        ),
        state,
        error or None,
    )


async def _backup_check(bot: Any, *, verify: bool, smoke_test: bool = False) -> HealthCheck:
    from utils.backups import list_backups, smoke_test_backup, verify_backup

    config = getattr(bot, "config", {}) or {}
    max_age_hours = max(1, int(config.get("admin_alert_backup_max_age_hours", 36) or 36))
    interval_hours = max(0, int(config.get("backup_interval_hours", 24) or 0))
    backup_on_start = bool(config.get("backup_on_start", True))
    age_check_enabled = interval_hours > 0
    managed_backup_expected = backup_on_start or age_check_enabled
    archives = await asyncio.to_thread(list_backups)
    if not archives:
        status: HealthStatus = "warning" if managed_backup_expected else "ok"
        summary = "no managed envsbot backup exists" if managed_backup_expected else "managed backups disabled"
        return HealthCheck(
            "backup",
            status,
            summary,
            {
                "name": "none",
                "status": "missing" if managed_backup_expected else "disabled",
                "age_seconds": None,
                "path": None,
                "max_age_hours": max_age_hours,
                "age_check_enabled": age_check_enabled,
                "managed_backup_expected": managed_backup_expected,
                "too_old": False,
                "valid": None,
            },
        )

    latest = archives[0]
    age_seconds = backup_age_seconds(latest)
    too_old = age_check_enabled and (age_seconds is None or age_seconds >= max_age_hours * 3600)
    validation_status = "not-checked"
    valid: bool | None = None
    if verify:
        checker = smoke_test_backup if smoke_test else verify_backup
        result = await asyncio.to_thread(checker, latest.path)
        valid = bool(result.get("ok"))
        if valid and smoke_test:
            validation_status = "verified+restore-smoke"
        elif valid:
            validation_status = "verified"
        else:
            validation_status = "failed"

    backup_status: HealthStatus = "warning" if too_old or valid is False else "ok"
    age_text = "unknown age" if age_seconds is None else f"{age_seconds}s old"
    return HealthCheck(
        "backup",
        backup_status,
        f"{latest.name} · {age_text} · {validation_status}",
        {
            "name": latest.name,
            "path": Path(latest.path),
            "created_at": getattr(latest, "created_at", "unknown"),
            "age_seconds": age_seconds,
            "max_age_hours": max_age_hours,
            "age_check_enabled": age_check_enabled,
            "managed_backup_expected": managed_backup_expected,
            "too_old": too_old,
            "valid": valid,
            "status": validation_status,
        },
    )


async def _database_check(bot: Any) -> HealthCheck:
    db = getattr(bot, "db", None)
    if db is None:
        return HealthCheck("database", "error", "database unavailable")
    maintenance = dict(getattr(db, "maintenance_state", {}) or {})
    error = str(maintenance.get("last_error") or "").strip()
    status: HealthStatus = "warning" if error else "ok"
    return HealthCheck(
        "database",
        status,
        (
            f"maintenance runs={int(maintenance.get('runs', 0) or 0)}, "
            f"failures={int(maintenance.get('failures', 0) or 0)}, "
            f"last={int(maintenance.get('last_duration_ms', 0) or 0)}ms"
        ),
        {"maintenance": maintenance, "connected": getattr(db, "conn", None) is not None},
        error or None,
    )


async def _watchdog_check(bot: Any) -> HealthCheck:
    diagnostics = watchdog_health_state(getattr(bot, "watchdog", None))
    if not diagnostics.available:
        return HealthCheck("watchdog", "unknown", "runtime watchdog unavailable")

    config = getattr(bot, "config", {}) or {}
    warning = max(0.1, float(config.get("watchdog_lag_warning_seconds", 2.0) or 2.0))
    lag = diagnostics.last_lag_seconds
    error = diagnostics.last_error or ""
    status: HealthStatus = "warning" if error or lag >= warning else "ok"
    state = diagnostics.as_dict()
    state["warning_seconds"] = warning
    return HealthCheck(
        "watchdog",
        status,
        f"last lag {lag:.3f}s, max {diagnostics.max_lag_seconds:.3f}s",
        state,
        error or None,
    )


async def _plugins_check(bot: Any) -> HealthCheck:
    manager = getattr(bot, "bot_plugins", None)
    if manager is None:
        return HealthCheck("plugins", "unknown", "plugin manager unavailable")
    failed_plugins = dict(getattr(manager, "failed_plugins", {}) or {})
    status: HealthStatus = "warning" if failed_plugins else "ok"
    return HealthCheck(
        "plugins",
        status,
        f"{len(failed_plugins)} load failure(s)",
        {"failed_count": len(failed_plugins), "failed_plugins": tuple(sorted(failed_plugins))},
    )


async def _idlerpg_export_check(bot: Any) -> HealthCheck:
    try:
        from plugins.idlerpg.state import _public_export_runtime
    except Exception:
        return HealthCheck("idlerpg_export", "unknown", "IdleRPG export unavailable")
    state = dict(_public_export_runtime() or {})
    config = getattr(bot, "config", {}) or {}
    threshold = max(1, int(config.get("admin_alert_idlerpg_export_failures", 3) or 3))
    failures = int(state.get("consecutive_failures", 0) or 0)
    error = str(state.get("last_error") or "").strip()
    status: HealthStatus = "warning" if failures >= threshold and error else "ok"
    state["failure_threshold"] = threshold
    return HealthCheck(
        "idlerpg_export",
        status,
        f"{failures} consecutive failure(s)",
        state,
        error or None,
    )


async def _alerts_check(bot: Any) -> HealthCheck:
    alerts = getattr(bot, "alerts", None)
    runtime_state = getattr(alerts, "runtime_state", None)
    if not callable(runtime_state):
        return HealthCheck("alerts", "unknown", "admin alerts unavailable")
    state = dict(runtime_state() or {})
    active = int(state.get("active", 0) or 0)
    error = str(state.get("last_error") or "").strip()
    status: HealthStatus = "warning" if active or error else "ok"
    return HealthCheck(
        "alerts",
        status,
        f"{active} active alert(s)",
        state,
        error or None,
    )


async def collect_health_snapshot(
    bot: Any,
    *,
    verify_backup: bool = False,
    backup_smoke_test: bool = False,
    include_alert_manager: bool = True,
) -> HealthSnapshot:
    """Collect all shared health checks without one failure aborting the rest."""
    collectors: list[tuple[str, Any]] = [
        ("rooms", lambda: _rooms_check(bot)),
        ("tasks", lambda: _tasks_check(bot)),
        ("outbox", lambda: _outbox_check(bot)),
        ("message_cache", lambda: _message_cache_check(bot)),
        (
            "backup",
            lambda: _backup_check(bot, verify=verify_backup, smoke_test=backup_smoke_test),
        ),
        ("database", lambda: _database_check(bot)),
        ("watchdog", lambda: _watchdog_check(bot)),
        ("plugins", lambda: _plugins_check(bot)),
        ("idlerpg_export", lambda: _idlerpg_export_check(bot)),
    ]
    if include_alert_manager:
        collectors.append(("alerts", lambda: _alerts_check(bot)))

    return await collect_shared_health_snapshot(collectors)
