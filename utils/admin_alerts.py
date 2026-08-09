"""Immediate, deduplicated operational alerts delivered through XMPP."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from utils.admin_notify import notify_admin
from utils.task_supervisor import wait_for_runtime_ready

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
                await self._notify(f"🟡 {summary}", key=key, transition="ongoing")
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

    async def _check_outbox(self) -> None:
        store = getattr(getattr(self.bot, "db", None), "outbox", None)
        runtime = getattr(self.bot, "outbox", None)
        if store is None or runtime is None:
            return
        config = getattr(self.bot, "config", {}) or {}
        counts = await store.counts()
        usage = await store.queue_usage()
        queued = int(usage.get("queued", 0) or 0)
        queued_bytes = int(usage.get("bytes", 0) or 0)
        max_pending = max(1, int(config.get("outbox_max_pending", 10000) or 10000))
        max_bytes = max(1, int(config.get("outbox_max_bytes", 50 * 1024 * 1024) or 1))
        max_destination = max(
            1, int(config.get("outbox_max_per_destination", 1000) or 1000)
        )
        max_category = max(
            1, int(config.get("outbox_max_per_category", 5000) or 5000)
        )
        destination_count = int(usage.get("largest_destination_count", 0) or 0)
        category_count = int(usage.get("largest_category_count", 0) or 0)
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
        dead = int(counts.get("dead", 0) or 0)
        await self._set(
            "outbox-dead",
            dead > 0,
            f"Outbox contains {dead} dead-letter message(s)",
            fingerprint="dead" if dead else "",
        )
        oldest = int(await store.oldest_pending_age() or 0)
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

    async def _check_tasks(self) -> None:
        supervisor = getattr(self.bot, "tasks", None)
        if supervisor is None:
            return
        current: set[str] = set()
        for info in supervisor.snapshot(include_done=True):
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

    async def _check_rooms(self) -> None:
        rooms = getattr(getattr(self.bot, "db", None), "rooms", None)
        if rooms is None:
            return
        config = getattr(self.bot, "config", {}) or {}
        threshold = max(60, int(config.get("admin_alert_room_missing_seconds", 1800) or 1800))
        joined_raw = getattr(getattr(self.bot, "presence", None), "joined_rooms", {}) or {}
        joined_values = (
            joined_raw.keys() if hasattr(joined_raw, "keys") else joined_raw
        )
        joined = {str(value) for value in joined_values}
        now = int(time.time())
        configured: set[str] = set()
        for row in await rooms.list():
            room = str(row["room_jid"])
            if not bool(row["autojoin"]):
                continue
            configured.add(room)
            key = f"room-missing:{room}"
            if room in joined:
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
                await self._set(f"room-missing:{room}", False, f"Room is no longer configured: {room}")

    async def _check_backup(self) -> None:
        from utils.backups import list_backups, verify_backup

        config = getattr(self.bot, "config", {}) or {}
        max_age_hours = max(1, int(config.get("admin_alert_backup_max_age_hours", 36) or 36))
        archives = await asyncio.to_thread(list_backups)
        if not archives:
            await self._set("backup-age", True, "No managed envsbot backup exists", fingerprint="missing")
            await self._set("backup-invalid", False, "Backup validation recovered")
            return
        newest = archives[0]
        try:
            modified = newest.path.stat().st_mtime
            age_hours = max(0.0, (time.time() - modified) / 3600.0)
        except OSError:
            age_hours = float(max_age_hours + 1)
        await self._set(
            "backup-age",
            age_hours >= max_age_hours,
            f"Newest backup is {age_hours:.1f}h old (limit {max_age_hours}h): {newest.name}",
            fingerprint="old",
        )
        marker = str(newest.path.resolve())
        if self._last_backup_verified is None or self._last_backup_verified[0] != marker:
            try:
                await asyncio.to_thread(verify_backup, newest.path)
                valid = True
            except Exception:
                valid = False
                log.exception("[ALERTS] Backup verification failed: %s", newest.path)
            self._last_backup_verified = (marker, valid)
        valid = bool(self._last_backup_verified[1])
        await self._set(
            "backup-invalid",
            not valid,
            f"Newest backup failed verification: {newest.name}",
            fingerprint="invalid",
        )

    async def _check_database(self) -> None:
        state = getattr(getattr(self.bot, "db", None), "maintenance_state", {}) or {}
        failures = int(state.get("consecutive_failures", 0) or 0)
        error = str(state.get("last_error") or "")
        await self._set(
            "database-maintenance",
            failures >= 2 and bool(error),
            f"Database maintenance failed repeatedly ({failures} failures): {error}",
            fingerprint="failed",
        )

    async def _check_idlerpg_export(self) -> None:
        try:
            from plugins.idlerpg.state import _public_export_runtime
        except Exception:
            return
        config = getattr(self.bot, "config", {}) or {}
        threshold = max(1, int(config.get("admin_alert_idlerpg_export_failures", 3) or 3))
        state = _public_export_runtime()
        failures = int(state.get("consecutive_failures", 0) or 0)
        error = str(state.get("last_error") or "")
        await self._set(
            "idlerpg-export",
            failures >= threshold and bool(error),
            f"IdleRPG public export failed {failures} time(s): {error}",
            fingerprint="failed",
        )

    async def _check_watchdog(self) -> None:
        watchdog = getattr(self.bot, "watchdog", None)
        state = getattr(watchdog, "state", None)
        if state is None:
            return
        config = getattr(self.bot, "config", {}) or {}
        warning = max(0.1, float(config.get("watchdog_lag_warning_seconds", 2.0) or 2.0))
        lag = float(getattr(state, "last_lag_seconds", 0.0) or 0.0)
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

    async def run_once(self) -> None:
        self._last_check_at = int(time.time())
        try:
            await self._check_outbox()
            await self._check_tasks()
            await self._check_rooms()
            await self._check_backup()
            await self._check_database()
            await self._check_idlerpg_export()
            await self._check_watchdog()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            log.exception("[ALERTS] Health check iteration failed")
            raise
        else:
            self._checks += 1
            self._last_error = None

    async def _run(self) -> None:
        await wait_for_runtime_ready(self.bot)
        config = getattr(self.bot, "config", {}) or {}
        interval = max(30, int(config.get("admin_alert_interval_seconds", 60) or 60))
        while True:
            await self.run_once()
            supervisor = getattr(self.bot, "tasks", None)
            heartbeat = getattr(supervisor, "heartbeat", None)
            if callable(heartbeat):
                heartbeat("_runtime", "admin-alert-manager")
            await asyncio.sleep(interval)

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
            "active": self.active_count(),
            "active_keys": sorted(key for key, state in self._states.items() if state.active),
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
