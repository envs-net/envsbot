"""
Admin management commands.

This plugin exposes administrative commands for bot management,
like restart, shutdown, and status monitoring.

The restart and shutdown commands disconnect gracefully. A systemd unit using
``Restart=on-failure`` restarts the dedicated restart exit code but leaves a
clean shutdown stopped. Operators may optionally configure ``STOP_CMD`` as an
external service-manager override.
"""

import asyncio
import json
import logging
import os
import platform
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import psutil

from bot.lifecycle import _restart_notification_paths
from bot.room_state import direct_roster_contacts
from core_plugins._core import JOINED_ROOMS
from utils.audit import audit_event
from utils.command import COMMANDS, Role, command
from utils.config import config
from utils.file_security import PRIVATE_FILE_MODE
from utils.health import HealthSnapshot, collect_health_snapshot
from utils.runtime_paths import vcard_file
from utils.task_display import render_task_lines
from utils.task_supervisor import create_resilient_plugin_task
from utils.time_utils import ensure_utc, utc_now
from utils.updatecheck import check_for_updates_once, version_check_worker
from utils.version import __version__, display_version

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "_admin",
    "version": "0.2.1",
    "description": "Bot administration commands",
    "category": "core",
    "requires": ["_core"],
}

# Track bot start time
BOT_START_TIME = None

_STATUS_ROOM_PROBLEM_LIMIT = 10


# ------------------------------------------------
# Small formatting helpers
# ------------------------------------------------
def set_bot_start_time(bot):
    """Initialize bot start time tracking."""
    global BOT_START_TIME
    if BOT_START_TIME is None:
        BOT_START_TIME = utc_now()


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


_STATUS_SECTION_ICONS = {
    "Core": "⚙️",
    "Runtime": "🖥️",
    "XMPP": "💬",
    "Plugins": "🧩",
    "Database": "🗄️",
    "Room issues": "🏠",
    "Loaded plugins": "📦",
    "Background tasks": "⏱️",
    "Health": "🩺",
    "Caches": "🧠",
}


def _section(title: str, lines: list[str]) -> list[str]:
    """Format one visually structured status section."""
    icon = _STATUS_SECTION_ICONS.get(title, "•")
    body = []
    for index, line in enumerate(lines):
        marker = "└─" if index == len(lines) - 1 else "├─"
        body.append(f"{marker} {line}")
    return [f"{icon} {title}:", *body, ""]


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
    uptime = utc_now() - ensure_utc(BOT_START_TIME, assume_tz=None)
    return f"Uptime: {human_time(int(uptime.total_seconds()))}"


def _connection_line(bot) -> str:
    """Return XMPP connection uptime."""
    connection_start = getattr(bot, "connection_start_time", None)
    if not connection_start:
        return "Connection: unknown"
    try:
        if connection_start.tzinfo is None:
            connection_start = connection_start.astimezone()
        uptime = utc_now() - connection_start.astimezone(UTC)
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
    ]

    latest = getattr(bot, "last_version_check_result", None)
    if latest:
        lines.append(f"Latest release: {display_version(latest)}")

    lines.extend([
        f"JID: {getattr(bot, 'boundjid', 'unknown')}",
        f"Prefix: {_safe_config_value('prefix', getattr(bot, 'prefix', ','))}",
        _bot_uptime_line(),
        _connection_line(bot),
        f"Presence: {_format_presence(bot)}",
    ])
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


async def _stored_rooms_snapshot(bot) -> tuple:
    """Return stored room rows for status-only roster filtering."""
    rooms_manager = getattr(getattr(bot, "db", None), "rooms", None)
    list_rooms = getattr(rooms_manager, "list", None)
    if not callable(list_rooms):
        return tuple()
    try:
        return tuple(await list_rooms())
    except Exception:
        log.debug("[ADMIN] Could not load stored rooms for status", exc_info=True)
        return tuple()


def _direct_contact_count(bot, stored_rooms=()) -> int | None:
    """Return the filtered 1:1 roster count, or None when unavailable."""
    try:
        return len(direct_roster_contacts(bot, stored_rooms))
    except Exception:
        log.debug("[ADMIN] Could not count direct roster contacts", exc_info=True)
        return None


