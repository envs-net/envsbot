#!/usr/bin/env python3

# envsbot: Modular XMPP Bot Framework
# Author: dan <mailto:fab@redterminal.org>
# Author: creme <mailto:creme@envs.net>
# License: GPL-3.0

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
from pathlib import Path

import slixmpp

from bot.audit import AuditMixin
from bot.connection import (
    build_client_jid as _build_client_jid_impl,
    connect_xmpp as _connect_xmpp_impl,
    get_configured_resource as _get_configured_resource_impl,
)
from bot.dispatch import CommandDispatchMixin
from bot.lifecycle import LifecycleMixin
from bot.messages import MessageMixin
from bot.permissions import PermissionMixin
from bot.routing import MessageRoutingMixin
from bot.room_state import room_state
from database.manager import DatabaseManager
from utils.command import Role
from utils.command import check_permission as _check_permission
from utils.command import resolve_command as _resolve_command
from utils.command_execution import CommandExecutor
from utils.config import (
    ConfigError,
    config,
    exit_on_config_error,
    setup_logging,
    validate_startup_config,
)
from utils.config.defaults import BASE_DIR
from utils.message_cache import MessageCache
from utils.runtime_paths import chat_slang_file
from utils.plugin_manager import PluginManager
from utils.presence_manager import PresenceManager
from utils.rate_limiter import TokenBucketRateLimiter
from utils.task_supervisor import TaskSupervisor
from utils.outbox import PersistentOutbox
from utils.runtime_watchdog import RuntimeWatchdog
from utils.admin_alerts import AdminAlertManager
from utils.version import __version__

# === set up logging ===
setup_logging()
log = logging.getLogger(__name__)


def resolve_command(text: str):
    """Compatibility wrapper around the command registry resolver."""
    return _resolve_command(text)


def check_permission(user_role: Role, cmd) -> bool:
    """Compatibility wrapper around role permission checks."""
    return _check_permission(user_role, cmd)


# -------------------------------------------------
# XMPP CONNECTION HELPERS
# -------------------------------------------------


def _get_configured_resource() -> str | None:
    """Return the optional configured XMPP resource."""
    return _get_configured_resource_impl(config)


def _build_client_jid(jid, resource=None) -> str:
    """Build the login JID, optionally replacing/adding a resource."""
    return _build_client_jid_impl(jid, resource)


async def connect_xmpp(xmpp):
    """Connect using optional host, port and direct-TLS config."""
    return await _connect_xmpp_impl(xmpp, config)


# -------------------------------------------------
# BOT CLASS
# -------------------------------------------------


