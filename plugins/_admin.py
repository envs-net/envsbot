"""
Admin management commands.

This plugin exposes administrative commands for bot management,
like restart, shutdown, and status monitoring.

The bot restart command simply stops the bot, which is then restarted by
the system's service functions.

The bot shutdown command is built from the "stop_cmd" key in the config.json
like this:
"stop_cmd": ["/usr/bin/systemctl", "--user", "stop", "envsbot.service"]
(This may be different for your setup and used init system)
"""

import asyncio
import json
import logging
import os
import platform
import subprocess
from datetime import datetime
from importlib import metadata
from pathlib import Path

import psutil

from plugins._core import JOINED_ROOMS
from utils.command import COMMANDS, Role, command
from utils.config import config
from utils.audit import audit_event
from utils.task_supervisor import create_plugin_task
from utils.updatecheck import check_for_updates_once, version_check_worker
from utils.version import __version__, display_version

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "admin",
    "version": "0.2.0",
    "description": "Bot administration commands",
    "category": "core",
    "requires": ["_core"],
}

# Use a temp file to store restart notification data
RESTART_NOTIFICATION_FILE = "/tmp/bot_restart_notification.json"

# Track bot start time
BOT_START_TIME = None


# ------------------------------------------------
# Small formatting helpers
# ------------------------------------------------
def set_bot_start_time(bot):
    """Initialize bot start time tracking."""
    global BOT_START_TIME
    if BOT_START_TIME is None:
        BOT_START_TIME = datetime.now()


def human_time(seconds: int) -> str:
    """Convert seconds to human-readable string."""
    seconds = int(seconds)
    if seconds <= 0:
        return "0s"

    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)

    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")

    return " ".join(parts)


