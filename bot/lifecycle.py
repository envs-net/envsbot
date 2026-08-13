"""Bot startup/shutdown lifecycle helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any

from utils.logging_helpers import kv
from utils.time_utils import utc_now

log = logging.getLogger(__name__)

_DEFAULT_RESTART_NOTIFICATION_FILE = "data/envsbot_restart_notification.json"
_LEGACY_RESTART_NOTIFICATION_FILE = "/tmp/envsbot_restart_notification.json"


@dataclass(frozen=True, slots=True)
class LifecyclePhaseResult:
    """One startup/shutdown phase result used for logging and diagnostics."""

    name: str
    status: str
    duration_seconds: float
    details: dict[str, object] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        """Return whether the phase completed cleanly or was not applicable."""
        return self.status in {"ok", "skipped"}


def _restart_notification_paths(config_obj: Any) -> list[str]:
    """Return restart-notification state paths in priority order.

    Older configurations used ``/tmp``.  That breaks with systemd
    ``PrivateTmp=true`` because the next process may not see the same temp
    namespace.  Always include the repo-local data path as a persistent fallback
    so ``bot restart`` can notify after restart even before operators update an
    existing config.py.
    """
    getter = getattr(config_obj, "get", None)
    configured = getter("restart_notification_file") if callable(getter) else None
    candidates = (
        str(configured or _DEFAULT_RESTART_NOTIFICATION_FILE),
        _DEFAULT_RESTART_NOTIFICATION_FILE,
        _LEGACY_RESTART_NOTIFICATION_FILE,
    )
    return list(dict.fromkeys(candidates))


def _read_restart_notification(restart_files: list[str]) -> dict[str, Any] | None:
    """Read queued restart metadata outside the event loop."""
    restart_file = next(
        (path for path in restart_files if os.path.exists(path)),
        "",
    )
    if not restart_file:
        return None

    with open(restart_file, encoding="utf-8") as handle:
        return json.load(handle)


def _remove_restart_notifications(restart_files: list[str]) -> None:
    """Remove all queued restart metadata after successful delivery."""
    for path in restart_files:
        try:
            os.remove(path)
        except FileNotFoundError:
            continue


def _database_shutdown_timeout(config_obj: Any) -> float:
    """Return the database shutdown timeout in seconds.

    SQLite shutdown may need a little longer than the flush timeout because
    aiosqlite still has to drain its worker queue and close the connection.
    Keep a sane lower bound so DB close is never raced by an equal or shorter
    outer timeout.
    """
    try:
        getter = getattr(config_obj, "get", None)
        value = getter("database_shutdown_timeout_seconds", 15.0) if callable(getter) else 15.0
        timeout = float(value)
    except Exception:
        timeout = 15.0
    return max(6.0, timeout)


class LifecycleMixin:
    """Startup/shutdown helper methods for the bot class."""

    # Structural attributes supplied by Bot's other mixins/runtime wiring.
    # Annotation-only declarations keep mypy useful without creating runtime
    # attributes that could interfere with the multiple-inheritance MRO.
    config: Any
    db: Any
    message_cache: Any
    bot_plugins: Any
    presence: Any
    roster: Any
    make_message: Any
    _safe_send_message: Any
    get_roster: Any
    __getitem__: Any
    _startup_backup_done: bool
    connection_start_time: datetime | None

    async def _send_restart_notification(self) -> None:
        """Send restart completion notification if one was queued."""
        restart_files = _restart_notification_paths(getattr(self, "config", {}))

        try:
            notif = await asyncio.to_thread(
                _read_restart_notification,
                restart_files,
            )
            if notif is None:
                return

            log.info("[ADMIN] event=restart_notification status=processing data=%s", notif)
            if notif.get("is_room") and notif.get("room"):
                message = self.make_message(
                    mto=notif["room"],
                    mbody=f"{notif['nick']}: ✅ Bot restart complete!",
                    mtype="groupchat",
                )
                sent = await self._safe_send_message(message)
                if sent is False:
                    log.warning(
                        "[ADMIN] event=restart_notification status=send_failed room=%s",
                        notif["room"],
                    )
                    return
                log.info("[ADMIN] event=restart_notification status=sent room=%s", notif["room"])
            else:
                message = self.make_message(
                    mto=notif["sender"],
                    mbody="✅ Bot restart complete!",
                    mtype="chat",
                )
                sent = await self._safe_send_message(message)
                if sent is False:
                    log.warning(
                        "[ADMIN] event=restart_notification status=send_failed target=%s",
                        notif["sender"],
                    )
                    return
                log.info("[ADMIN] event=restart_notification status=sent target=%s", notif["sender"])

            await asyncio.to_thread(
                _remove_restart_notifications,
                restart_files,
            )
        except FileNotFoundError:
            log.debug("[ADMIN] No restart notification file found")
        except Exception as exc:
            log.error("[ADMIN] Failed to process restart notification: %s", exc)

    async def _create_startup_backup(self) -> None:
        """Create one optional managed backup during this bot process start."""
        if self._startup_backup_done:
            return
        self._startup_backup_done = True

        if not self.config.get("backup_on_start", True):
            log.info("[BACKUP] event=startup_backup status=disabled")
            return

        try:
            import utils.audit as audit_mod
            import utils.backups as backups_mod

            archive_path = await backups_mod.create_backup(self, reason="startup")
            await audit_mod.audit_event(
                self,
                "backup_created",
                actor="system",
                target=archive_path.name,
                details={"reason": "startup", "automatic": True},
            )
            log.info("[BACKUP] event=startup_backup status=created archive=%s", archive_path.name)
        except Exception:
            log.exception("[BACKUP] event=startup_backup status=failed")

    async def _run_startup_phase(
        self,
        name: str,
        operation: Callable[[], Awaitable[None]],
        results: list[LifecyclePhaseResult],
    ) -> None:
        """Run one mandatory startup phase and record its duration/status."""
        started = perf_counter()
        try:
            await operation()
        except Exception:
            result = LifecyclePhaseResult(
                name=name,
                status="failed",
                duration_seconds=perf_counter() - started,
            )
            results.append(result)
            log.exception(
                "[LIFECYCLE] event=startup phase=%s %s",
                name,
                kv(status=result.status, duration_ms=round(result.duration_seconds * 1000, 1)),
            )
            raise

        result = LifecyclePhaseResult(
            name=name,
            status="ok",
            duration_seconds=perf_counter() - started,
        )
        results.append(result)
        log.info(
            "[LIFECYCLE] event=startup phase=%s %s",
            name,
            kv(status=result.status, duration_ms=round(result.duration_seconds * 1000, 1)),
        )

    async def _startup_transport(self) -> None:
        """Advertise transport features, publish presence and fetch the roster."""
        try:
            self["xep_0030"].add_feature("http://jabber.org/protocol/muc#user")
        except Exception:
            log.debug("[BOT] Could not advertise MUC-PM feature", exc_info=True)
        self.presence.broadcast()
        await self.get_roster()

    async def _startup_storage(self) -> None:
        """Open persistent stores and start cache/outbox workers."""
        await self.db.connect()
        await self.message_cache.start(self.db.message_cache)
        outbox = getattr(self, "outbox", None)
        outbox_store = getattr(self.db, "outbox", None)
        outbox_start = getattr(outbox, "start", None)
        if callable(outbox_start) and outbox_store is not None:
            await outbox_start(outbox_store)

    async def _startup_plugins(self) -> None:
        """Load plugins, run their ready hooks and create the startup backup."""
        await self.bot_plugins.load_all()
        await self.bot_plugins.call_on_ready()
        await self._create_startup_backup()

    async def _startup_monitoring(self) -> None:
        """Start runtime health monitors and scheduled managed backups."""
        alerts_start = getattr(getattr(self, "alerts", None), "start", None)
        if callable(alerts_start):
            await alerts_start()
        watchdog_start = getattr(getattr(self, "watchdog", None), "start", None)
        if callable(watchdog_start):
            await watchdog_start()

        import utils.backups as backups_mod

        backups_mod.start_periodic_backup_worker(self)

    async def _startup_publish_ready(self) -> None:
        """Publish final readiness only after restart notification ordering is safe."""
        self.presence.broadcast()
        self.roster.auto_subscribe = True

        # Keep autonomous plugin workers behind the restart-complete stanza.
        # Slixmpp queues outbound stanzas in order, so opening runtime_ready
        # only after this await keeps RSS/reminders/etc. behind the visible
        # restart confirmation while still allowing that confirmation itself
        # to use the established XMPP transport.
        await self._send_restart_notification()

        self.accepting_commands = True
        runtime_ready = getattr(self, "runtime_ready", None)
        if runtime_ready is not None:
            runtime_ready.set()

        outbox = getattr(self, "outbox", None)
        wake_outbox = getattr(getattr(outbox, "wakeup", None), "set", None)
        if callable(wake_outbox):
            wake_outbox()
        notify_ready = getattr(getattr(self, "watchdog", None), "notify_ready", None)
        if callable(notify_ready):
            notify_ready()

    async def _handle_startup_failure(self) -> None:
        """Close routing and clean up a partially initialized runtime."""
        self.accepting_commands = False
        runtime_ready = getattr(self, "runtime_ready", None)
        if runtime_ready is not None:
            runtime_ready.clear()
        session_ready = getattr(self, "session_ready", None)
        if session_ready is not None:
            session_ready.clear()
        self._requested_exit_code = 1

        disconnect = getattr(self, "disconnect", None)
        if callable(disconnect):
            try:
                disconnect()
            except Exception:
                log.exception("[BOT] Failed to disconnect after startup failure")
        try:
            await self.shutdown_runtime()
        except Exception:
            log.exception("[BOT] Failed to clean up partial startup")

    def _log_startup_complete(self) -> None:
        """Log final plugin/startup health after all mandatory phases succeed."""
        failed = getattr(self.bot_plugins, "failed_plugins", None)
        try:
            failed_count = len(failed or {})
        except TypeError:
            failed_count = 0
        loaded_count = len(getattr(self.bot_plugins, "plugins", {}) or {})
        startup_status = "degraded" if failed_count else "ok"
        startup_log = log.warning if failed_count else log.info
        startup_log(
            "[BOT] event=startup status=%s loaded_plugins=%d failed_plugins=%d rooms=%d",
            startup_status,
            loaded_count,
            failed_count,
            len(getattr(self.presence, "joined_rooms", {}) or {}),
        )
        if failed_count:
            log.warning("[BOT] ⚠️ Bot started with %d plugin load failure(s)", failed_count)
        else:
            log.info("[BOT] ✅ Bot started successfully")

    async def on_start(self, event: Any) -> None:
        """Handle slixmpp session_start and expose readiness only after startup."""
        session_ready = getattr(self, "session_ready", None)
        if session_ready is not None:
            session_ready.set()
        runtime_ready = getattr(self, "runtime_ready", None)
        if runtime_ready is not None:
            runtime_ready.clear()
        self.accepting_commands = False
        self.connection_start_time = utc_now()

        results: list[LifecyclePhaseResult] = []
        self._last_startup_phases = tuple(results)
        phases = (
            ("transport", self._startup_transport),
            ("storage", self._startup_storage),
            ("plugins", self._startup_plugins),
            ("monitoring", self._startup_monitoring),
            ("readiness", self._startup_publish_ready),
        )
        try:
            for name, operation in phases:
                await self._run_startup_phase(name, operation, results)
                self._last_startup_phases = tuple(results)
            self._log_startup_complete()
        except Exception:
            self._last_startup_phases = tuple(results)
            log.exception("[BOT] event=startup status=failed")
            await self._handle_startup_failure()
            raise

    def on_session_end(self, event: Any) -> None:
        """Stop new outbound work as soon as the XMPP session ends."""
        session_ready = getattr(self, "session_ready", None)
        if session_ready is not None:
            session_ready.clear()
        runtime_ready = getattr(self, "runtime_ready", None)
        if runtime_ready is not None:
            runtime_ready.clear()
        self.accepting_commands = False

    async def shutdown_runtime(self) -> bool:
        """Run the ordered shutdown once and report whether it was fully clean."""
        lock = getattr(self, "_shutdown_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._shutdown_lock = lock

        async with lock:
            if getattr(self, "_shutdown_complete", False):
                return bool(getattr(self, "_shutdown_clean", False))
            clean = False
            try:
                clean = bool(await self._shutdown_runtime_once())
                return clean
            finally:
                self._shutdown_clean = clean
                self._shutdown_complete = True

    async def _run_shutdown_phase(
        self,
        name: str,
        operation: Callable[[], Awaitable[tuple[str, dict[str, object]]]],
    ) -> LifecyclePhaseResult:
        """Run one best-effort shutdown phase without aborting later phases."""
        started = perf_counter()
        try:
            status, details = await operation()
        except Exception:
            result = LifecyclePhaseResult(
                name=name,
                status="failed",
                duration_seconds=perf_counter() - started,
            )
            log.exception(
                "[LIFECYCLE] event=shutdown phase=%s %s",
                name,
                kv(status=result.status, duration_ms=round(result.duration_seconds * 1000, 1)),
            )
            return result

        result = LifecyclePhaseResult(
            name=name,
            status=status,
            duration_seconds=perf_counter() - started,
            details=details,
        )
        fields = {
            "status": result.status,
            "duration_ms": round(result.duration_seconds * 1000, 1),
            **result.details,
        }
        logger = log.info if result.healthy else log.warning
        logger("[LIFECYCLE] event=shutdown phase=%s %s", name, kv(**fields))
        return result

    async def _shutdown_alerts(self) -> tuple[str, dict[str, object]]:
        alerts = getattr(self, "alerts", None)
        stop_alerts = getattr(alerts, "stop", None)
        if not callable(stop_alerts):
            return "skipped", {}
        await stop_alerts()
        return "ok", {}

    async def _shutdown_watchdog(self) -> tuple[str, dict[str, object]]:
        watchdog = getattr(self, "watchdog", None)
        stop_watchdog = getattr(watchdog, "stop", None)
        if not callable(stop_watchdog):
            return "skipped", {}
        await stop_watchdog()
        return "ok", {}

    async def _shutdown_replies(self) -> tuple[str, dict[str, object]]:
        drain_replies = getattr(self, "_drain_reply_tasks", None)
        if not callable(drain_replies):
            return "skipped", {}
        completed, cancelled = await asyncio.wait_for(
            drain_replies(timeout=3.0),
            timeout=4.0,
        )
        return "ok", {"completed": completed, "cancelled": cancelled}

    async def _shutdown_plugins(self) -> tuple[str, dict[str, object]]:
        unload = getattr(self.bot_plugins, "unload_all", None)
        if not callable(unload):
            return "skipped", {}
        result = unload()
        if asyncio.iscoroutine(result):
            result = await asyncio.wait_for(result, timeout=30.0)
        if isinstance(result, tuple) and result and result[0] is False:
            detail = result[1] if len(result) > 1 else "plugin cleanup incomplete"
            return "partial", {"detail": detail}
        return "ok", {}

    async def _shutdown_outbox(self) -> tuple[str, dict[str, object]]:
        outbox = getattr(self, "outbox", None)
        stop_outbox = getattr(outbox, "stop", None)
        if not callable(stop_outbox):
            return "skipped", {}
        await stop_outbox(timeout=10.0)
        return "ok", {}

    async def _shutdown_message_cache(self) -> tuple[str, dict[str, object]]:
        message_cache = getattr(self, "message_cache", None)
        close_cache = getattr(message_cache, "close", None)
        if not callable(close_cache):
            return "skipped", {}
        cache_result = await asyncio.wait_for(close_cache(), timeout=10.0)
        return ("degraded" if cache_result is False else "ok"), {}

    async def _shutdown_db_workers(self) -> tuple[str, dict[str, object]]:
        stop_db_workers = getattr(self.db, "stop_background_tasks", None)
        if not callable(stop_db_workers):
            return "skipped", {}
        await stop_db_workers(timeout=5.0)
        return "ok", {}

    async def _shutdown_tasks(self) -> tuple[str, dict[str, object]]:
        tasks = getattr(self, "tasks", None)
        cancel_all = getattr(tasks, "cancel_all", None)
        if not callable(cancel_all):
            return "skipped", {}
        result = cancel_all(timeout=10.0)
        if asyncio.iscoroutine(result):
            result = await asyncio.wait_for(result, timeout=12.0)
        return "ok", {"cancelled": int(result or 0)}

    async def _shutdown_database(self) -> tuple[str, dict[str, object]]:
        db_timeout = _database_shutdown_timeout(getattr(self, "config", {}))
        try:
            await asyncio.wait_for(self.db.close(), timeout=db_timeout)
        except TimeoutError:
            return "timeout", {"timeout": f"{db_timeout:.1f}s"}
        return "ok", {}

    def _mark_runtime_stopping(self) -> None:
        """Close inbound routing before any shutdown phase starts."""
        self.accepting_commands = False
        runtime_ready = getattr(self, "runtime_ready", None)
        if runtime_ready is not None:
            runtime_ready.clear()
        session_ready = getattr(self, "session_ready", None)
        if session_ready is not None:
            session_ready.clear()

    def _log_shutdown_complete(self, results: list[LifecyclePhaseResult]) -> bool:
        """Record phase results and emit one compact final shutdown summary."""
        self._last_shutdown_phases = tuple(results)
        clean = all(result.healthy for result in results)
        by_name = {result.name: result.status for result in results}
        log.info(
            "[LIFECYCLE] event=shutdown phase=done %s",
            kv(
                status="ok" if clean else "partial",
                replies=by_name.get("replies", "skipped"),
                plugins=by_name.get("plugins", "skipped"),
                tasks=by_name.get("tasks", "skipped"),
                message_cache=by_name.get("message_cache", "skipped"),
                db_workers=by_name.get("db_workers", "skipped"),
                alerts=by_name.get("alerts", "skipped"),
                watchdog=by_name.get("watchdog", "skipped"),
                outbox=by_name.get("outbox", "skipped"),
                db=by_name.get("db", "failed"),
            ),
        )
        return clean

    async def _shutdown_runtime_once(self) -> bool:
        """Best-effort ordered shutdown of runtime workers and persistence."""
        log.info("[LIFECYCLE] event=shutdown phase=start status=begin")
        self._mark_runtime_stopping()

        phases = (
            ("alerts", self._shutdown_alerts),
            ("watchdog", self._shutdown_watchdog),
            ("replies", self._shutdown_replies),
            ("plugins", self._shutdown_plugins),
            ("outbox", self._shutdown_outbox),
            ("message_cache", self._shutdown_message_cache),
            ("db_workers", self._shutdown_db_workers),
            ("tasks", self._shutdown_tasks),
            ("db", self._shutdown_database),
        )
        results: list[LifecyclePhaseResult] = []
        for name, operation in phases:
            results.append(await self._run_shutdown_phase(name, operation))
        return self._log_shutdown_complete(results)
