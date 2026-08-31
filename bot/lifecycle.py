"""Bot startup/shutdown lifecycle helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from utils.logging_helpers import kv
from utils.time_utils import utc_now
from utils.version import __version__, display_version, normalized_version

log = logging.getLogger(__name__)

_DEFAULT_RESTART_NOTIFICATION_FILE = "data/envsbot_restart_notification.json"
_LEGACY_RESTART_NOTIFICATION_FILE = "/tmp/envsbot_restart_notification.json"


_VERSION_STATE_SCHEMA = 1

def _read_version_state(path: str | Path) -> dict[str, Any]:
    """Read the persisted last-successful-version state."""
    state_path = Path(path)
    try:
        with state_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}

    if not isinstance(payload, dict):
        raise ValueError("version state must be a JSON object")
    raw_version = payload.get("version")
    version = normalized_version(str(raw_version)) if raw_version is not None else ""
    if version == "unknown":
        version = ""
    pending = payload.get("pending_announcement")
    normalized_pending: dict[str, str] | None = None
    if isinstance(pending, dict):
        previous = normalized_version(str(pending.get("from", "")))
        current = normalized_version(str(pending.get("to", "")))
        if previous != "unknown" and current != "unknown" and previous != current:
            normalized_pending = {"from": previous, "to": current}
    result: dict[str, Any] = {}
    if version:
        result["version"] = version
    if normalized_pending is not None:
        result["pending_announcement"] = normalized_pending
    return result

def _write_version_state(path: str | Path, state: dict[str, Any]) -> None:
    """Atomically persist the last-successful-version state."""
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    payload = {
        "schema": _VERSION_STATE_SCHEMA,
        "version": normalized_version(str(state.get("version") or __version__)),
        "updated_at": utc_now().isoformat(),
    }
    pending = state.get("pending_announcement")
    if isinstance(pending, dict):
        payload["pending_announcement"] = {
            "from": normalized_version(str(pending.get("from", ""))),
            "to": normalized_version(str(pending.get("to", ""))),
        }
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, state_path)
    finally:
        tmp_path.unlink(missing_ok=True)

def _version_notification_target(config_obj: Any) -> str:
    """Return the configured target for successful version-change announcements."""
    getter = getattr(config_obj, "get", None)
    if not callable(getter):
        return ""
    for key in ("version_check_notify_jid", "owner"):
        value = str(getter(key, "") or "").strip()
        if value:
            return value
    return ""

def _version_state_path(config_obj: Any) -> Path:
    """Return the persistent successful-version state path lazily."""
    from utils.runtime_paths import version_state_file

    return version_state_file(config_obj)


def _version_change_message(previous_version: str, current_version: str) -> str:
    """Return an upgrade/downgrade message for one successful version change."""
    previous = normalized_version(previous_version)
    current = normalized_version(current_version)

    from utils.updatecheck import parse_version_tuple

    previous_parts = parse_version_tuple(previous)
    current_parts = parse_version_tuple(current)
    if previous_parts and current_parts and current_parts < previous_parts:
        action = "⬇️ EnvsBot downgraded successfully"
    else:
        action = "⬆️ EnvsBot updated successfully"
    return f"{action}: {display_version(previous)} → {display_version(current)}"


def _merge_pending_version_change(
    previous_version: str,
    current_version: str,
    pending: object,
) -> dict[str, str] | None:
    """Preserve the earliest undelivered version when extending a transition."""
    previous = normalized_version(previous_version)
    current = normalized_version(current_version)
    if previous == "unknown" or current == "unknown":
        return None

    existing: dict[str, str] | None = None
    if isinstance(pending, dict):
        pending_from = normalized_version(str(pending.get("from", "")))
        pending_to = normalized_version(str(pending.get("to", "")))
        if (
            pending_from != "unknown"
            and pending_to == previous
            and pending_from != pending_to
        ):
            existing = {"from": pending_from, "to": pending_to}

    if previous == current:
        return existing

    start = existing["from"] if existing is not None else previous
    if start == current:
        return None
    return {"from": start, "to": current}


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
    version: str
    tasks: Any
    _restart_version_change_announced: dict[str, str] | None
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
            current_version = normalized_version(getattr(self, "version", __version__))
            restart_version = normalized_version(str(notif.get("version") or ""))
            version_change = None
            if restart_version != "unknown" and restart_version != current_version:
                version_change = {"from": restart_version, "to": current_version}
            completion = "✅ Bot restart complete!"
            if version_change is not None:
                completion += f" {_version_change_message(restart_version, current_version)}"
            log.info("[ADMIN] event=restart_notification status=processing data=%s", notif)
            if notif.get("is_room") and notif.get("room"):
                message = self.make_message(
                    mto=notif["room"],
                    mbody=f"{notif['nick']}: {completion}",
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
                    mbody=completion,
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
            if version_change is not None:
                self._restart_version_change_announced = version_change

            await asyncio.to_thread(
                _remove_restart_notifications,
                restart_files,
            )
        except FileNotFoundError:
            log.debug("[ADMIN] No restart notification file found")
        except Exception as exc:
            log.error("[ADMIN] Failed to process restart notification: %s", exc)
    async def _send_version_change_notification(
        self,
        previous_version: str,
        current_version: str,
    ) -> bool:
        """Announce one successful version transition to the update target."""
        target = _version_notification_target(getattr(self, "config", {}))
        if not target:
            log.info(
                "[ADMIN] event=version_change_notification status=skipped reason=no_target "
                "from_version=%s to_version=%s",
                previous_version,
                current_version,
            )
            return False
        try:
            from utils.outbox import durable_send
            from utils.xmpp_notify import (
                ensure_notification_target_joined,
                target_is_muc_room,
            )
            is_room = await target_is_muc_room(self, target)
            if is_room and not await ensure_notification_target_joined(self, target):
                log.warning(
                    "[ADMIN] event=version_change_notification status=deferred "
                    "target=%s reason=room_unavailable from_version=%s to_version=%s",
                    target,
                    previous_version,
                    current_version,
                )
                return False
            body = _version_change_message(previous_version, current_version)
            message = self.make_message(
                mto=target,
                mbody=body,
                mtype="groupchat" if is_room else "chat",
            )
            sent = await durable_send(
                self,
                message,
                category="version-update",
                dedupe_key=f"version-update:{previous_version}:{current_version}:{target}",
            )
            if sent:
                log.info(
                    "[ADMIN] event=version_change_notification status=sent target=%s "
                    "from_version=%s to_version=%s",
                    target,
                    previous_version,
                    current_version,
                )
                return True
            log.warning(
                "[ADMIN] event=version_change_notification status=send_failed target=%s "
                "from_version=%s to_version=%s",
                target,
                previous_version,
                current_version,
            )
            return False
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "[ADMIN] event=version_change_notification status=failed target=%s "
                "from_version=%s to_version=%s",
                target,
                previous_version,
                current_version,
            )
            return False
    async def _clear_pending_version_announcement(
        self,
        state_path: Path,
        previous_version: str,
        current_version: str,
    ) -> None:
        """Clear a delivered pending transition without clobbering newer state."""
        try:
            state = await asyncio.to_thread(_read_version_state, state_path)
            pending = state.get("pending_announcement")
            if pending != {"from": previous_version, "to": current_version}:
                return
            state.pop("pending_announcement", None)
            state["version"] = normalized_version(
                str(state.get("version") or current_version)
            )
            await asyncio.to_thread(_write_version_state, state_path, state)
        except Exception:
            log.exception(
                "[ADMIN] event=version_state status=clear_pending_failed path=%s",
                state_path,
            )
    async def _deliver_pending_version_announcement(
        self,
        state_path: Path,
        previous_version: str,
        current_version: str,
    ) -> None:
        """Deliver and clear one persisted post-upgrade announcement."""
        if not await self._send_version_change_notification(
            previous_version,
            current_version,
        ):
            return
        await self._clear_pending_version_announcement(
            state_path,
            previous_version,
            current_version,
        )
    async def _finalize_successful_startup_version(self) -> None:
        """Persist the successful version and schedule any required announcement."""
        current_version = normalized_version(getattr(self, "version", __version__))
        try:
            state_path = _version_state_path(getattr(self, "config", {}))
        except Exception:
            log.warning(
                "[ADMIN] event=version_state status=path_failed version=%s",
                current_version,
                exc_info=True,
            )
            return
        try:
            state = await asyncio.to_thread(_read_version_state, state_path)
        except Exception:
            log.warning(
                "[ADMIN] event=version_state status=read_failed path=%s; "
                "treating this as first successful startup",
                state_path,
                exc_info=True,
            )
            state = {}
        previous_version = str(state.get("version") or "")
        pending = _merge_pending_version_change(
            previous_version,
            current_version,
            state.get("pending_announcement"),
        )

        restart_announced = getattr(self, "_restart_version_change_announced", None)
        if isinstance(pending, dict) and pending == restart_announced:
            pending = None
        next_state: dict[str, Any] = {"version": current_version}
        if isinstance(pending, dict):
            next_state["pending_announcement"] = pending
        try:
            await asyncio.to_thread(_write_version_state, state_path, next_state)
        except Exception:
            log.warning(
                "[ADMIN] event=version_state status=write_failed path=%s version=%s",
                state_path,
                current_version,
                exc_info=True,
            )
            return
        if not isinstance(pending, dict):
            log.info(
                "[ADMIN] event=version_state status=recorded path=%s version=%s",
                state_path,
                current_version,
            )
            return
        previous = str(pending["from"])
        current = str(pending["to"])
        log.info(
            "[ADMIN] event=version_state status=pending path=%s "
            "from_version=%s to_version=%s",
            state_path,
            previous,
            current,
        )

        try:
            from utils.task_supervisor import create_plugin_task
            create_plugin_task(
                self,
                "_runtime",
                self._deliver_pending_version_announcement(
                    state_path,
                    previous,
                    current,
                ),
                name="version-change-announcement",
            )
        except Exception:
            # The transition stays persisted as pending and is retried on the
            # next successful process start.
            log.exception(
                "[ADMIN] event=version_change_notification status=schedule_failed "
                "from_version=%s to_version=%s",
                previous,
                current,
            )
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
    def _log_startup_complete(self) -> bool:
        """Log final plugin/startup health and return whether it is fully healthy."""
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
        return failed_count == 0
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
            startup_healthy = self._log_startup_complete()
            if startup_healthy:
                await self._finalize_successful_startup_version()
            else:
                log.info(
                    "[ADMIN] event=version_state status=deferred "
                    "reason=degraded_startup"
                )
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
        manager = self.bot_plugins
        unload = getattr(manager, "unload_all", None)
        if not callable(unload):
            return "skipped", {}
        details: dict[str, object] = {}
        quiesce = getattr(manager, "quiesce_for_shutdown", None)
        if callable(quiesce):
            quiesce_result = await asyncio.wait_for(
                quiesce(grace_timeout=1.0, cancel_timeout=2.0),
                timeout=4.0,
            )
            if isinstance(quiesce_result, dict):
                quiesce_status = str(quiesce_result.get("status", "unknown"))
                if quiesce_status not in {"idle", "completed"}:
                    details["lifecycle"] = quiesce_status
                operation = quiesce_result.get("operation")
                if operation:
                    details["operation"] = operation
                age_ms = quiesce_result.get("age_ms")
                if age_ms is not None:
                    details["operation_age_ms"] = age_ms
                if quiesce_status == "stuck":
                    return "partial", {
                        **details,
                        "detail": (
                            "active plugin lifecycle operation ignored "
                            "shutdown cancellation; plugin unload skipped"
                        ),
                    }
        result = unload()
        if asyncio.iscoroutine(result):
            result = await asyncio.wait_for(result, timeout=30.0)
        if isinstance(result, tuple) and result and result[0] is False:
            detail = result[1] if len(result) > 1 else "plugin cleanup incomplete"
            return "partial", {**details, "detail": detail}
        return "ok", details
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
