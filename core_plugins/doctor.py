"""Operator health checks and diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from utils.backups import backup_dir, backup_keep, backup_retention_days, list_backups
from utils.command import COMMANDS, Role, command
from utils.config import config, get_runtime_config_path
from utils.formatting import format_page, parse_page_args

PLUGIN_META = {
    "name": "doctor",
    "version": "0.2.0",
    "description": "Operator health checks and runtime diagnostics.",
    "category": "core",
}

_PLUGIN_HEALTH_PLUGINS = (
    "rss",
    "idlerpg",
    "reminder",
    "pin",
    "weather",
    "urlcheck",
    "birthday_notify",
    "ducks",
    "tell",
    "karma",
)

_SECTION_ALIASES = {
    "all": "all",
    "full": "all",
    "details": "all",
    "config": "config",
    "db": "database",
    "database": "database",
    "rooms": "rooms",
    "room": "rooms",
    "plugins": "plugins",
    "plugin": "plugins",
    "tasks": "tasks",
    "task": "tasks",
    "backups": "backups",
    "backup": "backups",
    "network": "network",
    "http": "network",
    "plugin-health": "plugin-health",
    "pluginhealth": "plugin-health",
    "health": "plugin-health",
    "rss": "plugin:rss",
    "idlerpg": "plugin:idlerpg",
    "irpg": "plugin:idlerpg",
    "reminder": "plugin:reminder",
    "pin": "plugin:pin",
    "weather": "plugin:weather",
    "urlcheck": "plugin:urlcheck",
    "birthday": "plugin:birthday_notify",
    "birthday_notify": "plugin:birthday_notify",
    "ducks": "plugin:ducks",
    "tell": "plugin:tell",
    "karma": "plugin:karma",
}
_DEFAULT_SECTIONS = (
    "config",
    "database",
    "rooms",
    "plugins",
    "tasks",
    "backups",
    "plugin-health",
)
_ALL_SECTIONS = _DEFAULT_SECTIONS + ("network",)


def _line(ok: bool | None, label: str, text: str) -> str:
    icon = "✅" if ok is True else "🔴" if ok is False else "ℹ️"
    return f"{icon} {label}: {text}"


def _migration_version(value: Any) -> str:
    """Return a readable migration version from strings, tuples or sqlite rows."""
    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        for key in ("version", "name", "id"):
            if key in value:
                return str(value[key])
        return str(value)

    for key in ("version", "name", "id"):
        try:
            item = value[key]
        except Exception:
            continue
        return str(item)

    try:
        return str(value[0])
    except Exception:
        return str(value)


async def _db_lines(bot: Any) -> list[str]:
    db = getattr(bot, "db", None)
    conn = getattr(db, "conn", None)
    if conn is None:
        return [_line(False, "Database", "not connected")]

    lines = [_line(True, "Database", "connected")]
    try:
        cursor = await conn.execute("SELECT 1")
        row = await cursor.fetchone()
        lines.append(_line(row is not None, "Database query", "SELECT 1 ok"))
    except Exception as exc:
        lines.append(_line(False, "Database query", str(exc)))

    integrity = getattr(db, "integrity_check", None)
    if callable(integrity):
        try:
            result = list(await integrity())
            ok = result == ["ok"] or result == []
            lines.append(_line(ok, "Integrity check", ", ".join(result) if result else "ok"))
        except Exception as exc:
            lines.append(_line(False, "Integrity check", str(exc)))

    list_migrations = getattr(db, "list_migrations", None)
    if callable(list_migrations):
        try:
            applied = [
                _migration_version(item)
                for item in list(await list_migrations())
            ]
            lines.append(
                _line(
                    True,
                    "Migrations",
                    ", ".join(applied) if applied else "none applied",
                )
            )
        except Exception as exc:
            lines.append(_line(False, "Migrations", str(exc)))
    return lines


async def _room_lines(bot: Any, *, full: bool) -> list[str]:
    try:
        from core_plugins.rooms import JOINED_ROOMS
    except Exception:
        JOINED_ROOMS = {}

    db_rooms = []
    rooms_manager = getattr(getattr(bot, "db", None), "rooms", None)
    list_rooms = getattr(rooms_manager, "list", None)
    if callable(list_rooms):
        try:
            db_rooms = list(await list_rooms())
        except Exception as exc:
            return [_line(False, "Rooms", f"DB list failed: {exc}")]

    presence_rooms = set(getattr(getattr(bot, "presence", None), "joined_rooms", {}) or {})
    joined_rooms = set(JOINED_ROOMS) | presence_rooms
    autojoin_rooms = {str(row[0]) for row in db_rooms if len(row) >= 3 and bool(row[2])}
    missing = sorted(autojoin_rooms - joined_rooms)

    lines = [
        _line(True, "Rooms in DB", str(len(db_rooms))),
        _line(True, "Joined rooms", str(len(joined_rooms))),
        _line(not missing, "Autojoin coverage", "ok" if not missing else f"missing: {', '.join(missing)}"),
    ]
    if full and joined_rooms:
        for room in sorted(joined_rooms):
            nicks = (JOINED_ROOMS.get(room, {}) or {}).get("nicks", {}) or {}
            lines.append(_line(None, f"Room {room}", f"occupants={len(nicks)}"))
    return lines


async def _plugin_lines(bot: Any, *, full: bool) -> list[str]:
    manager = getattr(bot, "bot_plugins", None)
    if manager is None:
        return [_line(False, "Plugins", "plugin manager missing")]
    try:
        loaded = set(manager.list())
        available = set(manager.discover())
    except Exception as exc:
        return [_line(False, "Plugins", str(exc))]
    missing_core = sorted(set(getattr(manager, "core_plugins", set())) - loaded)
    lines = [
        _line(True, "Plugins loaded", str(len(loaded))),
        _line(True, "Plugins available", str(len(available))),
        _line(not missing_core, "Core plugins", "ok" if not missing_core else f"not loaded: {', '.join(missing_core)}"),
        _line(True, "Commands registered", str(len(COMMANDS.index))),
    ]
    issue_getter = getattr(manager, "all_metadata_issues", None)
    if callable(issue_getter):
        try:
            issues = list(await issue_getter())
            errors = [issue for issue in issues if getattr(issue, "severity", "") == "error"]
            lines.append(_line(not errors, "Plugin metadata", "ok" if not issues else f"{len(errors)} error(s), {len(issues) - len(errors)} warning(s)"))
            if full:
                lines.extend(_line(False if getattr(issue, "severity", "") == "error" else None, "Metadata", issue.format()) for issue in issues[:30])
        except Exception as exc:
            lines.append(_line(False, "Plugin metadata", str(exc)))
    return lines


def _task_lines(bot: Any, *, full: bool) -> list[str]:
    supervisor = getattr(bot, "tasks", None)
    if supervisor is None:
        return [_line(False, "Tasks", "supervisor missing")]
    try:
        running, failed, finished = supervisor.summary()
    except Exception as exc:
        return [_line(False, "Tasks", str(exc))]
    lines = [
        _line(failed == 0, "Background tasks", f"{running} running, {failed} failed, {finished} finished"),
    ]
    stale = getattr(supervisor, "stale_tasks", None)
    if callable(stale):
        try:
            stale_items = stale()
            lines.append(_line(not stale_items, "Task heartbeat", "ok" if not stale_items else f"{len(stale_items)} stale"))
            if full:
                for task in stale_items[:20]:
                    lines.append(_line(False, "Stale task", f"{task.plugin}/{task.name}"))
        except Exception as exc:
            lines.append(_line(False, "Task heartbeat", str(exc)))
    return lines


def _backup_lines() -> list[str]:
    directory = backup_dir()
    exists = directory.exists()
    writable_target = directory if exists else directory.parent
    writable = writable_target.exists() and os.access(writable_target, os.W_OK)
    backups = list_backups(directory=directory)
    lines = [
        _line(exists or writable, "Backup directory", str(directory)),
        _line(writable, "Backup writable", "yes" if writable else "no"),
        _line(True, "Backup retention", f"keep={backup_keep()}, days={backup_retention_days()}"),
        _line(True, "Managed backups", str(len(backups))),
    ]
    if backups:
        lines.append(_line(True, "Latest backup", f"{backups[0].name} · {backups[0].created_at}"))
    return lines


def _config_lines() -> list[str]:
    path = get_runtime_config_path()
    avatar = config.get("avatar")
    lines = [
        _line(Path(path).exists(), "Config file", str(path)),
        _line(True, "Command prefix", repr(config.get("prefix", ","))),
        _line(bool(config.get("command_rate_limit_enabled", True)), "Command rate limit", "enabled" if config.get("command_rate_limit_enabled", True) else "disabled"),
        _line(True, "Command timeout", f"{config.get('command_timeout_seconds', 30)}s"),
        _line(True, "SQLite busy timeout", f"{config.get('database_busy_timeout_ms', 5000)}ms"),
        _line(True, "SQLite WAL", "enabled" if config.get("database_wal_enabled", False) else "disabled"),
    ]
    if avatar:
        avatar_path = Path(str(avatar))
        if not avatar_path.is_absolute():
            avatar_path = Path.cwd() / avatar_path
        lines.append(_line(avatar_path.exists(), "Avatar file", str(avatar_path)))
    return lines


def _network_lines() -> list[str]:
    return [
        _line(True, "HTTP timeout", f"{config.get('http_timeout_seconds', 8)}s"),
        _line(True, "HTTP user-agent", str(config.get("http_user_agent", ""))[:80]),
        _line(not bool(config.get("allow_private_fetch_urls", False)), "Private fetch URLs", "allowed" if config.get("allow_private_fetch_urls", False) else "blocked"),
    ]


async def _plugin_doctor_lines(bot: Any, plugin_names: tuple[str, ...] | list[str]) -> list[str]:
    manager = getattr(bot, "bot_plugins", None)
    if manager is None:
        return [_line(False, "Plugin health", "plugin manager missing")]
    doctor = getattr(manager, "plugin_doctor", None)
    if not callable(doctor):
        return [_line(False, "Plugin health", "plugin diagnostics unavailable")]

    lines: list[str] = []
    for plugin_name in plugin_names:
        lines.extend(str(line) for line in await doctor(plugin_name))
    return lines or [_line(None, "Plugin health", "no plugins selected")]


def _overall_status(lines: list[str]) -> str:
    """Return a compact status line for doctor output."""
    body = lines[2:] if lines[:2] == ["🩺 EnvsBot doctor", ""] else lines
    failures = sum(1 for line in body if str(line).startswith("🔴"))
    warnings = sum(1 for line in body if str(line).startswith(("⚠️", "🟡", "🟡️")))
    if failures:
        return f"Overall: 🔴 {failures} problem(s), {warnings} warning(s)"
    if warnings:
        return f"Overall: ⚠️ {warnings} warning(s)"
    return "Overall: ✅ healthy"


async def _section_lines(bot: Any, section: str, *, full: bool) -> list[str]:
    if section == "config":
        return _config_lines()
    if section == "database":
        return await _db_lines(bot)
    if section == "rooms":
        return await _room_lines(bot, full=full)
    if section == "plugins":
        return await _plugin_lines(bot, full=full)
    if section == "tasks":
        return _task_lines(bot, full=full)
    if section == "backups":
        return _backup_lines()
    if section == "network":
        return _network_lines()
    if section == "plugin-health":
        return await _plugin_doctor_lines(bot, list(_PLUGIN_HEALTH_PLUGINS))
    if section.startswith("plugin:"):
        return await _plugin_doctor_lines(bot, [section.split(":", 1)[1]])
    return [_line(False, section, "unknown doctor section")]


async def build_doctor_lines(bot: Any, *, full: bool = False, sections: tuple[str, ...] | None = None) -> list[str]:
    """Build the doctor output as testable lines."""
    selected = sections or _DEFAULT_SECTIONS
    body: list[str] = []
    for section in selected:
        if section == "database":
            label = "Database"
        elif section == "plugin-health":
            label = "Plugin health"
        elif section.startswith("plugin:"):
            label = f"Plugin: {section.split(':', 1)[1]}"
        else:
            label = section.capitalize()
        body.append(f"[{label}]")
        body.extend(await _section_lines(bot, section, full=full))
        body.append("")
    if body and body[-1] == "":
        body.pop()
    return ["🩺 EnvsBot doctor", _overall_status(body), "", *body]


def _parse_doctor_args(args: list[str]) -> tuple[bool, list[str]]:
    """Return legacy ``(full, page_args)`` for doctor command arguments."""
    normalized = [str(arg).strip().lower() for arg in args if str(arg).strip()]
    full = False
    page_args: list[str] = []
    for arg in normalized:
        if arg in {"full", "details"}:
            full = True
            continue
        if arg == "all":
            full = True
        page_args.append(arg)
    return full, page_args


def _parse_doctor_sections(args: list[str]) -> tuple[bool, tuple[str, ...], list[str]]:
    """Return ``(full, sections, page_args)`` for doctor command arguments."""
    normalized = [str(arg).strip().lower() for arg in args if str(arg).strip()]
    full = False
    page_args: list[str] = []
    sections: list[str] = []
    for arg in normalized:
        mapped = _SECTION_ALIASES.get(arg)
        if mapped:
            if arg in {"full", "details"}:
                full = True
                continue
            if mapped == "all":
                full = True
                sections = list(_ALL_SECTIONS)
                page_args.append("all")
            elif mapped not in sections:
                sections.append(mapped)
            continue
        page_args.append(arg)
    return full, tuple(sections or _DEFAULT_SECTIONS), page_args


@command("doctor", role=Role.ADMIN, aliases=["bot doctor", "healthcheck", "bot health"])
async def doctor_command(bot, sender, nick, args, msg, is_room):
    """Run operator health checks."""
    full, sections, page_args = _parse_doctor_sections(args or [])
    lines = await build_doctor_lines(bot, full=full, sections=sections)
    bot.reply(
        msg,
        format_page(
            "🩺 EnvsBot doctor",
            lines[1:] if len(lines) > 1 else lines,
            page_request=parse_page_args(page_args),
            page_size=18,
            command_hint=f"{bot.prefix}doctor",
        ),
    )
