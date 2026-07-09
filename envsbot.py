#!/usr/bin/env python3

# envsbot: Modular XMPP Bot Framework
# Author: dan <mailto:fab@redterminal.org>
# Author: creme <mailto:creme@envs.net>
# License: GPL-3.0

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess

import slixmpp

from bot.audit import AuditMixin
from bot.connection import (
    boundjid_domain as _boundjid_domain_impl,
    build_client_jid as _build_client_jid_impl,
    configured_jid_domain as _configured_jid_domain_impl,
    connect_kwargs as _connect_kwargs_impl,
    connect_signature_parameters as _connect_signature_parameters_impl,
    connect_xmpp as _connect_xmpp_impl,
    get_configured_resource as _get_configured_resource_impl,
)
from bot.dispatch import CommandDispatchMixin
from bot.lifecycle import LifecycleMixin
from bot.messages import MessageMixin
from bot.permissions import (
    PermissionMixin,
    configured_rate_limit_bypass_role as _configured_rate_limit_bypass_role_impl,
    role_bypasses_rate_limit as _role_bypasses_rate_limit_impl,
)
from bot.routing import MessageRoutingMixin
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
from utils.plugin_manager import PluginManager
from utils.presence_manager import PresenceManager
from utils.rate_limiter import TokenBucketRateLimiter
from utils.task_supervisor import TaskSupervisor
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
# RATE LIMIT HELPERS
# -------------------------------------------------


def _configured_rate_limit_bypass_role() -> Role | None:
    """Return the configured role threshold for rate-limit bypasses."""
    return _configured_rate_limit_bypass_role_impl(config)


def _role_bypasses_rate_limit(role: Role) -> bool:
    """Return whether *role* is privileged enough to bypass command limits."""
    return _role_bypasses_rate_limit_impl(role, config)


# -------------------------------------------------
# XMPP CONNECTION HELPERS
# -------------------------------------------------


def _get_configured_resource() -> str | None:
    """Return the optional configured XMPP resource."""
    return _get_configured_resource_impl(config)


def _build_client_jid(jid, resource=None) -> str:
    """Build the login JID, optionally replacing/adding a resource."""
    return _build_client_jid_impl(jid, resource)


def _configured_jid_domain() -> str | None:
    """Return the domain part of the configured bot JID if available."""
    return _configured_jid_domain_impl(config)


def _boundjid_domain(xmpp) -> str | None:
    """Return a best-effort domain from Slixmpp's bound JID object."""
    return _boundjid_domain_impl(xmpp)


def _connect_signature_parameters(connect_method):
    """Return inspectable connect() parameters, or an empty mapping."""
    return _connect_signature_parameters_impl(connect_method)


def _connect_kwargs(xmpp) -> dict:
    """Build kwargs for xmpp.connect() without passing unsupported names."""
    return _connect_kwargs_impl(xmpp, config)


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
        self.command_executor = CommandExecutor(self)
        self._startup_backup_done = False

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

        self.db = DatabaseManager(config.get("db", "bot.db"))
        self.bot_plugins = PluginManager(self)

        self.add_event_handler("session_start", self.on_start)
        self.add_event_handler("groupchat_message", self.on_muc_message)
        self.add_event_handler("message", self.on_private_message)


# --------------------------------------------------
# GET LATEST GIT TAG (for version display)
# --------------------------------------------------


def get_latest_git_tag():
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            stderr=subprocess.STDOUT,
        ).strip().decode("utf-8")
        return tag
    except subprocess.CalledProcessError:
        return None


# -------------------------------------------------
# PREFLIGHT / MAIN / CLI
# -------------------------------------------------


async def preflight_check() -> int:
    """Run local startup checks without connecting to XMPP."""
    from utils.preflight import run_preflight

    return await run_preflight(config)


async def main():
    try:
        validate_startup_config(config)
    except ConfigError as e:
        exit_on_config_error(e)

    xmpp = Bot()
    await connect_xmpp(xmpp)
    log.info("[XMPP] ✅ Connected successfully. Starting event loop...")

    try:
        await xmpp.disconnected
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("[XMPP] Shutdown request")
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
        log.info("[XMPP] ✅ Database closed! End!")


def copy_initial_chat_slang(source="init_chat_slang.csv", target="chat_slang.csv") -> None:
    """Copy the default chat slang file into place on first startup."""
    if os.path.exists(source) and not os.path.exists(target):
        try:
            shutil.copyfile(source, target)
            log.info("[INIT] ✅ Copied %s to %s", source, target)
        except Exception as e:
            log.error("[INIT] 🔴 Failed to copy %s to %s: %s", source, target, e)
    elif not os.path.exists(source):
        log.warning("[INIT] 🔴 Source file %s not found. Skipping copy.", source)
    else:
        log.info("[INIT] ✅ Target file %s already exists. Skipping copy.", target)


def cli() -> None:
    """Console-script entrypoint for running envsbot."""
    import sys

    copy_initial_chat_slang()
    if "--check" in sys.argv:
        raise SystemExit(asyncio.run(preflight_check()))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("[INIT] Shutdown requested by keyboard interrupt")


if __name__ == "__main__":
    cli()
