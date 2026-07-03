"""Operator health checks and diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from utils.backups import backup_dir, backup_keep, backup_retention_days
from utils.command import COMMANDS, Role, command
from utils.config import config, get_runtime_config_path
from utils.formatting import format_page, parse_page_args

PLUGIN_META = {
    "name": "doctor",
    "version": "0.1.0",
    "description": "Operator health checks and runtime diagnostics.",
    "category": "core",
}


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


def _plugin_lines(bot: Any) -> list[str]:
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
    return lines


def _task_lines(bot: Any) -> list[str]:
    supervisor = getattr(bot, "tasks", None)
    if supervisor is None:
        return [_line(False, "Tasks", "supervisor missing")]
    try:
        running, failed, finished = supervisor.summary()
    except Exception as exc:
        return [_line(False, "Tasks", str(exc))]
    return [
        _line(failed == 0, "Background tasks", f"{running} running, {failed} failed, {finished} finished"),
    ]


def _backup_lines() -> list[str]:
    directory = backup_dir()
    exists = directory.exists()
    writable_target = directory if exists else directory.parent
    writable = writable_target.exists() and os.access(writable_target, os.W_OK)
    return [
        _line(exists or writable, "Backup directory", str(directory)),
        _line(writable, "Backup writable", "yes" if writable else "no"),
        _line(True, "Backup retention", f"keep={backup_keep()}, days={backup_retention_days()}"),
    ]


def _config_lines() -> list[str]:
    path = get_runtime_config_path()
    avatar = config.get("avatar")
    lines = [
        _line(Path(path).exists(), "Config file", str(path)),
        _line(True, "Command prefix", repr(config.get("prefix", ","))),
        _line(bool(config.get("command_rate_limit_enabled", True)), "Command rate limit", "enabled" if config.get("command_rate_limit_enabled", True) else "disabled"),
    ]
    if avatar:
        avatar_path = Path(str(avatar))
        if not avatar_path.is_absolute():
            avatar_path = Path.cwd() / avatar_path
        lines.append(_line(avatar_path.exists(), "Avatar file", str(avatar_path)))
    return lines


async def build_doctor_lines(bot: Any, *, full: bool = False) -> list[str]:
    """Build the doctor output as testable lines."""
    lines = ["🩺 EnvsBot doctor", ""]
    for section, section_lines in (
        ("Config", _config_lines()),
        ("Database", await _db_lines(bot)),
        ("Rooms", await _room_lines(bot, full=full)),
        ("Plugins", _plugin_lines(bot)),
        ("Tasks", _task_lines(bot)),
        ("Backups", _backup_lines()),
    ):
        lines.append(f"[{section}]")
        lines.extend(section_lines)
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _parse_doctor_args(args: list[str]) -> tuple[bool, list[str]]:
    """Return ``(full, page_args)`` for doctor command arguments."""
    normalized = [str(arg).strip().lower() for arg in args if str(arg).strip()]
    if not normalized:
        return False, []

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


@command("doctor", role=Role.ADMIN, aliases=["bot doctor", "healthcheck", "bot health"])
async def doctor_command(bot, sender, nick, args, msg, is_room):
    """Run operator health checks."""
    full, page_args = _parse_doctor_args(args or [])
    lines = await build_doctor_lines(bot, full=full)
    bot.reply(
        msg,
        format_page(
            "🩺 EnvsBot doctor",
            lines[2:] if len(lines) > 2 else lines,
            page_request=parse_page_args(page_args),
            page_size=18,
            command_hint=f"{bot.prefix}doctor",
        ),
    )