def _xmpp_status_lines(
    bot,
    room_snapshot: tuple[tuple[str, dict], ...],
    stored_rooms=(),
) -> list[str]:
    """Return XMPP-related status lines."""
    joined_rooms = len(room_snapshot)
    direct_contacts = _direct_contact_count(bot, stored_rooms)
    muc_label = f"{joined_rooms} joined MUC{'s' if joined_rooms != 1 else ''}"
    if direct_contacts is None:
        direct_label = "unknown direct contacts (1:1/DM)"
    else:
        direct_label = (
            f"{direct_contacts} direct "
            f"contact{'s' if direct_contacts != 1 else ''} (1:1/DM)"
        )
    occupants = sum(_room_occupant_count(room_data)
                    for _room, room_data in room_snapshot)
    avatar_hash = getattr(bot, "avatar_hash", None)
    vcard_path = vcard_file(config)

    return [
        f"Rooms: {muc_label} · {direct_label}",
        f"Occupants: {occupants} tracked",
        f"Avatar: {'published' if avatar_hash else 'missing'}",
        f"vCard: {'configured' if vcard_path.exists() else 'missing'}",
    ]


def _task_summary_line(bot) -> str:
    """Return a short supervised task summary."""
    supervisor = getattr(bot, "tasks", None)
    if supervisor is None:
        return "Tasks: unavailable"
    details = getattr(supervisor, "summary_by_kind", None)
    if callable(details):
        counts = details()
        text = (
            f"Tasks: {counts.get('services_running', 0)} services running, "
            f"{counts.get('one_shots_running', 0)} one-shots running, "
            f"{counts.get('one_shots_completed', 0)} one-shots completed, "
            f"{counts.get('failed', 0)} failed"
        )
        service_finished = int(counts.get("services_finished", 0) or 0)
        if service_finished:
            text += f", {service_finished} services finished unexpectedly"
        return text
    running, failed, finished = supervisor.summary()
    if failed:
        return f"Tasks: {running} running, {failed} failed, {finished} finished"
    return f"Tasks: {running} running, {finished} finished"


def _message_cache_stats(bot) -> dict:
    """Return message-cache diagnostics without exposing cached content."""
    cache = getattr(bot, "message_cache", None)
    stats = getattr(cache, "stats", None)
    if not callable(stats):
        return {}
    try:
        return dict(stats() or {})
    except Exception:
        log.debug("[ADMIN] Could not read message-cache stats", exc_info=True)
        return {}


async def _outbox_runtime_state(bot) -> dict:
    """Return the persistent-outbox runtime state without failing status."""
    outbox = getattr(bot, "outbox", None)
    runtime_state = getattr(outbox, "runtime_state", None)
    if not callable(runtime_state):
        return {}
    try:
        return dict(await runtime_state() or {})
    except Exception:
        log.debug("[ADMIN] Could not read outbox runtime state", exc_info=True)
        return {}


def _alert_runtime_state(bot) -> dict:
    """Return immediate-alert state without making status depend on it."""
    alerts = getattr(bot, "alerts", None)
    runtime_state = getattr(alerts, "runtime_state", None)
    if not callable(runtime_state):
        return {}
    try:
        return dict(runtime_state() or {})
    except Exception:
        log.debug("[ADMIN] Could not read admin-alert runtime state", exc_info=True)
        return {}


async def _health_status_lines(
    bot,
    health: HealthSnapshot | None = None,
) -> list[str]:
    """Return compact shared operational health for the normal status view."""
    shared = health or await collect_health_snapshot(bot, verify_backup=False)
    alerts = shared.check("alerts")
    outbox = shared.check("outbox")
    cache = shared.check("message_cache")

    active_alerts = int(alerts.data.get("active", 0) or 0)
    if active_alerts:
        overall = f"Overall: ⚠️ {active_alerts} active alert{'s' if active_alerts != 1 else ''}"
    elif shared.needs_attention:
        problems = [
            key for key in shared.problem_keys
            if key not in {"alerts"}
        ]
        detail = f" ({', '.join(problems[:4])})" if problems else ""
        overall = f"Overall: ⚠️ attention required{detail}"
    else:
        overall = "Overall: ✅ OK"

    if outbox.status != "unknown":
        outbox_line = (
            f"Outbox: {int(outbox.data.get('pending', 0) or 0)} pending · "
            f"{int(outbox.data.get('dead', 0) or 0)} dead"
        )
    else:
        outbox_line = "Outbox: unavailable"

    if cache.status != "unknown":
        state = cache.data
        persistence = "persistent" if state.get("persistent") else "memory-only"
        cache_health = "degraded" if cache.needs_attention else "healthy"
        cache_line = (
            f"Message cache: {int(state.get('messages', 0) or 0)} messages · "
            f"{persistence} · {cache_health}"
        )
    else:
        cache_line = "Message cache: unavailable"

    return [overall, outbox_line, cache_line]


