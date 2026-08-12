"""Immediate, deduplicated operational alerts delivered through XMPP."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from utils.admin_notify import notify_admin
from utils.health import HealthSnapshot, collect_health_snapshot
from utils.task_supervisor import sleep_with_heartbeat, wait_for_runtime_ready
from utils.time_utils import utc_now

log = logging.getLogger(__name__)


@dataclass
class AlertState:
    active: bool = False
    since: int = 0
    last_notified_at: int = 0
    summary: str = ""
    fingerprint: str = ""


class AdminAlertManager:
    """Poll local runtime health and report state transitions without flooding."""

    def __init__(self, bot: Any):
        self.bot = bot
        self.task: asyncio.Task[Any] | None = None
        self._states: dict[str, AlertState] = {}
        self._room_missing_since: dict[str, int] = {}
        self._last_backup_verified: tuple[str, bool] | None = None
        self._checks = 0
        self._notifications = 0
        self._last_check_at = 0
        self._last_error: str | None = None
        self._check_errors: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return bool((getattr(self.bot, "config", {}) or {}).get("admin_alerts_enabled", True))

    async def start(self) -> None:
        if not self.enabled or self.task is not None:
            return
        supervisor = getattr(self.bot, "tasks", None)
        if supervisor is not None:
            self.task = supervisor.create_resilient(
                "_runtime",
                self._run,
                name="admin-alert-manager",
                service=True,
            )
        else:
            self.task = asyncio.create_task(self._run(), name="admin-alert-manager")

    async def stop(self) -> None:
        task = self.task
        self.task = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _notify(self, text: str, *, key: str, transition: str) -> None:
        try:
            sent = await notify_admin(
                self.bot,
                text,
                category="runtime_alert",
                dedupe_key=f"runtime-alert:{key}:{transition}:{int(time.time()) // 60}",
            )
            if sent:
                self._notifications += 1
        except Exception:
            log.exception("[ALERTS] Failed to send admin alert: %s", key)

    async def _set(
        self,
        key: str,
        active: bool,
        summary: str,
        *,
        fingerprint: str = "",
        resolved_summary: str | None = None,
    ) -> None:
        now = int(time.time())
        config = getattr(self.bot, "config", {}) or {}
        cooldown = max(60, int(config.get("admin_alert_cooldown_seconds", 3600) or 3600))
        state = self._states.setdefault(key, AlertState())
        if active:
            first = not state.active
            changed = state.active and fingerprint and fingerprint != state.fingerprint
            if first:
                state.active = True
                state.since = now
                state.last_notified_at = now
                state.summary = summary
                state.fingerprint = fingerprint
                await self._notify(f"🔴 {summary}", key=key, transition="open")
                return
            state.summary = summary
            state.fingerprint = fingerprint or state.fingerprint
            if changed or now - state.last_notified_at >= cooldown:
                state.last_notified_at = now
                await self._notify(f"🔴 Still active: {summary}", key=key, transition="ongoing")
            return

        if state.active:
            state.active = False
            state.last_notified_at = now
            previous = state.summary or summary
            state.summary = summary
            state.fingerprint = ""
            resolved = resolved_summary or previous
            await self._notify(f"✅ Resolved: {resolved}", key=key, transition="resolved")

    async def report_task_circuit(self, plugin: str, name: str, error: str) -> None:
        """Open a task-circuit alert immediately; polling handles recovery."""
        key = f"task-circuit:{plugin}:{name}"
        await self._set(
            key,
            True,
            f"Task circuit is open: {plugin}/{name} ({error})",
            fingerprint="open",
        )

    async def report_outbox_dead(self, message_id: int, category: str) -> None:
        """Report the first/new dead-letter transition without waiting for polling."""
        await self._set(
            "outbox-dead",
            True,
            f"Outbox contains a dead-letter message: id={int(message_id)} category={category}",
            fingerprint="dead",
        )

    async def report_outbox_capacity(self, detail: str) -> None:
        """Report a hard outbox capacity rejection immediately."""
        await self._set(
            "outbox-capacity",
            True,
            f"Outbox capacity rejected a message: {detail}",
            fingerprint="100",
        )

    async def report_event_loop_lag(self, lag: float, warning: float) -> None:
        """Report watchdog lag immediately while periodic checks handle recovery."""
        await self._set(
            "event-loop-lag",
            True,
            f"Event-loop lag is {float(lag):.3f}s (warning {float(warning):.3f}s)",
            fingerprint="lag",
        )

    async def _snapshot_for_check(
        self, snapshot: HealthSnapshot | None
    ) -> HealthSnapshot:
        if snapshot is not None:
            return snapshot
        return await collect_health_snapshot(
            self.bot,
            verify_backup=False,
            include_alert_manager=False,
        )

    async def _check_outbox(
        self, snapshot: HealthSnapshot | None = None
    ) -> None:
        snapshot = await self._snapshot_for_check(snapshot)
        state = snapshot.check("outbox").data
        if not state:
            return
        config = getattr(self.bot, "config", {}) or {}
        queued = int(state.get("queued", state.get("pending", 0)) or 0)
        queued_bytes = int(state.get("bytes", 0) or 0)
        max_pending = max(1, int(config.get("outbox_max_pending", 10000) or 10000))
        max_bytes = max(1, int(config.get("outbox_max_bytes", 50 * 1024 * 1024) or 1))
        max_destination = max(
            1, int(config.get("outbox_max_per_destination", 1000) or 1000)
        )
        max_category = max(
            1, int(config.get("outbox_max_per_category", 5000) or 5000)
        )
        destination_count = int(state.get("largest_destination_count", 0) or 0)
        category_count = int(state.get("largest_category_count", 0) or 0)
        ratio = max(
            queued / max_pending,
            queued_bytes / max_bytes,
            destination_count / max_destination,
            category_count / max_category,
        )
        level = 100 if ratio >= 1 else 80 if ratio >= 0.8 else 50 if ratio >= 0.5 else 0
        await self._set(
            "outbox-capacity",
            level > 0,
            "Outbox usage reached "
            f"{level}% threshold: {queued}/{max_pending} messages, "
            f"{queued_bytes}/{max_bytes} bytes, largest destination "
            f"{destination_count}/{max_destination}, largest category "
            f"{category_count}/{max_category}",
            fingerprint=str(level),
        )
        dead = int(state.get("dead", 0) or 0)
        await self._set(
            "outbox-dead",
            dead > 0,
            f"Outbox contains {dead} dead-letter message(s)",
            fingerprint="dead" if dead else "",
        )
        oldest = int(state.get("oldest_pending_age_seconds", 0) or 0)
        threshold = max(
            60,
            int(config.get("admin_alert_outbox_oldest_seconds", 1800) or 1800),
        )
        await self._set(
            "outbox-oldest",
            oldest >= threshold,
            f"Oldest outbox message has been pending for {oldest}s (limit {threshold}s)",
            fingerprint="old",
        )

    async def _check_tasks(
        self, snapshot: HealthSnapshot | None = None
    ) -> None:
        snapshot = await self._snapshot_for_check(snapshot)
        current: set[str] = set()
        for info in snapshot.check("tasks").data.get("snapshot", ()):
            if str(getattr(info, "circuit_state", "closed")) != "open":
                continue
            key = f"task-circuit:{info.plugin}:{info.name}"
            current.add(key)
            await self._set(
                key,
                True,
                f"Task circuit is open: {info.plugin}/{info.name} ({info.last_error or 'unknown error'})",
                fingerprint="open",
            )
        stale_keys = [
            name
            for name in self._states
            if name.startswith("task-circuit:") and name not in current
        ]
        for key in stale_keys:
            await self._set(key, False, "Task circuit recovered")

    async def _check_rooms(
        self, snapshot: HealthSnapshot | None = None
    ) -> None:
        snapshot = await self._snapshot_for_check(snapshot)
        config = getattr(self.bot, "config", {}) or {}
        threshold = max(60, int(config.get("admin_alert_room_missing_seconds", 1800) or 1800))
        data = snapshot.check("rooms").data
        configured = set(str(room) for room in data.get("autojoin_rooms", ()) or ())
        missing = set(str(room) for room in data.get("missing", ()) or ())
        now = int(time.time())
        for room in configured:
            key = f"room-missing:{room}"
            if room not in missing:
                self._room_missing_since.pop(room, None)
                await self._set(key, False, f"Room rejoined: {room}")
                continue
            since = self._room_missing_since.setdefault(room, now)
            age = now - since
            await self._set(
                key,
                age >= threshold,
                f"Configured room has been missing for {age}s: {room}",
                fingerprint="missing",
            )
        for room in list(self._room_missing_since):
            if room not in configured:
                self._room_missing_since.pop(room, None)
                await self._set(
                    f"room-missing:{room}",
                    False,
                    f"Room is no longer configured: {room}",
                )

    async def _check_backup(
        self, snapshot: HealthSnapshot | None = None
    ) -> None:
        snapshot = await self._snapshot_for_check(snapshot)
        from utils.backups import verify_backup

        data = snapshot.check("backup").data
        config = getattr(self.bot, "config", {}) or {}
        max_age_hours = max(1, int(config.get("admin_alert_backup_max_age_hours", 36) or 36))
        path = data.get("path")
        name = str(data.get("name") or "unknown")
        age_seconds = data.get("age_seconds")
        if path is None:
            await self._set(
                "backup-age",
                True,
                "No managed envsbot backup exists",
                fingerprint="missing",
            )
            await self._set("backup-invalid", False, "Backup validation recovered")
            self._last_backup_verified = None
            return

        too_old = age_seconds is None or int(age_seconds) >= max_age_hours * 3600
        age_hours = (
            float(age_seconds) / 3600.0
            if age_seconds is not None
            else float(max_age_hours + 1)
        )
        interval_hours = max(
            0, int(config.get("backup_interval_hours", 24) or 0)
        )
        schedule = (
            f"scheduled every {interval_hours}h"
            if interval_hours > 0
            else "scheduled backups disabled"
        )
        await self._set(
            "backup-age",
            too_old,
            (
                f"Newest backup is {age_hours:.1f}h old "
                f"(limit {max_age_hours}h; {schedule}): {name}"
            ),
            fingerprint="old" if too_old else "",
        )
        marker = str(path.resolve())
        if self._last_backup_verified is None or self._last_backup_verified[0] != marker:
            try:
                result = await asyncio.to_thread(verify_backup, path)
                valid = bool(result.get("ok"))
            except Exception:
                valid = False
                log.exception("[ALERTS] Backup verification failed: %s", path)
            self._last_backup_verified = (marker, valid)
        valid = bool(self._last_backup_verified[1])
        await self._set(
            "backup-invalid",
            not valid,
            f"Newest backup failed verification: {name}",
            fingerprint="invalid" if not valid else "",
        )

    async def _check_message_cache(
        self, snapshot: HealthSnapshot | None = None
    ) -> None:
        snapshot = await self._snapshot_for_check(snapshot)
        check = snapshot.check("message_cache")
        state = check.data
        if not state and check.status == "unknown":
            return
        degraded = bool(state.get("degraded", False)) or check.status in {"warning", "error"}
        error = str(state.get("last_persistence_error") or check.error or "").strip()
        dropped = int(state.get("dropped_persistence_entries", 0) or 0)
        summary = (
            "Message cache persistence is degraded: "
            f"pending={int(state.get('pending_writes', 0) or 0)}, "
            f"retry={int(state.get('retry_backlog', 0) or 0)}, dropped={dropped}"
        )
        if error:
            summary += f" ({error})"
        await self._set(
            "message-cache",
            degraded,
            summary,
            fingerprint=f"degraded:{dropped}" if degraded else "",
        )

    async def _check_database(
        self, snapshot: HealthSnapshot | None = None
    ) -> None:
        snapshot = await self._snapshot_for_check(snapshot)
        maintenance = dict(snapshot.check("database").data.get("maintenance", {}) or {})
        failures = int(maintenance.get("consecutive_failures", 0) or 0)
        error = str(maintenance.get("last_error") or "")
        await self._set(
            "database-maintenance",
            failures >= 2 and bool(error),
            f"Database maintenance failed repeatedly ({failures} failures): {error}",
            fingerprint="failed",
        )

    async def _check_idlerpg_export(
        self, snapshot: HealthSnapshot | None = None
    ) -> None:
        snapshot = await self._snapshot_for_check(snapshot)
        state = snapshot.check("idlerpg_export").data
        if not state:
            return
        threshold = int(state.get("failure_threshold", 3) or 3)
        failures = int(state.get("consecutive_failures", 0) or 0)
        error = str(state.get("last_error") or "")
        await self._set(
            "idlerpg-export",
            failures >= threshold and bool(error),
            f"IdleRPG public export failed {failures} time(s): {error}",
            fingerprint="failed",
        )

    async def _check_watchdog(
        self, snapshot: HealthSnapshot | None = None
    ) -> None:
        snapshot = await self._snapshot_for_check(snapshot)
        state = snapshot.check("watchdog").data
        if not state:
            return
        warning = float(state.get("warning_seconds", 2.0) or 2.0)
        lag = float(state.get("last_lag_seconds", 0.0) or 0.0)
        await self._set(
            "event-loop-lag",
            lag >= warning,
            f"Event-loop lag is {lag:.3f}s (warning {warning:.3f}s)",
            fingerprint="lag",
            resolved_summary=(
                f"Event-loop lag recovered to {lag:.3f}s "
                f"(warning {warning:.3f}s)"
            ),
        )

    async def _run_health_check(
        self,
        name: str,
        check,
        snapshot: HealthSnapshot,
        errors: dict[str, str],
    ) -> None:
        try:
            await check(snapshot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
            log.exception("[ALERTS] Health check failed: %s", name)

    async def run_once(self) -> None:
        self._last_check_at = int(time.time())
        snapshot = await collect_health_snapshot(
            self.bot,
            verify_backup=False,
            include_alert_manager=False,
        )
        errors = {
            key: check.error
            for key, check in snapshot.checks.items()
            if check.status == "error" and check.error
        }
        checks = (
            ("outbox", self._check_outbox),
            ("tasks", self._check_tasks),
            ("rooms", self._check_rooms),
            ("backup", self._check_backup),
            ("message_cache", self._check_message_cache),
            ("database", self._check_database),
            ("idlerpg_export", self._check_idlerpg_export),
            ("watchdog", self._check_watchdog),
        )
        for name, check in checks:
            await self._run_health_check(name, check, snapshot, errors)
        self._checks += 1
        self._check_errors = errors
        self._last_error = (
            "; ".join(f"{name}: {error}" for name, error in sorted(errors.items()))
            if errors
            else None
        )

    async def _run(self) -> None:
        await wait_for_runtime_ready(
            self.bot, plugin="_runtime", name="admin-alert-manager"
        )
        config = getattr(self.bot, "config", {}) or {}
        interval = max(30, int(config.get("admin_alert_interval_seconds", 60) or 60))
        while True:
            await self.run_once()
            await sleep_with_heartbeat(
                self.bot, "_runtime", "admin-alert-manager", interval
            )

    def active_count(self) -> int:
        return sum(1 for state in self._states.values() if state.active)

    def runtime_state(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "worker_running": bool(self.task and not self.task.done()),
            "checks": self._checks,
            "notifications": self._notifications,
            "last_check_at": self._last_check_at,
            "last_error": self._last_error,
            "check_errors": dict(self._check_errors),
            "active": self.active_count(),
            "active_keys": sorted(key for key, state in self._states.items() if state.active),
            "checked_at": utc_now().isoformat(timespec="seconds"),
        }
