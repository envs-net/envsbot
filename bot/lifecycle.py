"""Bot startup/shutdown lifecycle helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any

from utils.logging_helpers import kv

log = logging.getLogger(__name__)

_DEFAULT_RESTART_NOTIFICATION_FILE = "data/envsbot_restart_notification.json"
_LEGACY_RESTART_NOTIFICATION_FILE = "/tmp/envsbot_restart_notification.json"


def _restart_notification_paths(config_obj: Any) -> list[str]:
    """Return restart-notification state paths in priority order.

    Older configurations used ``/tmp``.  That breaks with systemd
    ``PrivateTmp=true`` because the next process may not see the same temp
    namespace.  Always include the repo-local data path as a persistent fallback
    so ``bot restart`` can notify after restart even before operators update an
    existing config.py.
    """
    getter = getattr(config_obj, "get", None)
    if callable(getter):
        configured = getter("restart_notification_file", _DEFAULT_RESTART_NOTIFICATION_FILE)
    else:
        configured = _DEFAULT_RESTART_NOTIFICATION_FILE
    candidates = [
        str(configured or _DEFAULT_RESTART_NOTIFICATION_FILE),
        _DEFAULT_RESTART_NOTIFICATION_FILE,
        _LEGACY_RESTART_NOTIFICATION_FILE,
    ]
    result: list[str] = []
    for path in candidates:
        if path and path not in result:
            result.append(path)
    return result


def _read_restart_notification(restart_files: list[str]) -> dict[str, Any] | None:
    """Read queued restart metadata outside the event loop."""
    restart_file = next(
        (path for path in restart_files if os.path.exists(path)),
        "",
    )
    if not restart_file:
        return None

    with open(restart_file, "r", encoding="utf-8") as handle:
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

    async def on_start(self, event: Any) -> None:
        """Handle slixmpp session_start."""
        self.connection_start_time = datetime.now()
        try:
            self["xep_0030"].add_feature("http://jabber.org/protocol/muc#user")
        except Exception:
            log.debug("[BOT] Could not advertise MUC-PM feature", exc_info=True)

        self.presence.broadcast()
        await self.get_roster()
        await self.db.connect()
        await self.message_cache.start(self.db.message_cache)
        outbox = getattr(self, "outbox", None)
        outbox_store = getattr(self.db, "outbox", None)
        outbox_start = getattr(outbox, "start", None)
        if callable(outbox_start) and outbox_store is not None:
            await outbox_start(outbox_store)

        await self.bot_plugins.load_all()
        await self.bot_plugins.call_on_ready()
        await self._create_startup_backup()
        await self._send_restart_notification()
        watchdog_start = getattr(getattr(self, "watchdog", None), "start", None)
        if callable(watchdog_start):
            await watchdog_start()
        alerts_start = getattr(getattr(self, "alerts", None), "start", None)
        if callable(alerts_start):
            await alerts_start()

        self.presence.broadcast()
        self.roster.auto_subscribe = True

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
            log.warning(
                "[BOT] ⚠️ Bot started with %d plugin load failure(s)",
                failed_count,
            )
        else:
            log.info("[BOT] ✅ Bot started successfully")

    async def shutdown_runtime(self) -> None:
        """Run the ordered shutdown once, even when callers race."""
        lock = getattr(self, "_shutdown_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._shutdown_lock = lock

        async with lock:
            if getattr(self, "_shutdown_complete", False):
                return
            try:
                await self._shutdown_runtime_once()
            finally:
                self._shutdown_complete = True

    async def _shutdown_runtime_once(self) -> None:
        """Best-effort ordered shutdown of tasks, cache and database."""
        log.info("[LIFECYCLE] event=shutdown phase=start status=begin")
        self.accepting_commands = False

        alerts_status = "skipped"
        try:
            alerts = getattr(self, "alerts", None)
            stop_alerts = getattr(alerts, "stop", None)
            if callable(stop_alerts):
                await stop_alerts()
                alerts_status = "ok"
        except Exception:
            alerts_status = "failed"
            log.exception("[LIFECYCLE] event=shutdown phase=alerts status=failed")
        else:
            log.info("[LIFECYCLE] event=shutdown phase=alerts %s", kv(status=alerts_status))

        watchdog_status = "skipped"
        try:
            watchdog = getattr(self, "watchdog", None)
            stop_watchdog = getattr(watchdog, "stop", None)
            if callable(stop_watchdog):
                await stop_watchdog()
                watchdog_status = "ok"
        except Exception:
            watchdog_status = "failed"
            log.exception("[LIFECYCLE] event=shutdown phase=watchdog status=failed")

        reply_status = "skipped"
        reply_completed = 0
        reply_cancelled = 0
        try:
            drain_replies = getattr(self, "_drain_reply_tasks", None)
            if callable(drain_replies):
                reply_completed, reply_cancelled = await asyncio.wait_for(
                    drain_replies(timeout=3.0),
                    timeout=4.0,
                )
                reply_status = "ok"
        except Exception:
            reply_status = "failed"
            log.exception("[LIFECYCLE] event=shutdown phase=replies status=failed")
        else:
            log.info(
                "[LIFECYCLE] event=shutdown phase=replies %s",
                kv(
                    status=reply_status,
                    completed=reply_completed,
                    cancelled=reply_cancelled,
                ),
            )

        plugin_status = "skipped"
        try:
            unload = getattr(self.bot_plugins, "unload_all", None)
            if callable(unload):
                result = unload()
                if asyncio.iscoroutine(result):
                    result = await asyncio.wait_for(result, timeout=30.0)
                if (
                    isinstance(result, tuple)
                    and result
                    and result[0] is False
                ):
                    plugin_status = "partial"
                    detail = result[1] if len(result) > 1 else "plugin cleanup incomplete"
                    log.warning(
                        "[LIFECYCLE] event=shutdown phase=plugins "
                        "status=partial detail=%s",
                        detail,
                    )
                else:
                    plugin_status = "ok"
        except Exception:
            plugin_status = "failed"
            log.exception("[LIFECYCLE] event=shutdown phase=plugins status=failed")
        else:
            log.info("[LIFECYCLE] event=shutdown phase=plugins %s", kv(status=plugin_status))

        outbox_status = "skipped"
        try:
            outbox = getattr(self, "outbox", None)
            stop_outbox = getattr(outbox, "stop", None)
            if callable(stop_outbox):
                await stop_outbox(timeout=10.0)
                outbox_status = "ok"
        except Exception:
            outbox_status = "failed"
            log.exception("[LIFECYCLE] event=shutdown phase=outbox status=failed")
        else:
            log.info("[LIFECYCLE] event=shutdown phase=outbox %s", kv(status=outbox_status))

        cache_status = "skipped"
        try:
            message_cache = getattr(self, "message_cache", None)
            close_cache = getattr(message_cache, "close", None)
            if callable(close_cache):
                await asyncio.wait_for(close_cache(), timeout=10.0)
                cache_status = "ok"
        except Exception:
            cache_status = "failed"
            log.exception(
                "[LIFECYCLE] event=shutdown phase=message_cache status=failed"
            )
        else:
            log.info(
                "[LIFECYCLE] event=shutdown phase=message_cache %s",
                kv(status=cache_status),
            )

        db_workers_status = "skipped"
        try:
            stop_db_workers = getattr(self.db, "stop_background_tasks", None)
            if callable(stop_db_workers):
                await stop_db_workers(timeout=5.0)
                db_workers_status = "ok"
        except Exception:
            db_workers_status = "failed"
            log.exception(
                "[LIFECYCLE] event=shutdown phase=db_workers status=failed"
            )
        else:
            log.info(
                "[LIFECYCLE] event=shutdown phase=db_workers %s",
                kv(status=db_workers_status),
            )

        task_status = "skipped"
        cancelled = 0
        try:
            tasks = getattr(self, "tasks", None)
            cancel_all = getattr(tasks, "cancel_all", None)
            if callable(cancel_all):
                result = cancel_all(timeout=10.0)
                if asyncio.iscoroutine(result):
                    cancelled = int(await asyncio.wait_for(result, timeout=12.0) or 0)
                task_status = "ok"
        except Exception:
            task_status = "failed"
            log.exception("[LIFECYCLE] event=shutdown phase=tasks status=failed")
        else:
            log.info("[LIFECYCLE] event=shutdown phase=tasks %s", kv(status=task_status, cancelled=cancelled))

        db_status = "ok"
        db_timeout = _database_shutdown_timeout(getattr(self, "config", {}))
        try:
            await asyncio.wait_for(self.db.close(), timeout=db_timeout)
        except asyncio.TimeoutError:
            db_status = "timeout"
            log.warning(
                "[LIFECYCLE] event=shutdown phase=db status=timeout timeout=%.1fs",
                db_timeout,
            )
        except Exception as exc:
            db_status = "failed"
            log.exception("[LIFECYCLE] event=shutdown phase=db status=failed error=%s", exc)
        else:
            log.info("[LIFECYCLE] event=shutdown phase=db status=closed")
        healthy_statuses = {"ok", "skipped"}
        overall_status = (
            "ok"
            if db_status == "ok"
            and reply_status in healthy_statuses
            and plugin_status in healthy_statuses
            and task_status in healthy_statuses
            and cache_status in healthy_statuses
            and db_workers_status in healthy_statuses
            and alerts_status in healthy_statuses
            and watchdog_status in healthy_statuses
            and outbox_status in healthy_statuses
            else "partial"
        )
        log.info(
            "[LIFECYCLE] event=shutdown phase=done %s",
            kv(
                status=overall_status,
                replies=reply_status,
                plugins=plugin_status,
                tasks=task_status,
                message_cache=cache_status,
                db_workers=db_workers_status,
                alerts=alerts_status,
                watchdog=watchdog_status,
                outbox=outbox_status,
                db=db_status,
            ),
        )