class Bot(
    LifecycleMixin,
    MessageRoutingMixin,
    CommandDispatchMixin,
    PermissionMixin,
    MessageMixin,
    AuditMixin,
    slixmpp.ClientXMPP,
):
    """Main envsbot runtime object."""

    XMPP_PLUGINS = (
        "xep_0012",
        "xep_0030",
        "xep_0045",
        "xep_0054",
        "xep_0084",
        "xep_0092",
        "xep_0153",
        "xep_0163",
        "xep_0199",
        "xep_0249",
        "xep_0359",
        "xep_0461",
        "xep_0511",
    )

    def __init__(self):
        self.config = config
        super().__init__(
            _build_client_jid(config["jid"], _get_configured_resource()),
            config["password"],
        )

        self.nick = config.get("nick", "bot")
        self.admins = []
        self.prefix = config.get("prefix", ",")
        self.version = __version__
        self.last_version_check_result = None
        self.last_update_notified_version = None
        self.connection_start_time = None
        self.tasks = TaskSupervisor()
        self.tasks.bot = self
        self.command_executor = CommandExecutor(self)
        self.message_cache = MessageCache(
            max_messages=int(config.get("message_cache_size", 100) or 100),
            max_age_days=int(config.get("message_cache_max_age_days", 30) or 0),
            task_supervisor=self.tasks,
        )
        self.outbox = PersistentOutbox(self)
        self.watchdog = RuntimeWatchdog(self)
        self.alerts = AdminAlertManager(self)
        self.room_state = room_state
        self._startup_backup_done = False
        self._shutdown_lock = asyncio.Lock()
        self._shutdown_complete = False
        # Unexpected disconnects should be restarted by Restart=on-failure.
        self._requested_exit_code = 1
        self.accepting_commands = True

        self.rate_limiter = TokenBucketRateLimiter(
            capacity=int(config.get("command_rate_limit_capacity", 4)),
            refill_amount=int(config.get("command_rate_limit_refill_amount", 1)),
            refill_interval=float(config.get("command_rate_limit_refill_interval_seconds", 0.5)),
            deny_window=float(config.get("command_rate_limit_deny_window_seconds", 10.0)),
            deny_threshold=int(config.get("command_rate_limit_deny_threshold", 6)),
            base_block_seconds=float(config.get("command_rate_limit_base_block_seconds", 30.0)),
            backoff_multiplier=float(config.get("command_rate_limit_backoff_multiplier", 2.0)),
            max_block_seconds=float(config.get("command_rate_limit_max_block_seconds", 3600.0)),
            notify_cooldown=float(config.get("command_rate_limit_notify_cooldown_seconds", 10.0)),
        )

        self.presence = PresenceManager(self)
        for plugin_name in self.XMPP_PLUGINS:
            self.register_plugin(plugin_name)

        self.db = DatabaseManager(
            config.get("db", "bot.db"),
            task_supervisor=self.tasks,
        )
        self.bot_plugins = PluginManager(self)

        self.add_event_handler("session_start", self.on_start)
        self.add_event_handler("groupchat_message", self.on_muc_message)
        self.add_event_handler("message", self.on_private_message)


# -------------------------------------------------
# PREFLIGHT / MAIN / CLI
# -------------------------------------------------


async def preflight_check() -> int:
    """Run local startup checks without connecting to XMPP."""
    from utils.preflight import run_preflight

    return await run_preflight(config)


def _install_shutdown_signal_handlers(xmpp, loop=None) -> tuple[signal.Signals, ...]:
    """Turn SIGINT/SIGTERM into one clean asynchronous runtime shutdown."""
    loop = loop or asyncio.get_running_loop()
    installed: list[signal.Signals] = []

    def request_shutdown(sig: signal.Signals) -> None:
        if getattr(xmpp, "_signal_shutdown_requested", False):
            return
        xmpp._signal_shutdown_requested = True
        xmpp._requested_exit_code = 0
        log.info("[XMPP] Shutdown signal received: %s", sig.name)
        try:
            xmpp.disconnect()
        except Exception:
            log.exception("[XMPP] Failed to disconnect after %s", sig.name)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, request_shutdown, sig)
        except (NotImplementedError, RuntimeError, ValueError):
            continue
        installed.append(sig)
    return tuple(installed)


async def main():
    try:
        validate_startup_config(config)
    except ConfigError as e:
        exit_on_config_error(e)

    xmpp = Bot()
    await connect_xmpp(xmpp)
    loop = asyncio.get_running_loop()
    installed_signals = _install_shutdown_signal_handlers(xmpp, loop)
    log.info("[XMPP] ✅ Connected successfully. Starting event loop...")

    try:
        await xmpp.disconnected
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("[XMPP] Shutdown request")
        xmpp._requested_exit_code = 0
        xmpp.disconnect()
        try:
            await asyncio.wait_for(xmpp.disconnected, timeout=2.0)
        except asyncio.TimeoutError:
            log.warning("[XMPP] Disconnect timeout")
    finally:
        log.info("[XMPP] disconnected. Closing Database...")
        shutdown_runtime = getattr(xmpp, "shutdown_runtime", None)
        if callable(shutdown_runtime) and isinstance(xmpp, Bot):
            await shutdown_runtime()
        else:
            try:
                await xmpp.db.close()
            except Exception as e:
                log.exception("[XMPP] Error closing database: %s", e)
        for sig in installed_signals:
            with contextlib.suppress(Exception):
                loop.remove_signal_handler(sig)
        log.info("[XMPP] ✅ Database closed! End!")
    return int(getattr(xmpp, "_requested_exit_code", 1))


