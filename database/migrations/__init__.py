"""Database schema migration helpers.

Migrations are small async callables with stable version identifiers.  The
runner keeps the existing idempotent table creation style while making schema
changes explicit and ordered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

MigrationCallable = Callable[[object], Awaitable[None]]


@dataclass(frozen=True)
class Migration:
    """One ordered database migration."""

    version: str
    description: str
    run: MigrationCallable


async def _initial_runtime_tables(db) -> None:
    """Create core runtime tables owned by the users and rooms managers."""
    await db.users.init()
    await db.rooms.init()


async def _audit_log(db) -> None:
    """Create the audit log table."""
    await db.audit.init()


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        "0001_initial_runtime_tables",
        "Create users, users_runtime and rooms tables",
        _initial_runtime_tables,
    ),
    Migration(
        "0002_audit_log",
        "Create audit_log table",
        _audit_log,
    ),
)


def available_migrations() -> tuple[Migration, ...]:
    """Return all known migrations in application order."""
    return MIGRATIONS
