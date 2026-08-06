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


async def _message_cache(db) -> None:
    """Create the persistent shared recent-message cache."""
    await db.message_cache.init()


async def _idlerpg_state(db) -> None:
    """Create normalized IdleRPG state tables and indexes."""
    await db.idlerpg.init()


async def _outbox(db) -> None:
    """Create persistent outbound message queue."""
    await db.outbox.init()


async def _command_usage(db) -> None:
    """Create privacy-preserving command usage aggregates."""
    await db.command_usage.init()


async def _room_invites(db) -> None:
    """Create the pending room invite table and indexes."""
    await db.conn.execute(
        """
        CREATE TABLE IF NOT EXISTS room_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_jid TEXT NOT NULL,
            inviter TEXT NOT NULL,
            reason TEXT,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            UNIQUE(room_jid, inviter)
        )
        """
    )
    await db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_room_invites_created_at "
        "ON room_invites(created_at)"
    )


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
    Migration(
        "0003_room_invites",
        "Create room_invites table and index",
        _room_invites,
    ),
    Migration(
        "0004_message_cache",
        "Create persistent shared recent-message cache",
        _message_cache,
    ),
    Migration(
        "0005_idlerpg_state",
        "Create normalized IdleRPG room, player, season and event tables",
        _idlerpg_state,
    ),
    Migration(
        "0006_outbox",
        "Create persistent outbound message queue",
        _outbox,
    ),
    Migration(
        "0007_command_usage",
        "Create aggregate command usage statistics",
        _command_usage,
    ),
)


def available_migrations() -> tuple[Migration, ...]:
    """Return all known migrations in application order."""
    return MIGRATIONS