def human_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable size string."""
    if size_bytes < 0:
        return "unknown"

    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(size_bytes)

    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024

    return f"{size_bytes} B"


def _section(title: str, lines: list[str]) -> list[str]:
    """Format one status section."""
    return [f"{title}:", *[f"• {line}" for line in lines], ""]


def _package_version(package: str) -> str:
    """Return an installed package version or 'unknown'."""
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "unknown"


def _safe_config_value(key: str, default="unknown"):
    """Return a safe, non-secret config value."""
    value = config.get(key, default)
    return default if value in (None, "") else value


def _format_presence(bot) -> str:
    """Return current presence state without raising on test doubles."""
    presence = getattr(bot, "presence", None)
    status_data = getattr(presence, "status", {}) or {}
    show = status_data.get("show", "unknown")
    text = status_data.get("status", "")
    return f"{show} / {text}" if text else str(show)


def _bot_uptime_line() -> str:
    """Return bot uptime based on plugin load time."""
    if not BOT_START_TIME:
        return "Uptime: unknown"
    uptime = datetime.now() - BOT_START_TIME
    return f"Uptime: {human_time(uptime.total_seconds())}"


def _connection_line(bot) -> str:
    """Return XMPP connection uptime."""
    connection_start = getattr(bot, "connection_start_time", None)
    if not connection_start:
        return "Connection: unknown"
    try:
        uptime = datetime.now() - connection_start
        return f"Connection: {human_time(uptime.total_seconds())}"
    except Exception:
        log.debug("[ADMIN] Could not calculate connection uptime", exc_info=True)
        return "Connection: unknown"


def _command_counts() -> tuple[int, int]:
    """Return primary command and alias counts from the live registry."""
    primary_names = set()
    aliases = 0
    for tokens, cmd_obj in COMMANDS.items():
        registered_name = " ".join(tokens)
        primary_names.add(getattr(cmd_obj, "name", registered_name))
        if registered_name != getattr(cmd_obj, "name", registered_name):
            aliases += 1
    return len(primary_names), aliases


def _joined_rooms_snapshot() -> tuple[tuple[str, dict], ...]:
    """Return a stable snapshot of joined rooms for race-safe status output."""
    try:
        return tuple((str(room), dict(room_data or {}))
                     for room, room_data in JOINED_ROOMS.items())
    except Exception:
        log.debug("[ADMIN] Could not snapshot joined rooms", exc_info=True)
        return tuple()


def _room_occupant_count(room_data: dict) -> int:
    """Return occupant count from a room data snapshot."""
    nicks = room_data.get("nicks", {})
    if isinstance(nicks, dict):
        return len(tuple(nicks))
    return 0


# ------------------------------------------------
# Status helpers
# ------------------------------------------------
def _core_status_lines(bot) -> list[str]:
    """Return core bot status lines."""
    lines = [
        f"Version: {display_version(getattr(bot, 'version', __version__))}",
        f"JID: {getattr(bot, 'boundjid', 'unknown')}",
        f"Prefix: {_safe_config_value('prefix', getattr(bot, 'prefix', ','))}",
        _bot_uptime_line(),
        _connection_line(bot),
        f"Presence: {_format_presence(bot)}",
    ]

    latest = getattr(bot, "last_version_check_result", None)
    if latest:
        lines.append(f"Latest release: {display_version(latest)}")
    return lines


def _runtime_status_lines() -> list[str]:
    """Return Python and process runtime status lines."""
    lines = [
        f"Python: {platform.python_version()}",
        f"slixmpp: {_package_version('slixmpp')}",
    ]

    try:
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        lines.append(f"Memory: {human_size(memory_info.rss)}")
        lines.append(f"CPU: {process.cpu_percent(None):.1f}%")
    except Exception:
        log.debug("[ADMIN] Could not read process metrics", exc_info=True)
        lines.append("Memory: unknown")
        lines.append("CPU: unknown")

    try:
        load1, load5, load15 = psutil.getloadavg()
        lines.append(f"Load: {load1:.2f} / {load5:.2f} / {load15:.2f}")
    except Exception:
        log.debug("[ADMIN] Could not read system load", exc_info=True)
        lines.append("Load: unknown")

    return lines


def _xmpp_status_lines(bot, room_snapshot: tuple[tuple[str, dict], ...]) -> list[str]:
    """Return XMPP-related status lines."""
    joined_rooms = len(room_snapshot)
    occupants = sum(_room_occupant_count(room_data)
                    for _room, room_data in room_snapshot)
    avatar_hash = getattr(bot, "avatar_hash", None)
    vcard_path = Path(__file__).resolve().parent.parent / "vcard.py"

    return [
        f"Joined rooms: {joined_rooms}",
        f"Tracked occupants: {occupants}",
        f"Avatar: {'published' if avatar_hash else 'missing'}",
        f"vCard: {'configured' if vcard_path.exists() else 'missing'}",
    ]


def _task_summary_line(bot) -> str:
    """Return a short supervised task summary."""
    supervisor = getattr(bot, "tasks", None)
    if supervisor is None:
        return "Tasks: unavailable"
    running, failed, finished = supervisor.summary()
    if failed:
        return f"Tasks: {running} running, {failed} failed, {finished} finished"
    return f"Tasks: {running} running, {finished} finished"


def _plugin_status_lines(bot) -> list[str]:
    """Return plugin and command status lines."""
    manager = getattr(bot, "bot_plugins", None)
    loaded_plugins = getattr(manager, "plugins", {}) or {}

    try:
        available_count = len(list(manager.discover())) if manager else 0
    except Exception:
        log.debug("[ADMIN] Could not discover plugins", exc_info=True)
        available_count = "unknown"

    command_count, alias_count = _command_counts()
    return [
        f"Loaded: {len(loaded_plugins)}/{available_count}",
        f"Commands: {command_count} (+{alias_count} aliases)",
        _task_summary_line(bot),
    ]


async def _database_status_lines(bot) -> list[str]:
    """Return read-only SQLite status lines."""
    db = getattr(bot, "db", None)
    if not db:
        return ["Status: disconnected"]

    lines = ["Status: connected" if getattr(db, "conn", None) else "Status: configured"]
    db_path = getattr(db, "path", None)
    if db_path:
        path = Path(str(db_path))
        lines.append(f"Path: {path}")
        try:
            lines.append(f"Size: {human_size(path.stat().st_size)}"
                         if path.exists() else "Size: file not found")
        except OSError:
            log.debug("[ADMIN] Could not stat database file", exc_info=True)
            lines.append("Size: unknown")
    else:
        lines.append("Path: unknown")
        lines.append("Size: unknown")

    fetch_one = getattr(db, "fetch_one", None)
    if not fetch_one or not getattr(db, "conn", None):
        lines.append("Integrity: unknown")
        return lines

    try:
        row = await fetch_one("PRAGMA integrity_check")
        lines.append(f"Integrity: {row[0] if row else 'unknown'}")
    except Exception:
        log.debug("[ADMIN] Could not run database integrity check", exc_info=True)
        lines.append("Integrity: unknown")

    return lines


async def _room_feature_override_line(bot, room_snapshot) -> str:
    """Return a read-only count of modified room feature toggles."""
    try:
        from utils.room_features import list_room_features

        modified = 0
        for room_jid, _room_data in room_snapshot:
            states = await list_room_features(bot, room_jid)
            modified += sum(1 for state in states if state.modified)
        return f"Room feature overrides: {modified}"
    except Exception:
        log.debug("[ADMIN] Could not inspect room feature overrides",
                  exc_info=True)
        return "Room feature overrides: unknown"


def _room_detail_lines(room_snapshot) -> list[str]:
    """Return detailed room lines for full status."""
    if not room_snapshot:
        return ["—"]

    lines = []
    for room, room_data in sorted(room_snapshot, key=lambda item: item[0]):
        nick = room_data.get("nick") or "unknown"
        role = room_data.get("role") or "unknown"
        affiliation = room_data.get("affiliation") or "unknown"
        occupants = _room_occupant_count(room_data)
        lines.append(
            f"{room} | nick={nick} | occupants={occupants} | "
            f"affiliation={affiliation} | role={role}"
        )
    return lines


def _plugin_detail_lines(bot) -> list[str]:
    """Return detailed plugin lines for full status."""
    manager = getattr(bot, "bot_plugins", None)
    loaded_plugins = getattr(manager, "plugins", {}) or {}
    if not loaded_plugins:
        return ["—"]

    meta_cache = getattr(manager, "meta", {}) or {}
    lines = []
    for name in sorted(loaded_plugins):
        module = loaded_plugins.get(name)
        meta = meta_cache.get(name) or getattr(module, "PLUGIN_META", {}) or {}
        version = meta.get("version", "unknown")
        category = meta.get("category", "unknown")
        command_count = len(getattr(COMMANDS, "by_plugin", {}).get(name, ()))
        lines.append(
            f"{name} {version} | category={category} | commands={command_count}"
        )
    return lines


def _task_detail_lines(bot) -> list[str]:
    """Return detailed supervised task lines for full status."""
    supervisor = getattr(bot, "tasks", None)
    if supervisor is None:
        return ["unavailable"]
    tasks = supervisor.snapshot(include_done=True)
    if not tasks:
        return ["—"]
    lines = []
    for task in tasks:
        extra = f" | error={task.last_error}" if task.last_error else ""
        lines.append(
            f"{task.plugin}/{task.name} | {task.status} | "
            f"created={task.created_at}{extra}"
        )
    return lines


async def _build_status_lines(bot, *, full: bool = False) -> list[str]:
    """Build the complete status reply."""
    set_bot_start_time(bot)
    room_snapshot = _joined_rooms_snapshot()

    lines = ["🤖 EnvsBot Status", ""]
    lines.extend(_section("Core", _core_status_lines(bot)))
    lines.extend(_section("Runtime", _runtime_status_lines()))
    lines.extend(_section("XMPP", _xmpp_status_lines(bot, room_snapshot)))

    plugin_lines = _plugin_status_lines(bot)
    plugin_lines.append(await _room_feature_override_line(bot, room_snapshot))
    lines.extend(_section("Plugins", plugin_lines))
    lines.extend(_section("Database", await _database_status_lines(bot)))

    if full:
        lines.extend(_section("Rooms", _room_detail_lines(room_snapshot)))
        lines.extend(_section("Loaded plugins", _plugin_detail_lines(bot)))
        lines.extend(_section("Background tasks", _task_detail_lines(bot)))

    return lines[:-1] if lines and lines[-1] == "" else lines


def _invalid_status_args(args: list[str]) -> bool:
    """Return True if bot status arguments are unsupported."""
    return bool(args) and str(args[0]).lower() not in {"full", "all", "details"}


def _status_is_full(args: list[str]) -> bool:
    """Return True if full status output was requested."""
    return bool(args) and str(args[0]).lower() in {"full", "all", "details"}


def _reply_status_usage(bot, msg):
    """Reply with status usage, supporting older test doubles."""
    usage = "{prefix}bot status [full]".format(prefix=config.get("prefix", ","))
    if hasattr(bot, "reply_usage"):
        bot.reply_usage(msg, usage)
    else:
        bot.reply(msg, f"Usage: {usage}")


# --------------
# ADMIN COMMANDS
# --------------
@command("bot restart", role=Role.OWNER, aliases=["restart"])
async def bot_restart(bot, sender, nick, args, msg, is_room):
    """
    Restart the entire bot process.

    Gracefully disconnects, closes the database, and restarts the bot
    using the system's service functionality.

    Usage:
        {prefix}bot restart
    """
    bot.reply(msg, "🔄 Bot restarting...")
    log.info("[ADMIN] 🔄 Bot restart requested by %s", sender)
    await audit_event(bot, "bot_restart", actor=sender, target="bot")

    # Wait a moment to ensure the reply is sent
    await asyncio.sleep(0.5)

    # Initiate graceful shutdown
    log.info("[ADMIN] Initiating graceful shutdown...")
    bot.disconnect()

    # Store restart notification info to file
    notification_data = {
        "sender": str(sender),
        "sender_bare":
            str(sender.bare) if hasattr(sender, "bare") else str(sender),
        "nick": nick,
        "room":
            str(msg["from"].bare) if msg.get("type") == "groupchat" else None,
        "is_room": is_room,
    }

    try:
        with open(RESTART_NOTIFICATION_FILE, "w") as f:
            json.dump(notification_data, f)
        log.info(
            "[ADMIN] Restart notification saved to %s",
            RESTART_NOTIFICATION_FILE
        )
    except Exception as e:
        log.error("[ADMIN] Failed to save restart notification: %s", e)

    # Wait for disconnect with timeout
    try:
        await asyncio.wait_for(bot.disconnected, timeout=5)
    except asyncio.TimeoutError:
        log.warning(
            "[ADMIN] Disconnect timeout - proceeding with restart anyway")

    # Close database
    try:
        await bot.db.close()
    except Exception as e:
        log.error("[ADMIN] Error closing database: %s", e)


@command("bot shutdown", role=Role.OWNER, aliases=["shutdown"])
async def bot_shutdown(bot, sender, nick, args, msg, is_room):
    """
    Gracefully shutdown the bot.

    Shuts down the bot using the "stop_cmd" list from the config file
    which builds the shutdown system command, for example:
    ["/usr/bin/systemctl", "--user", "stop", "envsbot.service"]
    (This may be different for your setup and used system init system)

    Usage:
        {prefix}bot shutdown
    """
    try:
        stop_cmd = config["stop_cmd"]
        if not stop_cmd:
            raise KeyError
    except KeyError:
        bot.reply(msg, "🛑 No shutdown command provided in config file!")
        log.info("[ADMIN] 🛑 Shutdown request failed. No shutdown command"
                 " in config file provided.")
        return
    bot.reply(msg, "🛑 Bot shutting down...")
    log.info("[ADMIN] 🛑 Bot shutdown requested by %s", sender)
    await audit_event(bot, "bot_shutdown", actor=sender, target="bot")

    subprocess.run(stop_cmd)


@command("bot version", role=Role.USER, aliases=["version"])
async def bot_version(bot, sender, nick, args, msg, is_room):
    """Show local and latest release version information.

    Usage:
        {prefix}bot version
        {prefix}version
    """
    latest = getattr(bot, "last_version_check_result", None)
    enabled = bool(config.get("version_check_enabled", False))
    release_url = config.get(
        "version_check_url",
        "https://github.com/envs-net/envsbot/releases/latest",
    )

    lines = [
        "🏷️ EnvsBot Version",
        "",
        f"Current: {display_version(getattr(bot, 'version', __version__))}",
        f"Latest release: {display_version(latest) if latest else 'unknown'}",
        f"Update check: {'enabled' if enabled else 'disabled'}",
        f"Release page: {release_url}",
    ]
    bot.reply(msg, lines, no_store=False)


@command(
    "bot checkupdate",
    role=Role.ADMIN,
    aliases=["checkupdate", "updatecheck", "bot updatecheck"],
)
async def bot_checkupdate(bot, sender, nick, args, msg, is_room):
    """Check whether a newer EnvsBot release is available.

    Usage:
        {prefix}bot checkupdate
        {prefix}checkupdate
        {prefix}updatecheck
    """
    available, remote_version, error = await check_for_updates_once(
        bot, announce=False, require_enabled=False
    )
    if error:
        bot.reply_warn(msg, f"Update check failed: {error}")
        return

    current = display_version(getattr(bot, "version", __version__))
    remote = display_version(remote_version)
    release_url = config.get(
        "version_check_url",
        "https://github.com/envs-net/envsbot/releases/latest",
    )
    if available:
        bot.reply(msg, [
            f"⬆️ New EnvsBot version available: {remote}",
            f"Current version: {current}",
            f"Release page: {release_url}",
        ], no_store=False)
    else:
        bot.reply_ok(
            msg,
            f"EnvsBot is up to date ({current}; latest: {remote}).",
            no_store=False,
        )


@command("bot status", role=Role.ADMIN, aliases=["bot info", "status"])
async def bot_status(bot, sender, nick, args, msg, is_room):
    """
    Display current bot status and statistics.

    Shows core runtime details, XMPP room state, loaded plugins, command
    counts and read-only database status. Use ``full`` for room and plugin
    details.

    Usage:
        {prefix}bot status [full]
        {prefix}status [full]
    """
    try:
        if _invalid_status_args(args):
            _reply_status_usage(bot, msg)
            return
        bot.reply(
            msg,
            await _build_status_lines(bot, full=_status_is_full(args)),
            no_store=False,
        )
    except Exception:
        log.exception("[ADMIN] Error getting bot status")
        if hasattr(bot, "reply_error"):
            bot.reply_error(msg, "Failed to retrieve bot status")
        else:
            bot.reply(msg, "❌ Failed to retrieve bot status")


async def on_load(bot):
    """Initialize admin plugin."""
    set_bot_start_time(bot)
    log.info("[ADMIN] Admin plugin loaded")


async def on_ready(bot):
    """Start optional admin background workers."""
    if not config.get("version_check_enabled", False):
        return
    existing = getattr(bot, "version_check_task", None)
    if existing is not None and not existing.done():
        return
    bot.version_check_task = create_plugin_task(
        bot,
        "_admin",
        version_check_worker(bot),
        name="version-check",
    )
    log.info("[ADMIN] Version check worker started")
