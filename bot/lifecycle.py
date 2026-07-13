"""Bot startup/shutdown lifecycle helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Awaitable, Callable

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


async def call_with_timeout(label: str, func: Callable[[], Awaitable[Any]], timeout: float) -> Any:
    """Run one lifecycle step with logging and an optional timeout."""
    log.debug("[LIFECYCLE] step=%s status=start", label)
    try:
        if timeout and timeout > 0:
            result = await asyncio.wait_for(func(), timeout=timeout)
        else:
            result = await func()
        log.debug("[LIFECYCLE] step=%s status=ok", label)
        return result
    except Exception:
        log.exception("[LIFECYCLE] step=%s status=error", label)
        raise


class LifecycleMixin:
    """Startup/shutdown helper methods for the bot class."""

    async def _send_restart_notification(self) -> None:
        """Send restart completion notification if one was queued."""
        restart_files = _restart_notification_paths(getattr(self, "config", {}))
        restart_file = next((path for path in restart_files if os.path.exists(path)), "")
        if not restart_file:
            return

        try:
            with open(restart_file, "r") as handle:
                notif = json.load(handle)
            for path in restart_files:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    continue

            log.info("[ADMIN] event=restart_notification status=processing data=%s", notif)
            if notif.get("is_room") and notif.get("room"):
                message = self.make_message(
                    mto=notif["room"],
                    mbody=f"{notif['nick']}: ✅ Bot restart complete!",
                    mtype="groupchat",
                )
                await self._safe_send_message(message)
                log.info("[ADMIN] event=restart_notification status=sent room=%s", notif["room"])
            else:
                message = self.make_message(
                    mto=notif["sender"],
                    mbody="✅ Bot restart complete!",
                    mtype="chat",
                )
                await self._safe_send_message(message)
                log.info("[ADMIN] event=restart_notification status=sent target=%s", notif["sender"])
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

        await self.bot_plugins.load_all()
        await self.bot_plugins.call_on_ready()
        await self._create_startup_backup()
        await self._send_restart_notification()

        self.presence.broadcast()
        self.roster.auto_subscribe = True

        failed = getattr(self.bot_plugins, "failed_plugins", None)
        failed_count = len(failed or {}) if isinstance(failed, dict) else 0
        loaded_count = len(getattr(self.bot_plugins, "plugins", {}) or {})
        log.info(
            "[BOT] event=startup status=ok loaded_plugins=%d failed_plugins=%d rooms=%d",
            loaded_count,
            failed_count,
            len(getattr(self.presence, "joined_rooms", {}) or {}),
        )
        log.info("[BOT] ✅ Bot started, all rooms joined")

    async def shutdown_runtime(self) -> None:
        """Best-effort ordered shutdown of tasks, plugins and database."""
        log.info("[LIFECYCLE] event=shutdown phase=start status=begin")
        self.accepting_commands = False

        plugin_status = "skipped"
        try:
            unload = getattr(self.bot_plugins, "unload_all", None)
            if callable(unload):
                result = unload()
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(result, timeout=10.0)
                plugin_status = "ok"
        except Exception:
            plugin_status = "failed"
            log.exception("[LIFECYCLE] event=shutdown phase=plugins status=failed")
        else:
            log.info("[LIFECYCLE] event=shutdown phase=plugins %s", kv(status=plugin_status))

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
        log.info("[LIFECYCLE] event=shutdown phase=done %s", kv(status="ok" if db_status == "ok" else "partial", plugins=plugin_status, tasks=task_status, db=db_status))
