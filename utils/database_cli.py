"""Local database administration commands for envsbot."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from database.manager import DatabaseManager


def _database_path(config: Mapping[str, Any]) -> str:
    return str(config.get("db", "bot.db"))


async def _expected_schema_fingerprint() -> str:
    """Build the current release schema in memory and return its fingerprint."""
    db = DatabaseManager(":memory:")
    try:
        await db.connect(start_background=False)
        return await db.schema_fingerprint()
    finally:
        await db.close()


async def database_schema(config: Mapping[str, Any]) -> tuple[int, str]:
    """Show migration-catalog and actual/expected schema fingerprints."""
    db = DatabaseManager(_database_path(config))
    try:
        await db.connect(
            run_migrations=False,
            start_background=False,
            enforce_schema_compatibility=False,
        )
        status = await db.migration_status()
        expected = await _expected_schema_fingerprint()
        actual = str(status["schema_fingerprint"])
        mismatches = list(status["checksum_mismatches"])
        ok = not status["unknown"] and not mismatches and actual == expected
        lines = [
            f"Migration catalog: {status['catalog_fingerprint']}",
            f"Schema actual:     {actual}",
            f"Schema expected:   {expected}",
            "Schema match:      " + ("yes" if actual == expected else "NO"),
            "Migration checksums: "
            + ("ok" if not mismatches else "CHANGED: " + ", ".join(mismatches)),
        ]
        return (0 if ok else 1), "\n".join(lines)
    finally:
        await db.close()


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
            "Changed migrations: "
            + (", ".join(status["checksum_mismatches"]) or "none"),
            f"Migration catalog: {status['catalog_fingerprint']}",
            f"Schema fingerprint: {status['schema_fingerprint']}",
        ]
        last_run = status.get("last_run")
        if last_run:
            lines.append(
                "Last migration: "
                f"{last_run['version']} ({last_run['status']}, "
                f"{last_run['duration_ms']} ms)"
            )
        failed = bool(status["unknown"] or status["checksum_mismatches"])
        return (1 if failed else 0), "\n".join(lines)
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
        expected_schema = await _expected_schema_fingerprint()
        schema_matches = status["schema_fingerprint"] == expected_schema
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
            and not status["checksum_mismatches"]
            and schema_matches
            and write_error is None
        )
        lines = [
            "Integrity: " + (", ".join(integrity) if integrity else "no result"),
            f"Foreign keys: {'ok' if not fk_errors else f'{len(fk_errors)} violation(s)'}",
            "Pending migrations: " + (", ".join(status["pending"]) or "none"),
            "Unknown/newer migrations: " + (", ".join(status["unknown"]) or "none"),
            "Changed migrations: "
            + (", ".join(status["checksum_mismatches"]) or "none"),
            "Schema fingerprint: "
            + ("ok" if schema_matches else "MISMATCH")
            + f" ({status['schema_fingerprint']})",
            "Expected schema: " + expected_schema,
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