def _cache_detail_lines(bot, health: HealthSnapshot | None = None) -> list[str]:
    """Return bounded user/runtime cache and message-cache diagnostics."""
    lines: list[str] = []
    users = getattr(getattr(bot, "db", None), "users", None)
    cache_state = getattr(users, "cache_state", None)
    if callable(cache_state):
        try:
            state = dict(cache_state() or {})
        except Exception:
            log.debug("[ADMIN] Could not read user-cache state", exc_info=True)
            state = {}
        if state:
            lines.extend([
                (
                    f"Users: {int(state.get('users', 0) or 0)}/"
                    f"{int(state.get('user_limit', 0) or 0)} · "
                    f"dirty={int(state.get('dirty_users', 0) or 0)} · "
                    f"evicted={int(state.get('evicted_users', 0) or 0)}"
                ),
                (
                    f"Runtime: {int(state.get('runtime', 0) or 0)}/"
                    f"{int(state.get('runtime_limit', 0) or 0)} · "
                    f"dirty={int(state.get('dirty_runtime', 0) or 0)} · "
                    f"evicted={int(state.get('evicted_runtime', 0) or 0)}"
                ),
            ])
    if not lines:
        lines.extend(["Users: unavailable", "Runtime: unavailable"])

    cache_check = health.check("message_cache") if health is not None else None
    cache = cache_check.data if cache_check is not None else _message_cache_stats(bot)
    if cache:
        persistence = "persistent" if cache.get("persistent") else "memory-only"
        cache_health = (
            "degraded"
            if (cache_check.needs_attention if cache_check is not None else cache.get("degraded"))
            else "healthy"
        )
        lines.append(
            f"Message cache: {int(cache.get('messages', 0) or 0)} messages · "
            f"pending={int(cache.get('pending_writes', 0) or 0)} · "
            f"retry={int(cache.get('retry_backlog', 0) or 0)} · "
            f"dropped={int(cache.get('dropped_persistence_entries', 0) or 0)} · "
            f"{persistence} · {cache_health}"
        )
    else:
        lines.append("Message cache: unavailable")

    limiter = getattr(bot, "rate_limiter", None)
    runtime_state = getattr(limiter, "runtime_state", None)
    if callable(runtime_state):
        try:
            state = dict(runtime_state() or {})
            lines.append(
                f"Rate limiter: {int(state.get('clients', 0) or 0)}/"
                f"{int(state.get('max_clients', 0) or 0)} clients · "
                f"blocked={int(state.get('blocked_clients', 0) or 0)} · "
                f"evicted={int(state.get('capacity_evictions', 0) or 0)} · "
                f"pruned={int(state.get('stale_pruned', 0) or 0)}"
            )
        except Exception:
            log.debug("[ADMIN] Could not read rate-limiter state", exc_info=True)
    return lines


def _plugin_status_lines(bot, *, include_task_summary: bool = True) -> list[str]:
    """Return plugin and command status lines."""
    manager = getattr(bot, "bot_plugins", None)
    loaded_plugins = getattr(manager, "plugins", {}) or {}

    try:
        available_count: int | str = len(list(manager.discover())) if manager else 0
    except Exception:
        log.debug("[ADMIN] Could not discover plugins", exc_info=True)
        available_count = "unknown"

    command_count, alias_count = _command_counts()
    lines = [
        f"Loaded: {len(loaded_plugins)}/{available_count}",
        f"Commands: {command_count} (+{alias_count} aliases)",
    ]
    if include_task_summary:
        lines.append(_task_summary_line(bot))
    return lines


