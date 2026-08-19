"""Operator health checks and diagnostics."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from bot.room_state import direct_roster_contacts
from utils.backups import (
    backup_dir,
    backup_keep,
    backup_retention_days,
    backup_smoke_test_on_create,
    list_backups,
    list_migration_snapshots,
    migration_backup_keep,
    migration_backup_retention_days,
)
from utils.bundled_assets import resolve_bundled_asset
from utils.command import COMMANDS, Role, command
from utils.command_metadata import help_example, help_subcommand
from utils.config import (
    collect_config_warnings,
    config,
    get_runtime_config_path,
    load_default_config_for_diff,
)
from utils.file_security import (
    format_mode,
    has_group_or_other_access,
    sensitive_permission_targets,
)
from utils.formatting import format_page, parse_page_args
from utils.health import HealthSnapshot, collect_health_snapshot
from utils.http_user_agent import resolve_user_agent
from utils.performance import snapshot as performance_snapshot
from utils.updatecheck import check_for_updates_once, parse_version_tuple
from utils.version import display_version, normalized_version

PLUGIN_META = {
    "name": "doctor",
    "version": "0.2.2",
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
    "performance": "performance",
    "perf": "performance",
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
_ALL_SECTIONS = _DEFAULT_SECTIONS + ("performance", "network", "release")


def _line(ok: bool | None, label: str, text: str) -> str:
    icon = "✅" if ok is True else "🔴" if ok is False else "ℹ️"
    return f"{icon} {label}: {text}"


def _warning_line(label: str, text: str) -> str:
    """Return a warning line that affects the overall doctor status."""
    return f"⚠️ {label}: {text}"


def _is_mock_object(value: Any) -> bool:
    """Return whether *value* is a dynamically created unittest mock."""
    return type(value).__module__.startswith("unittest.mock")


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


async def _db_lines(bot: Any, health: HealthSnapshot | None = None) -> list[str]:
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

    shared = health or await collect_health_snapshot(bot, verify_backup=False)
    database_check = shared.check("database")
    maintenance = dict(database_check.data.get("maintenance", {}) or {})
    lines.append(
        _line(
            not database_check.needs_attention,
            "Database maintenance",
            (
                f"runs={maintenance.get('runs', 0)}, "
                f"failures={maintenance.get('failures', 0)}, "
                f"last={maintenance.get('last_duration_ms', 0)}ms"
                + (f", error={maintenance.get('last_error')}" if maintenance.get("last_error") else "")
            ),
        )
    )

    outbox_check = shared.check("outbox")
    if outbox_check.status != "unknown":
        state = outbox_check.data
        lines.append(
            _line(
                not outbox_check.needs_attention,
                "Persistent outbox",
                f"pending={state.get('pending', 0)}, dead={state.get('dead', 0)}, "
                f"oldest={state.get('oldest_pending_age_seconds', 0)}s",
            )
        )
    elif outbox_check.error:
        lines.append(_line(False, "Persistent outbox", outbox_check.error))

    cache_check = shared.check("message_cache")
    if cache_check.status != "unknown":
        cache_stats = cache_check.data
        detail = (
            f"messages={cache_stats.get('messages', 0)}, "
            f"pending={cache_stats.get('pending_writes', 0)}, "
            f"retry_backlog={cache_stats.get('retry_backlog', 0)}, "
            f"failures={cache_stats.get('persistence_failures', 0)}, "
            f"dropped={cache_stats.get('dropped_persistence_entries', 0)}"
        )
        lines.append(
            _line(
                not cache_check.needs_attention,
                "Message cache persistence",
                detail,
            )
        )
    elif cache_check.error:
        lines.append(_line(False, "Message cache persistence", cache_check.error))
    return lines


async def _room_lines(
    bot: Any,
    *,
    full: bool,
    health: HealthSnapshot | None = None,
) -> list[str]:
    shared = health or await collect_health_snapshot(bot, verify_backup=False)
    check = shared.check("rooms")
    data = check.data
    joined_rooms = set(str(room) for room in data.get("joined_rooms", ()) or ())
    autojoin_rooms = set(str(room) for room in data.get("autojoin_rooms", ()) or ())
    missing = list(str(room) for room in data.get("missing", ()) or ())

    rooms_manager = getattr(getattr(bot, "db", None), "rooms", None)
    list_rooms = getattr(rooms_manager, "list", None)
    db_rooms = []
    if callable(list_rooms):
        try:
            db_rooms = list(await list_rooms())
        except Exception as exc:
            return [_line(False, "Rooms", f"DB list failed: {exc}")]

    try:
        direct_contact_line = _line(
            True,
            "1:1 DM contacts",
            str(len(direct_roster_contacts(bot, db_rooms))),
        )
    except Exception as exc:
        direct_contact_line = _line(False, "1:1 DM contacts", f"count failed: {exc}")

    lines = [
        _line(True, "Rooms in DB", str(len(db_rooms))),
        _line(True, "Joined rooms", str(len(joined_rooms))),
        direct_contact_line,
        _line(
            not missing and check.status != "error",
            "Autojoin coverage",
            "ok" if not missing else f"missing: {', '.join(sorted(missing))}",
        ),
    ]
    if full and joined_rooms:
        try:
            from bot.room_state import JOINED_ROOMS
        except Exception:
            JOINED_ROOMS = {}
        for room in sorted(joined_rooms):
            nicks = (JOINED_ROOMS.get(room, {}) or {}).get("nicks", {}) or {}
            lines.append(_line(None, f"Room {room}", f"occupants={len(nicks)}"))
    if autojoin_rooms and not missing:
        # Keep the structured snapshot as the single source for coverage.
        assert int(data.get("autojoin_total", len(autojoin_rooms))) == len(autojoin_rooms)
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


def _task_summary_text(supervisor: Any) -> tuple[bool, str]:
    """Return health plus a lifecycle-aware background-task summary."""
    details = getattr(supervisor, "summary_by_kind", None)
    if callable(details):
        counts = details()
        failed = int(counts.get("failed", 0))
        service_finished = int(counts.get("services_finished", 0))
        healthy = failed == 0 and service_finished == 0
        text = (
            f"{int(counts.get('services_running', 0))} services running · "
            f"{int(counts.get('one_shots_running', 0))} one-shots running · "
            f"{int(counts.get('one_shots_completed', 0))} one-shots completed · "
            f"{failed} failed"
        )
        if service_finished:
            text += f" · {service_finished} services finished unexpectedly"
        return healthy, text
    running, failed, finished = supervisor.summary()
    return failed == 0, f"{running} running, {failed} failed, {finished} finished"

def _task_lines(
    bot: Any,
    *,
    full: bool,
    health: HealthSnapshot | None = None,
) -> list[str]:
    supervisor = getattr(bot, "tasks", None)
    if supervisor is None:
        return [_line(False, "Tasks", "supervisor missing")]
    if health is None:
        # Synchronous compatibility for direct helper tests; the full doctor
        # path always passes one shared snapshot.
        try:
            tasks_healthy, task_summary = _task_summary_text(supervisor)
        except Exception as exc:
            return [_line(False, "Tasks", str(exc))]
        snapshot_getter = getattr(supervisor, "snapshot", None)
        task_snapshot = (
            snapshot_getter(include_done=True)
            if callable(snapshot_getter) and not _is_mock_object(snapshot_getter)
            else []
        )
        open_circuits = [
            task for task in task_snapshot
            if getattr(task, "circuit_state", "closed") == "open"
        ]
    else:
        check = health.check("tasks")
        data = check.data
        failed = int(data.get("failed", 0) or 0)
        service_finished = int(data.get("services_finished", 0) or 0)
        tasks_healthy = not check.needs_attention or (
            not failed and not service_finished and not data.get("open_circuits")
        )
        task_summary = (
            f"{int(data.get('services_running', 0) or 0)} services running · "
            f"{int(data.get('one_shots_running', 0) or 0)} one-shots running · "
            f"{int(data.get('one_shots_completed', 0) or 0)} one-shots completed · "
            f"{failed} failed"
        )
        if service_finished:
            task_summary += f" · {service_finished} services finished unexpectedly"
        task_snapshot = list(data.get("snapshot", ()) or ())
        open_circuits = [
            task for task in task_snapshot
            if getattr(task, "circuit_state", "closed") == "open"
        ]

    lines = [
        _line(tasks_healthy, "Background tasks", task_summary),
        _line(
            not open_circuits,
            "Task circuits",
            "closed" if not open_circuits else f"{len(open_circuits)} open",
        ),
    ]
    if full:
        for task in open_circuits[:20]:
            lines.append(
                _line(False, "Open circuit", f"{task.plugin}/{task.name}: {task.last_error or '-'}")
            )

    if health is not None:
        watchdog_check = health.check("watchdog")
        if watchdog_check.status != "unknown":
            state = watchdog_check.data
            lines.append(
                _line(
                    not watchdog_check.needs_attention,
                    "Runtime watchdog",
                    f"running={state.get('worker_running', False)}, "
                    f"last_lag={float(state.get('last_lag_seconds', 0.0)):.3f}s, "
                    f"max_lag={float(state.get('max_lag_seconds', 0.0)):.3f}s",
                )
            )
    else:
        watchdog = getattr(bot, "watchdog", None)
        state_getter = getattr(watchdog, "runtime_state", None)
        if callable(state_getter) and not _is_mock_object(state_getter):
            state = state_getter()
            healthy = not state.get("last_error") and float(
                state.get("last_lag_seconds", 0.0)
            ) < float(config.get("watchdog_lag_failure_seconds", 30.0))
            lines.append(
                _line(
                    healthy,
                    "Runtime watchdog",
                    f"running={state.get('worker_running', False)}, "
                    f"last_lag={float(state.get('last_lag_seconds', 0.0)):.3f}s, "
                    f"max_lag={float(state.get('max_lag_seconds', 0.0)):.3f}s",
                )
            )

    stale = getattr(supervisor, "stale_tasks", None)
    if callable(stale):
        try:
            try:
                max_age = float(config.get("task_stale_after_seconds", 3600) or 3600)
            except Exception:
                max_age = 3600.0
            stale_items = stale(max_age_seconds=max_age)
            lines.append(
                _line(
                    not stale_items,
                    "Task heartbeat",
                    "ok" if not stale_items else f"{len(stale_items)} stale",
                )
            )
            if full:
                for task in stale_items[:20]:
                    lines.append(_line(False, "Stale task", f"{task.plugin}/{task.name}"))
        except Exception as exc:
            lines.append(_line(False, "Task heartbeat", str(exc)))
    return lines


def _backup_lines(bot: Any | None = None) -> list[str]:
    directory = backup_dir()
    exists = directory.exists()
    writable_target = directory if exists else directory.parent
    writable = writable_target.exists() and os.access(writable_target, os.W_OK)
    backups = list_backups(directory=directory)
    interval_hours = max(0, int(config.get("backup_interval_hours", 24) or 0))
    stale_hours = max(1, int(config.get("admin_alert_backup_max_age_hours", 36) or 36))
    schedule_ok = interval_hours == 0 or interval_hours < stale_hours
    schedule = "disabled" if interval_hours == 0 else f"every {interval_hours}h"
    schedule_detail = (
        "stale-age alert inactive"
        if interval_hours == 0
        else f"stale alert {stale_hours}h"
    )
    lines = [
        _line(exists or writable, "Backup directory", str(directory)),
        _line(writable, "Backup writable", "yes" if writable else "no"),
        _line(True, "Backup retention", f"keep={backup_keep()}, days={backup_retention_days()}"),
        _line(
            schedule_ok,
            "Backup schedule",
            f"{schedule} · {schedule_detail}",
        ),
        _line(
            backup_smoke_test_on_create(),
            "Backup restore smoke test",
            "required on create" if backup_smoke_test_on_create() else "disabled",
        ),
        _line(True, "Managed backups", str(len(backups))),
        _line(
            True,
            "Pre-migration snapshots",
            f"{len(list_migration_snapshots(directory=directory))} · "
            f"keep={migration_backup_keep()}, days={migration_backup_retention_days()}",
        ),
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
        avatar_path = resolve_bundled_asset(str(avatar), base_dir=_repo_root())
        lines.append(_line(avatar_path.exists(), "Avatar file", str(avatar_path)))
    return lines


def _performance_lines(bot: Any, *, full: bool) -> list[str]:
    """Return compact in-process latency diagnostics."""
    data = performance_snapshot()
    timings = data.get("timings", {}) if isinstance(data, dict) else {}
    groups = data.get("groups", {}) if isinstance(data, dict) else {}
    lines: list[str] = []

    watchdog = getattr(bot, "watchdog", None)
    runtime_state = getattr(watchdog, "runtime_state", None)
    if callable(runtime_state):
        state = runtime_state()
        if isinstance(state, dict):
            lines.append(
                _line(
                    True,
                    "Event-loop lag",
                    f"last {float(state.get('last_lag_seconds', 0.0) or 0.0):.3f}s / "
                    f"max {float(state.get('max_lag_seconds', 0.0) or 0.0):.3f}s",
                )
            )

    labels = (
        ("db_lock_wait", "DB lock wait"),
        ("idlerpg_tick", "IdleRPG tick"),
        ("idlerpg_save", "IdleRPG save"),
        ("idlerpg_export", "IdleRPG export"),
        ("outbox_delivery", "Outbox delivery"),
        ("rss_fetch", "RSS fetch"),
    )
    for key, label in labels:
        stats = timings.get(key) if isinstance(timings, dict) else None
        if not isinstance(stats, dict) or not int(stats.get("count", 0) or 0):
            continue
        lines.append(
            _line(
                True,
                label,
                f"p50 {float(stats.get('p50_ms', 0.0) or 0.0):.1f}ms / "
                f"p95 {float(stats.get('p95_ms', 0.0) or 0.0):.1f}ms / "
                f"p99 {float(stats.get('p99_ms', 0.0) or 0.0):.1f}ms / "
                f"n={int(stats.get('count', 0) or 0)}",
            )
        )

    group_specs = (("commands", "Slow commands"), ("rss_hosts", "Slow RSS hosts"))
    limit = 10 if full else 3
    for group_name, label in group_specs:
        values = groups.get(group_name) if isinstance(groups, dict) else None
        if not isinstance(values, dict) or not values:
            continue
        ranked = sorted(
            (
                (str(key), stats)
                for key, stats in values.items()
                if isinstance(stats, dict)
            ),
            key=lambda item: float(item[1].get("p95_ms", 0.0) or 0.0),
            reverse=True,
        )[:limit]
        detail = "; ".join(
            f"{key} p95 {float(stats.get('p95_ms', 0.0) or 0.0):.1f}ms "
            f"p99 {float(stats.get('p99_ms', 0.0) or 0.0):.1f}ms"
            for key, stats in ranked
        )
        if detail:
            lines.append(_line(True, label, detail))

    users = getattr(getattr(bot, "db", None), "users", None)
    cache_state = getattr(users, "cache_state", None)
    if callable(cache_state):
        try:
            state = cache_state()
            lines.append(
                _line(
                    True,
                    "User caches",
                    f"users={state.get('users', 0)}/{state.get('user_limit', 0)}, "
                    f"runtime={state.get('runtime', 0)}/{state.get('runtime_limit', 0)}, "
                    f"dirty={state.get('dirty_users', 0)}+{state.get('dirty_runtime', 0)}, "
                    f"evicted={state.get('evicted_users', 0)}+{state.get('evicted_runtime', 0)}",
                )
            )
        except Exception as exc:
            lines.append(_line(False, "User caches", str(exc)))

    limiter = getattr(bot, "rate_limiter", None)
    limiter_state = getattr(limiter, "runtime_state", None)
    if callable(limiter_state):
        try:
            state = limiter_state()
            lines.append(
                _line(
                    True,
                    "Rate limiter cache",
                    f"clients={state.get('clients', 0)}/{state.get('max_clients', 0)}, "
                    f"blocked={state.get('blocked_clients', 0)}, "
                    f"evicted={state.get('capacity_evictions', 0)}, "
                    f"stale_pruned={state.get('stale_pruned', 0)}",
                )
            )
        except Exception as exc:
            lines.append(_line(False, "Rate limiter cache", str(exc)))
    return lines or [_line(None, "Performance", "no runtime samples collected yet")]


def _network_lines() -> list[str]:
    private_fetch_allowed = bool(config.get("allow_private_fetch_urls", False))
    return [
        _line(True, "HTTP timeout", f"{config.get('http_timeout_seconds', 8)}s"),
        _line(True, "HTTP user-agent", resolve_user_agent(config.get("http_user_agent"))[:80]),
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


def _git_commits_ahead_of_release(remote_version: str) -> int | None:
    """Return commits between the published release tag and local ``HEAD``.

    ``None`` means the checkout cannot be compared reliably (for example a
    source archive, a shallow checkout without tags, or a tag that is not an
    ancestor of ``HEAD``).  This keeps the release check conservative while
    allowing development checkouts to report unreleased commits even before
    ``__version__`` is bumped.
    """
    root = _repo_root()
    if not (root / ".git").exists():
        return None

    normalized = normalized_version(remote_version)
    tag_candidates = (f"v{normalized}", normalized)
    for tag in tag_candidates:
        try:
            resolve = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}"],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except Exception:
            return None
        if resolve.returncode != 0:
            continue

        tag_commit = resolve.stdout.strip()
        if not tag_commit:
            continue
        try:
            ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", tag_commit, "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            if ancestor.returncode != 0:
                return None
            count = subprocess.run(
                ["git", "rev-list", "--count", f"{tag_commit}..HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except Exception:
            return None
        if count.returncode != 0:
            return None
        try:
            return max(0, int(count.stdout.strip()))
        except ValueError:
            return None

    return None


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

    raw_local = getattr(bot, "version", None)
    local_version = normalized_version(
        raw_local if isinstance(raw_local, str) and raw_local.strip() else None
    )
    remote_parts = parse_version_tuple(remote_version)
    local_parts = parse_version_tuple(local_version)
    if update_available or remote_parts > local_parts:
        return _line(
            False,
            "Latest release",
            f"{display_version(remote_version)} (update available)",
        )
    if local_parts > remote_parts:
        return _warning_line(
            "Latest release",
            f"{display_version(remote_version)} (local build ahead / unreleased)",
        )
    if local_parts == remote_parts:
        commits_ahead = await asyncio.to_thread(
            _git_commits_ahead_of_release,
            remote_version,
        )
        if commits_ahead is not None and commits_ahead > 0:
            return _warning_line(
                "Latest release",
                f"{display_version(remote_version)} (local build ahead / unreleased)",
            )
    return _line(True, "Latest release", f"{display_version(remote_version)} (current)")


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
            capture_output=True,
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
    """Return a read-only-safe release check for Python syntax.

    The production systemd unit intentionally mounts the application tree
    read-only.  ``compileall``/``py_compile`` normally create ``__pycache__``
    files, so using them here produced a false failure under
    ``ProtectSystem=strict``.  Compiling source bytes directly performs the
    same syntax compilation without writing into the checkout.
    """
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
            sources = sorted(target.rglob("*.py")) if target.is_dir() else [target]
            for source in sources:
                if not source.is_file():
                    continue
                compile(source.read_bytes(), str(source), "exec", dont_inherit=True)
        return _line(True, "Python compile", "ok")
    except SyntaxError as exc:
        filename = Path(exc.filename).name if exc.filename else "unknown"
        line = f":{exc.lineno}" if exc.lineno else ""
        return _line(False, "Python compile", f"{filename}{line}: {exc.msg}")
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
            capture_output=True,
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
        healthy, summary = _task_summary_text(supervisor)
    except Exception as exc:
        return _line(False, "Background tasks", str(exc))
    return _line(healthy, "Background tasks", summary)


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


async def _section_lines(
    bot: Any, section: str, *, full: bool, health: HealthSnapshot | None = None
) -> list[str]:
    if section == "config":
        return _config_lines()
    if section == "database":
        return await _db_lines(bot, health=health)
    if section == "rooms":
        return await _room_lines(bot, full=full, health=health)
    if section == "plugins":
        return await _plugin_lines(bot, full=full)
    if section == "tasks":
        return _task_lines(bot, full=full, health=health)
    if section == "backups":
        return _backup_lines(bot)
    if section == "performance":
        return _performance_lines(bot, full=full)
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
    health = await collect_health_snapshot(bot, verify_backup=False)
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
        body.extend(await _section_lines(bot, section, full=full, health=health))
        body.append("")
    if body and body[-1] == "":
        body.pop()
    return ["🩺 EnvsBot doctor", _overall_status(body), "", *body]


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
    short="Run operator health checks for config, DB, rooms, plugins, tasks, performance, backups, network and release readiness.",
    usage="{prefix}doctor [config|database|rooms|plugins|tasks|performance|backups|network|plugin-health|<plugin>|release|all|full] [page|last|all]",
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
            "performance",
            "{prefix}doctor performance [full] [page|last|all]",
            "Show event-loop, DB, IdleRPG, outbox, RSS and command latency diagnostics.",
            aliases=("perf",),
            examples=[help_example("{prefix}doctor performance", "Inspect in-process performance counters.")],
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
        "{prefix}doctor performance",
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