def copy_initial_chat_slang(
    source: str | os.PathLike[str] | None = None,
    target: str | os.PathLike[str] | None = None,
) -> None:
    """Copy the packaged chat-slang defaults into the writable runtime area."""
    source_path = Path(source) if source is not None else BASE_DIR / "init_chat_slang.csv"
    target_path = Path(target) if target is not None else chat_slang_file(config)
    if source_path.exists() and not target_path.exists():
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
            log.info("[INIT] ✅ Copied %s to %s", source_path, target_path)
        except Exception as e:
            log.error(
                "[INIT] 🔴 Failed to copy %s to %s: %s",
                source_path,
                target_path,
                e,
            )
    elif not source_path.exists():
        log.warning(
            "[INIT] 🔴 Source file %s not found. Skipping copy.",
            source_path,
        )
    else:
        log.info(
            "[INIT] ✅ Target file %s already exists. Skipping copy.",
            target_path,
        )


def cli(argv: list[str] | None = None) -> int:
    """Console-script entrypoint for runtime and local administration commands."""
    import argparse
    import sys

    arguments = list(sys.argv[1:] if argv is None else argv)

    if arguments[:1] == ["db"]:
        from utils.database_cli import (
            database_backup,
            database_check,
            database_migrate,
            database_status,
        )

        parser = argparse.ArgumentParser(prog="envsbot db")
        subparsers = parser.add_subparsers(dest="command", required=True)
        subparsers.add_parser("status", help="Show applied/pending schema migrations")
        migrate_parser = subparsers.add_parser("migrate", help="Apply pending migrations")
        migrate_parser.add_argument("--dry-run", action="store_true", help="Only list migrations")
        subparsers.add_parser("check", help="Run integrity, FK and schema checks")
        backup_parser = subparsers.add_parser("backup", help="Create a SQLite snapshot")
        backup_parser.add_argument("destination", nargs="?", help="Optional snapshot path")
        options = parser.parse_args(arguments[1:])

        async def run_db_command():
            if options.command == "status":
                return await database_status(config)
            if options.command == "migrate":
                return await database_migrate(config, dry_run=options.dry_run)
            if options.command == "check":
                return await database_check(config)
            return await database_backup(config, destination=options.destination)

        try:
            code, output = asyncio.run(run_db_command())
        except Exception as exc:
            print(f"Database command failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(output)
        return int(code)

    if arguments[:1] == ["systemd"]:
        from utils.systemd_deploy import check_systemd_installation, render_systemd_unit

        parser = argparse.ArgumentParser(prog="envsbot systemd")
        parser.add_argument("command", choices=("check", "render"))
        parser.add_argument("--user", default="envsbot", help="systemd service user")
        parser.add_argument("--group", default="envsbot", help="systemd service group")
        parser.add_argument(
            "--environment-file",
            default="/etc/default/envsbot",
            help="optional EnvironmentFile path",
        )
        options = parser.parse_args(arguments[1:])
        if options.command == "render":
            print(
                render_systemd_unit(
                    config,
                    user=options.user,
                    group=options.group,
                    environment_file=options.environment_file,
                ),
                end="",
            )
            return 0
        code, output = check_systemd_installation(
            config,
            user=options.user,
            group=options.group,
            environment_file=options.environment_file,
        )
        print(output)
        return int(code)

    copy_initial_chat_slang()
    try:
        runner = preflight_check if "--check" in arguments else main
        return int(asyncio.run(runner()) or 0)
    except KeyboardInterrupt:
        log.info("[INIT] Shutdown requested by keyboard interrupt")
        return 0


if __name__ == "__main__":
    raise SystemExit(cli())