async def _database_status_lines(bot, *, full: bool = False) -> list[str]:
    """Return read-only SQLite status lines.

    The compact status output includes safe online database checks. ``full``
    adds page-level SQLite details for operators who need a little more
    context.
    """
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
        if full:
            lines.extend([
                "Page count: unknown",
                "Page size: unknown",
                "Freelist pages: unknown",
            ])
        return lines

    try:
        row = await fetch_one("PRAGMA integrity_check")
        lines.append(f"Integrity: {row[0] if row else 'unknown'}")
    except Exception:
        log.debug("[ADMIN] Could not run database integrity check", exc_info=True)
        lines.append("Integrity: unknown")

    if not full:
        return lines

    for label, pragma in (
        ("Page count", "PRAGMA page_count"),
        ("Page size", "PRAGMA page_size"),
        ("Freelist pages", "PRAGMA freelist_count"),
    ):
        try:
            row = await fetch_one(pragma)
            value = row[0] if row else "unknown"
        except Exception:
            log.debug("[ADMIN] Could not run %s", pragma, exc_info=True)
            value = "unknown"
        lines.append(f"{label}: {value}")

    list_migrations = getattr(db, "list_migrations", None)
    if callable(list_migrations):
        try:
            rows = await list_migrations()
            versions = [str(row["version"]) for row in rows]
            lines.append(
                "Migrations: " + (", ".join(versions) if versions else "none")
            )
        except Exception:
            log.debug("[ADMIN] Could not list schema migrations", exc_info=True)
            lines.append("Migrations: unknown")

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


