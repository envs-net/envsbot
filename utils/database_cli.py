"""Local database administration commands for envsbot."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from database.manager import DatabaseManager


def _database_path(config: Mapping[str, Any]) -> str:
    return str(config.get("db", "bot.db"))


async def database_status(config: Mapping[str, Any]) -> tuple[int, str]:
    """Return migration status without applying application migrations."""
    db = DatabaseManager(_database_path(config))
    try:
        await db.connect(
            run_migrations=False,
            start_background=False,
            enforce_schema_compatibility=False,
        )
        status = await db.migration_status()
        lines = [
            f"Database: {_database_path(config)}",
            f"Known migrations: {len(status['known'])}",
            f"Applied migrations: {len(status['applied'])}",
            "Pending: " + (", ".join(status["pending"]) or "none"),
            "Unknown/newer: " + (", ".join(status["unknown"]) or "none"),
        ]
        last_run = status.get("last_run")
        if last_run:
            lines.append(
                "Last migration: "
                f"{last_run['version']} ({last_run['status']}, "
                f"{last_run['duration_ms']} ms)"
            )
        return (1 if status["unknown"] else 0), "\n".join(lines)
    finally:
        await db.close()


async def database_migrate(
    config: Mapping[str, Any],
    *,
    dry_run: bool = False,
) -> tuple[int, str]:
    """Apply or preview pending migrations."""
    db = DatabaseManager(_database_path(config))
    try:
        await db.connect(
            run_migrations=False,
            start_background=False,
            enforce_schema_compatibility=True,
        )
        versions = await db.run_migrations(dry_run=dry_run)
        if not versions:
            return 0, "Database schema is already up to date."
        verb = "Would apply" if dry_run else "Applied"
        return 0, f"{verb} {len(versions)} migration(s): " + ", ".join(versions)
    finally:
        await db.close()


async def database_check(config: Mapping[str, Any]) -> tuple[int, str]:
    """Run integrity, FK, migration compatibility and write checks."""
    db = DatabaseManager(_database_path(config))
    try:
        await db.connect(
            run_migrations=False,
            start_background=False,
            enforce_schema_compatibility=False,
        )
        integrity = await db.integrity_check()
        fk_errors = await db.foreign_key_check()
        status = await db.migration_status()
        write_error: str | None = None
        try:
            await db.verify_read_write()
        except Exception as exc:  # diagnostic command: keep all checks visible
            write_error = f"{type(exc).__name__}: {exc}"
        integrity_ok = bool(integrity) and all(
            str(item).lower() == "ok" for item in integrity
        )
        ok = (
            integrity_ok
            and not fk_errors
            and not status["pending"]
            and not status["unknown"]
            and write_error is None
        )
        lines = [
            "Integrity: " + (", ".join(integrity) if integrity else "no result"),
            f"Foreign keys: {'ok' if not fk_errors else f'{len(fk_errors)} violation(s)'}",
            "Pending migrations: " + (", ".join(status["pending"]) or "none"),
            "Unknown/newer migrations: " + (", ".join(status["unknown"]) or "none"),
            "Read/write: " + ("ok" if write_error is None else write_error),
        ]
        return (0 if ok else 1), "\n".join(lines)
    finally:
        await db.close()


async def database_backup(
    config: Mapping[str, Any],
    *,
    destination: str | None = None,
) -> tuple[int, str]:
    """Create a consistent standalone SQLite snapshot."""
    db = DatabaseManager(_database_path(config))
    try:
        await db.connect(
            run_migrations=False,
            start_background=False,
            enforce_schema_compatibility=False,
        )
        target = Path(destination).expanduser() if destination else None
        result = await db.backup_database(destination=target)
        if result is None:
            return 1, "Database backup is unavailable for in-memory/URI databases."
        return 0, f"Database backup created: {result}"
    finally:
        await db.close()
