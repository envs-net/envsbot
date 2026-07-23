"""Operator health checks and diagnostics."""

from __future__ import annotations

import asyncio
import compileall
import os
import py_compile
import subprocess
import sys
from pathlib import Path
from typing import Any

from utils.backups import backup_dir, backup_keep, backup_retention_days, list_backups
from utils.command import COMMANDS, Role, command
from utils.command_metadata import help_example, help_subcommand
from utils.config import (
    collect_config_warnings,
    config,
    get_runtime_config_path,
    load_default_config_for_diff,
)
from utils.formatting import format_page, parse_page_args
from utils.file_security import (
    format_mode,
    has_group_or_other_access,
    sensitive_permission_targets,
)
from utils.updatecheck import check_for_updates_once
from utils.version import display_version

PLUGIN_META = {
    "name": "doctor",
    "version": "0.2.1",
    "description": "Operator health checks and runtime diagnostics.",
    "category": "core",
    "requires": ["rooms"],
}

_PLUGIN_HEALTH_PLUGINS = (
    "rss",
    "idlerpg",
    "reminder",
    "pin",
    "weather",
    "translate",
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
    "release": "release",
    "releases": "release",
    "preflight": "release",
    "plugin-health": "plugin-health",
    "pluginhealth": "plugin-health",
    "health": "plugin-health",
    "warnings": "warnings",
    "warning": "warnings",
    "warn": "warnings",
    "failed": "failed",
    "fail": "failed",
    "errors": "failed",
    "error": "failed",
    "rss": "plugin:rss",
    "idlerpg": "plugin:idlerpg",
    "irpg": "plugin:idlerpg",
    "reminder": "plugin:reminder",
    "pin": "plugin:pin",
    "weather": "plugin:weather",
    "translate": "plugin:translate",
    "tr": "plugin:translate",
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
_ALL_SECTIONS = _DEFAULT_SECTIONS + ("network", "release")


def _line(ok: bool | None, label: str, text: str) -> str:
    icon = "✅" if ok is True else "🔴" if ok is False else "ℹ️"
    return f"{icon} {label}: {text}"


def _warning_line(label: str, text: str) -> str:
    """Return a warning line that affects the overall doctor status."""
    return f"⚠️ {label}: {text}"


def _repo_root(start: Path | None = None, *, fallback: Path | None = None) -> Path:
    """Return the repository checkout root, even when running under mutmut.

    mutmut copies mutated modules below ``mutants/``.  In that case the
    module file can live below ``<repo>/mutants/`` instead of the normal
    package directory.  Walk upward from the module directory until the real
    checkout markers are found.  When no checkout marker is available, fall
    back to ``fallback`` or the current working directory so callers can still
    report a readable release-check error.
    """
    module_path = (start or Path(__file__)).resolve()
    search_from = module_path if module_path.is_dir() else module_path.parent
    for candidate in (search_from, *search_from.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "scripts").is_dir():
            return candidate
    return (fallback or Path.cwd()).resolve()


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

    migration_status = getattr(db, "migration_status", None)
    if callable(migration_status):
        try:
            status = await migration_status()
            applied = list(status.get("applied", []))
            pending = list(status.get("pending", []))
            if pending:
                message = f"pending: {', '.join(pending)}; applied: {', '.join(applied) if applied else 'none'}"
            else:
                message = ", ".join(applied) if applied else "none applied"
            lines.append(_line(not pending, "Migrations", message))
        except Exception as exc:
            lines.append(_line(False, "Migrations", str(exc)))
    else:
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

    cache = getattr(bot, "message_cache", None)
    stats = getattr(cache, "stats", None)
    if callable(stats):
        try:
            cache_stats = stats()
            degraded = bool(cache_stats.get("degraded"))
            detail = (
                f"messages={cache_stats.get('messages', 0)}, "
                f"pending={cache_stats.get('pending_writes', 0)}, "
                f"retry_backlog={cache_stats.get('retry_backlog', 0)}, "
                f"failures={cache_stats.get('persistence_failures', 0)}, "
                f"dropped={cache_stats.get('dropped_persistence_entries', 0)}"
            )
            lines.append(_line(not degraded, "Message cache persistence", detail))
        except Exception as exc:
            lines.append(_line(False, "Message cache persistence", str(exc)))
    return lines


async def _room_lines(bot: Any, *, full: bool) -> list[str]:
    try:
        from bot.room_state import JOINED_ROOMS
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
    private_fetch_allowed = bool(config.get("allow_private_fetch_urls", False))
    return [
        _line(True, "HTTP timeout", f"{config.get('http_timeout_seconds', 8)}s"),
        _line(True, "HTTP user-agent", str(config.get("http_user_agent", ""))[:80]),
        (
            _warning_line("Private fetch URLs", "allowed")
            if private_fetch_allowed
            else _line(True, "Private fetch URLs", "blocked")
        ),
    ]


def _local_version_line(bot: Any) -> str:
    """Return a release-check line for the local version."""
    raw_version = getattr(bot, "version", None)
    if not isinstance(raw_version, str) or not raw_version.strip():
        raw_version = None
    return _line(True, "Local version", display_version(raw_version))


async def _latest_release_line(bot: Any) -> str:
    """Return a release-check line for the latest published release."""
    try:
        update_available, remote_version, error = await check_for_updates_once(
            bot,
            announce=False,
            require_enabled=False,
        )
    except Exception as exc:
        return _line(None, "Latest release", f"check failed: {exc}")
    if error:
        return _line(None, "Latest release", f"check failed: {error}")
    if not remote_version:
        return _line(None, "Latest release", "unknown")
    status = "update available" if update_available else "current"
    return _line(not update_available, "Latest release", f"{display_version(remote_version)} ({status})")


def _command_docs_line() -> str:
    """Return a release-check line for generated command docs.

    Run the same checker as CI in a fresh interpreter.  Import-based validation
    can accidentally reuse already-loaded runtime modules from the bot process
    and report stale docs even when ``python scripts/check_command_docs.py``
    passes from the repository checkout.
    """
    root = _repo_root()
    script = root / "scripts" / "check_command_docs.py"
    if not script.exists():
        return _line(False, "Command docs", "check script missing")

    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        return _line(False, "Command docs", f"check failed: {exc}")

    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
    if proc.returncode == 0:
        for line in output.splitlines():
            if "Command docs check passed" in line:
                detail = line.replace("Command docs check passed", "ok").strip().rstrip(".")
                detail = detail.replace(" decorated commands", " commands")
                return _line(True, "Command docs", detail)
        return _line(True, "Command docs", "ok")

    issues = [line for line in output.splitlines() if line.lstrip().startswith("- ")]
    if issues:
        return _line(
            False,
            "Command docs",
            f"{len(issues)} issue(s); run scripts/generate_commands_md.py",
        )

    detail = output.splitlines()[-1] if output else f"checker exited with {proc.returncode}"
    return _line(False, "Command docs", detail[:160])


def _config_sample_line() -> str:
    """Return a release-check line for config/default consistency."""
    try:
        defaults = load_default_config_for_diff()
        warnings = collect_config_warnings(config)
    except Exception as exc:
        return _line(False, "Config sample", f"check failed: {exc}")

    missing = sorted(str(key) for key in defaults if key not in config)
    if missing:
        shown = ", ".join(missing[:8])
        suffix = "…" if len(missing) > 8 else ""
        return _line(False, "Config sample", f"missing runtime key(s): {shown}{suffix}")
    if warnings:
        shown = "; ".join(str(item) for item in warnings[:3])
        suffix = "…" if len(warnings) > 3 else ""
        return _line(None, "Config warnings", f"{shown}{suffix}")
    return _line(True, "Config sample", "ok")


def _release_permissions_line(bot: Any) -> str:
    """Return a release warning for broadly readable sensitive runtime paths."""
    db_path = Path(str(getattr(getattr(bot, "db", None), "path", config.get("db", "bot.db"))))
    paths = sensitive_permission_targets(
        config_path=get_runtime_config_path(),
        database_path=db_path,
        backup_directory=backup_dir(),
    )
    unsafe = [
        f"{label}={format_mode(path)}"
        for label, path in paths
        if path.exists() and has_group_or_other_access(path)
    ]
    if unsafe:
        return _line(False, "File permissions", ", ".join(unsafe))
    return _line(True, "File permissions", "owner-only")


def _release_python_compile_line() -> str:
    """Return a release-check line for basic Python syntax/import safety."""
    root = _repo_root()
    targets = [
        root / "bot",
        root / "core_plugins",
        root / "database",
        root / "plugins",
        root / "utils",
        root / "envsbot.py",
        root / "config_sample.py",
    ]
    try:
        for target in targets:
            if target.is_dir():
                if not compileall.compile_dir(target, quiet=2, maxlevels=20):
                    return _line(False, "Python compile", f"failed in {target.name}")
            elif target.exists():
                py_compile.compile(str(target), doraise=True)
        return _line(True, "Python compile", "ok")
    except Exception as exc:
        return _line(False, "Python compile", str(exc))


def _release_git_status_line() -> str:
    """Return a release-check line for uncommitted tracked changes."""
    root = _repo_root()
    if not (root / ".git").exists():
        return _line(None, "Git status", "not a git checkout")
    try:
        proc = subprocess.run(
            ["git", "status", "--short", "--untracked-files=no"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return _line(None, "Git status", f"check failed: {exc}")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git status failed").strip()
        return _line(None, "Git status", detail[:160])
    changed = [line for line in proc.stdout.splitlines() if line.strip()]
    if changed:
        return _line(False, "Git status", f"{len(changed)} tracked file(s) modified")
    return _line(True, "Git status", "clean")


def _release_task_line(bot: Any) -> str:
    """Return a release-check line for failed supervised tasks."""
    supervisor = getattr(bot, "tasks", None)
    if supervisor is None:
        return _line(None, "Background tasks", "supervisor unavailable")
    try:
        running, failed, finished = supervisor.summary()
    except Exception as exc:
        return _line(False, "Background tasks", str(exc))
    return _line(failed == 0, "Background tasks", f"{running} running, {failed} failed, {finished} finished")


async def _release_migration_line(bot: Any) -> str:
    """Return a release-check line for pending database migrations."""
    db = getattr(bot, "db", None)
    if db is None:
        return _line(None, "Migrations", "database unavailable")

    migration_status = getattr(db, "migration_status", None)
    if callable(migration_status):
        try:
            status = await migration_status()
            pending = list(status.get("pending", []))
            applied = list(status.get("applied", []))
        except Exception as exc:
            return _line(False, "Migrations", str(exc))
        if pending:
            return _line(False, "Migrations", f"pending: {', '.join(pending)}")
        return _line(True, "Migrations", f"ok ({len(applied)} applied)")

    list_migrations = getattr(db, "list_migrations", None)
    if callable(list_migrations):
        try:
            applied = [_migration_version(item) for item in list(await list_migrations())]
        except Exception as exc:
            return _line(False, "Migrations", str(exc))
        return _line(True, "Migrations", f"ok ({len(applied)} applied)")
    return _line(None, "Migrations", "status unavailable")


def _release_backup_line() -> str:
    """Return a release-check line for the latest managed backup."""
    try:
        backups = list_backups(directory=backup_dir())
    except Exception as exc:
        return _line(False, "Latest backup", str(exc))
    if not backups:
        return _line(None, "Latest backup", "no managed backup found")
    return _line(True, "Latest backup", f"{backups[0].name} · {backups[0].created_at}")


async def _release_plugin_metadata_line(bot: Any) -> str:
    """Return a release-check line for plugin metadata diagnostics."""
    manager = getattr(bot, "bot_plugins", None)
    if manager is None:
        return _line(None, "Plugin metadata", "plugin manager unavailable")
    issue_getter = getattr(manager, "all_metadata_issues", None)
    if not callable(issue_getter):
        return _line(None, "Plugin metadata", "metadata diagnostics unavailable")
    try:
        issues = list(await issue_getter())
    except Exception as exc:
        return _line(False, "Plugin metadata", str(exc))
    errors = [issue for issue in issues if getattr(issue, "severity", "") == "error"]
    if errors:
        return _line(False, "Plugin metadata", f"{len(errors)} error(s), {len(issues) - len(errors)} warning(s)")
    if issues:
        return _line(None, "Plugin metadata", f"{len(issues)} warning(s)")
    return _line(True, "Plugin metadata", "ok")


def _release_sync_lines(bot: Any) -> tuple[str, str, str, str, str, str]:
    """Run blocking release checks outside the XMPP event loop."""
    return (
        _command_docs_line(),
        _config_sample_line(),
        _release_permissions_line(bot),
        _release_python_compile_line(),
        _release_git_status_line(),
        _release_backup_line(),
    )


async def _release_lines(bot: Any) -> list[str]:
    """Return release-readiness checks for operators."""
    (
        command_docs,
        config_sample,
        permissions,
        python_compile,
        git_status,
        backup,
    ) = await asyncio.to_thread(_release_sync_lines, bot)
    return [
        _local_version_line(bot),
        await _latest_release_line(bot),
        command_docs,
        config_sample,
        permissions,
        python_compile,
        git_status,
        await _release_migration_line(bot),
        backup,
        _release_task_line(bot),
        await _release_plugin_metadata_line(bot),
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


def _problem_lines(lines: list[str], *, mode: str) -> list[str]:
    """Return warning/error lines from a full doctor result."""
    body = [line for line in lines if line and not str(line).startswith("Overall:") and line != "🩺 EnvsBot doctor"]
    if mode == "failed":
        matched = [line for line in body if str(line).startswith("🔴") or "failed" in str(line).lower()]
        return matched or ["✅ No failed doctor checks found."]
    matched = [
        line for line in body
        if str(line).startswith(("⚠️", "🟡", "🟡️")) or "warning" in str(line).lower()
    ]
    return matched or ["✅ No doctor warnings found."]


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
    if section == "release":
        return await _release_lines(bot)
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
        elif section == "release":
            label = "Release readiness"
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
    """Return ``(full, sections, page_args)`` for doctor command arguments.

    ``doctor full`` should be a full health sweep, while
    ``doctor tasks full`` should remain a detailed view of only the selected
    section.
    """
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
    if full and not sections:
        sections = list(_ALL_SECTIONS)
    return full, tuple(sections or _DEFAULT_SECTIONS), page_args


@command(
    "doctor",
    role=Role.ADMIN,
    aliases=["bot doctor", "healthcheck", "bot health"],
    short="Run operator health checks for config, DB, rooms, plugins, tasks, backups, network and release readiness.",
    usage="{prefix}doctor [config|database|rooms|plugins|tasks|backups|network|plugin-health|<plugin>|release|all|full] [page|last|all]",
    subcommands=[
        help_subcommand(
            "config",
            "{prefix}doctor config [page|last|all]",
            "Check configuration validity, defaults and runtime consistency.",
            examples=[help_example("{prefix}doctor config", "Run configuration-specific diagnostics.")],
        ),
        help_subcommand(
            "database",
            "{prefix}doctor database [page|last|all]",
            "Check database connectivity, migrations and persistence state.",
            examples=[help_example("{prefix}doctor database", "Run database-specific diagnostics.")],
        ),
        help_subcommand(
            "rooms",
            "{prefix}doctor rooms [page|last|all]",
            "Check stored, joined and configured room state.",
            examples=[help_example("{prefix}doctor rooms", "Inspect room storage and join state.")],
        ),
        help_subcommand(
            "plugins",
            "{prefix}doctor plugins [page|last|all]",
            "Check plugin loading, metadata and command registration.",
            examples=[help_example("{prefix}doctor plugins", "Inspect loaded plugin metadata and state.")],
        ),
        help_subcommand(
            "tasks",
            "{prefix}doctor tasks [full] [page|last|all]",
            "Check supervised background tasks and heartbeat state.",
            examples=[help_example("{prefix}doctor tasks full", "Show detailed task diagnostics.")],
        ),
        help_subcommand(
            "backups",
            "{prefix}doctor backups [page|last|all]",
            "Check managed backups, retention and latest archive state.",
            examples=[help_example("{prefix}doctor backups", "Inspect managed backup health.")],
        ),
        help_subcommand(
            "network",
            "{prefix}doctor network [page|last|all]",
            "Check network and TLS-related runtime prerequisites.",
            examples=[help_example("{prefix}doctor network", "Run network-related health checks.")],
        ),
        help_subcommand(
            "plugin-health",
            "{prefix}doctor plugin-health [page|last|all]",
            "Run every plugin-provided doctor check.",
            examples=[help_example("{prefix}doctor plugin-health", "Collect health results from all loaded plugins.")],
        ),
        help_subcommand(
            "<plugin>",
            "{prefix}doctor <plugin> [page|last|all]",
            "Run doctor checks for one named plugin.",
            examples=[help_example("{prefix}doctor rss", "Run only the RSS plugin diagnostics.")],
        ),
        help_subcommand(
            "full",
            "{prefix}doctor full [page|last|all]",
            "Run a detailed health sweep across all doctor sections.",
            aliases=("all", "details"),
            examples=[help_example("{prefix}doctor full", "Run the complete detailed health sweep.")],
        ),
        help_subcommand(
            "release",
            "{prefix}doctor release [page|last|all]",
            "Run release-readiness checks for version, docs, config, syntax, database, backups and tasks.",
            examples=[help_example("{prefix}doctor release", "Run the release candidate checklist.")],
        ),
    ],
    examples=[
        "{prefix}doctor",
        "{prefix}doctor full",
        "{prefix}doctor all",
        "{prefix}doctor rss",
        "{prefix}doctor translate",
        "{prefix}doctor tasks full",
        "{prefix}doctor release",
    ],
    category="admin",
    context="private chat / MUC PM",
)
async def doctor_command(bot, sender, nick, args, msg, is_room):
    """Run operator health checks."""
    full, sections, page_args = _parse_doctor_sections(args or [])
    filter_mode = None
    if sections == ("warnings",):
        filter_mode = "warnings"
        sections = _ALL_SECTIONS
        full = True
    elif sections == ("failed",):
        filter_mode = "failed"
        sections = _ALL_SECTIONS
        full = True

    lines = await build_doctor_lines(bot, full=full, sections=sections)
    output_lines = lines[1:] if len(lines) > 1 else lines
    title = "🩺 EnvsBot doctor"
    if filter_mode:
        output_lines = _problem_lines(lines, mode=filter_mode)
        title = f"🩺 EnvsBot doctor — {filter_mode}"
    bot.reply(
        msg,
        format_page(
            title,
            output_lines,
            page_request=parse_page_args(page_args),
            page_size=18,
            command_hint=f"{bot.prefix}doctor",
        ),
    )


@command(
    "doctor release",
    role=Role.ADMIN,
    aliases=["bot doctor release", "doctor preflight", "bot doctor preflight"],
    short="Run release-readiness checks for version, docs, config, syntax, DB, backups, tasks and plugin metadata.",
    usage="{prefix}doctor release [page|last|all]",
    examples=["{prefix}doctor release", "{prefix}doctor release all"],
    category="admin",
    context="private chat / MUC PM",
)
async def doctor_release(bot, sender, nick, args, msg, is_room):
    """Run release-readiness checks."""
    await doctor_command(bot, sender, nick, ["release", *(args or [])], msg, is_room)


@command(
    "doctor warnings",
    role=Role.ADMIN,
    aliases=["bot doctor warnings", "doctor warn", "doctor warning"],
    short="Show only doctor warning lines.",
    usage="{prefix}doctor warnings [page|last|all]",
    examples=["{prefix}doctor warnings"],
    category="admin",
    context="private chat / MUC PM",
)
async def doctor_warnings(bot, sender, nick, args, msg, is_room):
    """Show only doctor warning lines."""
    await doctor_command(bot, sender, nick, ["warnings", *(args or [])], msg, is_room)


@command(
    "doctor failed",
    role=Role.ADMIN,
    aliases=["bot doctor failed", "doctor errors", "doctor error"],
    short="Show only failed doctor checks.",
    usage="{prefix}doctor failed [page|last|all]",
    examples=["{prefix}doctor failed"],
    category="admin",
    context="private chat / MUC PM",
)
async def doctor_failed(bot, sender, nick, args, msg, is_room):
    """Show only failed doctor checks."""
    await doctor_command(bot, sender, nick, ["failed", *(args or [])], msg, is_room)