def _room_problem_lines(
    bot,
    room_snapshot: tuple[tuple[str, dict], ...],
    health: HealthSnapshot,
) -> list[str]:
    """Return a bounded list of room-state problems for full status.

    Healthy rooms are deliberately omitted.  ``rooms list all`` owns the full
    inventory; status only surfaces room state that may need operator action.
    """
    problems: dict[str, list[str]] = {}

    def add_problem(room: str, detail: str) -> None:
        room = str(room)
        if not room:
            return
        details = problems.setdefault(room, [])
        if detail not in details:
            details.append(detail)

    room_check = health.check("rooms")
    for room in room_check.data.get("missing", ()) or ():
        add_problem(str(room), "autojoin room is not joined")

    core_rooms = {str(room): data for room, data in room_snapshot}
    presence_raw = getattr(getattr(bot, "presence", None), "joined_rooms", {}) or {}
    if hasattr(presence_raw, "items"):
        presence_rooms = {str(room): nick for room, nick in presence_raw.items()}
    else:
        presence_rooms = {str(room): None for room in presence_raw}

    for room in sorted(set(core_rooms) - set(presence_rooms), key=str.casefold):
        add_problem(room, "presence routing state is missing")
    for room in sorted(set(presence_rooms) - set(core_rooms), key=str.casefold):
        add_problem(room, "core room state is missing")
    for room in sorted(set(core_rooms) & set(presence_rooms), key=str.casefold):
        runtime_nick = str(core_rooms[room].get("nick") or "")
        presence_nick = str(presence_rooms[room] or "")
        if runtime_nick and presence_nick and runtime_nick != presence_nick:
            add_problem(
                room,
                f"presence nick differs from runtime nick ({presence_nick} != {runtime_nick})",
            )

    if not problems:
        return []

    rooms = sorted(problems, key=str.casefold)
    lines = [
        f"⚠️ {room} | {'; '.join(problems[room])}"
        for room in rooms[:_STATUS_ROOM_PROBLEM_LIMIT]
    ]
    hidden = len(rooms) - _STATUS_ROOM_PROBLEM_LIMIT
    if hidden > 0:
        prefix = getattr(bot, "prefix", None) or _safe_config_value("prefix", ",")
        lines.append(
            f"… {hidden} more room problem{'s' if hidden != 1 else ''}; "
            f"see {prefix}rooms list all"
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


def _timestamp_age(value: str | None) -> str:
    """Return a compact age for an ISO timestamp used in task diagnostics."""
    if not value:
        return "not reported"
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        age = (utc_now() - parsed.astimezone(UTC)).total_seconds()
        return f"{human_time(int(max(0, age)))} ago"
    except (TypeError, ValueError):
        return "unknown"


def _task_status_lines(bot) -> list[str]:
    """Return the same compact supervised-task inventory as ``tasks all``."""
    supervisor = getattr(bot, "tasks", None)
    if supervisor is None:
        return ["Task supervisor is not available."]
    tasks = supervisor.snapshot(include_done=True)
    return [line for line in render_task_lines(tasks, full=False) if line]


async def _build_status_lines(bot, *, full: bool = False) -> list[str]:
    """Build the complete status reply."""
    set_bot_start_time(bot)
    room_snapshot = _joined_rooms_snapshot()
    stored_rooms = await _stored_rooms_snapshot(bot)
    health = await collect_health_snapshot(bot, verify_backup=False)

    lines = ["🤖 EnvsBot Status", ""]
    lines.extend(_section("Core", _core_status_lines(bot)))
    lines.extend(_section("Runtime", _runtime_status_lines()))
    lines.extend(
        _section("XMPP", _xmpp_status_lines(bot, room_snapshot, stored_rooms))
    )

    plugin_lines = _plugin_status_lines(bot, include_task_summary=not full)
    plugin_lines.append(await _room_feature_override_line(bot, room_snapshot))
    lines.extend(_section("Plugins", plugin_lines))
    lines.extend(_section("Database", await _database_status_lines(bot, full=full)))
    lines.extend(_section("Health", await _health_status_lines(bot, health=health)))

    if full:
        room_problems = _room_problem_lines(bot, room_snapshot, health)
        if room_problems:
            lines.extend(_section("Room issues", room_problems))
        lines.extend(_section("Loaded plugins", _plugin_detail_lines(bot)))
        lines.extend(_section("Caches", _cache_detail_lines(bot, health=health)))
        lines.extend(_section("Background tasks", _task_status_lines(bot)))

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


def _write_private_json(path: Path, payload: dict) -> None:
    """Atomically write a small owner-only runtime JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    tmp = Path(tmp_name)
    try:
        os.chmod(tmp, PRIVATE_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        os.chmod(path, PRIVATE_FILE_MODE)
    except Exception:
        with suppress(OSError):
            os.close(fd)
        tmp.unlink(missing_ok=True)
        raise


async def _run_stop_command(stop_cmd: list[str], timeout: float) -> tuple[int, str]:
    """Run an optional service-manager command without blocking the event loop."""
    if not stop_cmd or not all(isinstance(item, str) and item for item in stop_cmd):
        raise ValueError("stop_cmd must be a non-empty list of arguments")
    process = await asyncio.create_subprocess_exec(
        *stop_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise
    detail = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()
    return int(process.returncode or 0), detail[:300]


async def _graceful_command_shutdown(bot, *, exit_code: int) -> None:
    """Disconnect and drain runtime state for an operator-requested exit."""
    bot._requested_exit_code = int(exit_code)
    bot.disconnect()
    disconnected = getattr(bot, "disconnected", None)
    if disconnected is not None:
        try:
            await asyncio.wait_for(disconnected, timeout=5)
        except TimeoutError:
            log.warning("[ADMIN] Disconnect timeout during requested shutdown")

    shutdown_runtime = getattr(bot, "shutdown_runtime", None)
    if callable(shutdown_runtime):
        await shutdown_runtime()
        return

    message_cache = getattr(bot, "message_cache", None)
    close_cache = getattr(message_cache, "close", None)
    if callable(close_cache):
        await close_cache()
    close_db = getattr(getattr(bot, "db", None), "close", None)
    if callable(close_db):
        await close_db()


# --------------
# ADMIN COMMANDS
# --------------
@command(
    "bot restart",
    role=Role.OWNER,
    aliases=["restart"],
    short="Restart the bot process gracefully.",
    usage="{prefix}bot restart",
    examples=["{prefix}bot restart"],
    category="admin",
    context="private chat / MUC PM",
)
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

    # Store restart notification before disconnecting so the main shutdown
    # path cannot race ahead of the persistent confirmation metadata.
    notification_data = {
        "sender": str(sender),
        "sender_bare":
            str(sender.bare) if hasattr(sender, "bare") else str(sender),
        "nick": nick,
        "room":
            str(msg["from"].bare) if msg.get("type") == "groupchat" else None,
        "is_room": is_room,
    }

    saved_paths: list[str] = []
    for path in _restart_notification_paths(config):
        try:
            notification_path = Path(path)
            await asyncio.to_thread(
                _write_private_json,
                notification_path,
                notification_data,
            )
            saved_paths.append(str(notification_path))
        except Exception as e:
            log.warning("[ADMIN] Failed to save restart notification to %s: %s", path, e)
    if saved_paths:
        log.info("[ADMIN] Restart notification saved to %s", ", ".join(saved_paths))
    else:
        log.error("[ADMIN] Failed to save restart notification to any configured path")

    # Exit 75 is deliberately non-zero so a Restart=on-failure systemd unit
    # starts the process again.
    log.info("[ADMIN] Initiating graceful restart...")
    try:
        await _graceful_command_shutdown(bot, exit_code=75)
    except Exception:
        log.exception("[ADMIN] Error during graceful restart")


@command(
    "bot shutdown",
    role=Role.OWNER,
    aliases=["shutdown"],
    short="Stop the bot gracefully, optionally using a configured command.",
    usage="{prefix}bot shutdown",
    examples=["{prefix}bot shutdown"],
    category="admin",
    context="private chat / MUC PM",
)
async def bot_shutdown(bot, sender, nick, args, msg, is_room):
    """
    Gracefully shutdown the bot.

    Without ``STOP_CMD`` the process exits cleanly after flushing runtime
    state. An optional ``STOP_CMD`` may be configured for installations that
    require an external service-manager command.

    Usage:
        {prefix}bot shutdown
    """
    stop_cmd = config.get("stop_cmd") or []
    timeout = max(1.0, float(config.get("stop_cmd_timeout_seconds", 10) or 10))

    bot.reply(msg, "🛑 Bot shutting down...")
    log.info("[ADMIN] 🛑 Bot shutdown requested by %s", sender)
    await audit_event(bot, "bot_shutdown", actor=sender, target="bot")
    await asyncio.sleep(0.5)

    if stop_cmd:
        try:
            returncode, detail = await _run_stop_command(list(stop_cmd), timeout)
        except TimeoutError:
            bot.reply(msg, f"🔴 Shutdown command timed out after {timeout:g}s.")
            log.error("[ADMIN] Shutdown command timed out after %.1fs", timeout)
            return
        except Exception as exc:
            bot.reply(msg, f"🔴 Shutdown command failed to start: {type(exc).__name__}.")
            log.exception("[ADMIN] Shutdown command failed to start")
            return
        if returncode != 0:
            suffix = f": {detail}" if detail else ""
            bot.reply(msg, f"🔴 Shutdown command exited with {returncode}{suffix}")
            log.error("[ADMIN] Shutdown command exited with %d: %s", returncode, detail)
            return
        # If the external command returns before the service manager has
        # terminated us, still drain and exit cleanly ourselves.
        await _graceful_command_shutdown(bot, exit_code=0)
        return

    try:
        await _graceful_command_shutdown(bot, exit_code=0)
    except Exception:
        log.exception("[ADMIN] Graceful shutdown failed")
        bot.reply(msg, "🔴 Graceful shutdown failed; check the bot log.")


@command(
    "bot version",
    role=Role.USER,
    aliases=["version"],
    short="Show the running EnvsBot version and latest checked release.",
    usage="{prefix}bot version",
    examples=[
        "{prefix}bot version",
        "{prefix}version",
    ],
    category="core",
    context="any",
)
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
    short="Check whether a newer EnvsBot release is available.",
    usage="{prefix}bot checkupdate",
    examples=[
        "{prefix}bot checkupdate",
        "{prefix}checkupdate",
        "{prefix}updatecheck",
    ],
    category="admin",
    context="private chat / MUC PM",
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


@command(
    "bot status",
    role=Role.ADMIN,
    aliases=["bot info", "status"],
    short="Show bot, runtime, XMPP rooms/direct contacts, plugin and database status.",
    usage="{prefix}bot status [full]",
    examples=[
        "{prefix}bot status",
        "{prefix}status",
        "{prefix}bot status full",
    ],
    category="admin",
    context="private chat / MUC PM",
)
async def bot_status(bot, sender, nick, args, msg, is_room):
    """
    Display current bot status and statistics.

    Shows core runtime details, XMPP room state, loaded plugins, command
    counts, read-only database status and compact operational health. Use
    ``full`` for detailed database, problematic-room, plugin, task and cache
    diagnostics. Healthy room inventory belongs to ``rooms list all``.

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
    bot.version_check_task = create_resilient_plugin_task(
        bot,
        "_admin",
        lambda: version_check_worker(bot),
        name="version-check",
    )
    log.info("[ADMIN] Version check worker started")


async def restart_tasks(bot):
    """Resynchronize optional admin workers after a live config reload."""
    bot.version_check_task = None
    await on_ready(bot)
