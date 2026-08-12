"""Database schema migration helpers.

Migrations are small async callables with stable version identifiers.  The
runner keeps the existing idempotent table creation style while making schema
changes explicit and ordered.
"""

from __future__ import annotations

import hashlib
import inspect
import textwrap
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

MigrationCallable = Callable[[object], Awaitable[None]]


@dataclass(frozen=True)
class Migration:
    """One ordered database migration."""

    version: str
    description: str
    run: MigrationCallable

    @property
    def checksum(self) -> str:
        """Return a stable checksum for this immutable migration definition."""
        return migration_checksum(self)


def migration_checksum(migration: object) -> str:
    """Return a deterministic checksum for a migration-like object."""
    version = str(getattr(migration, "version", ""))
    description = str(getattr(migration, "description", ""))
    run = getattr(migration, "run", None)
    source = ""
    if run is not None:
        try:
            source = textwrap.dedent(inspect.getsource(run)).strip()
        except (OSError, TypeError):
            code = getattr(run, "__code__", None)
            if code is None:
                function = getattr(run, "__func__", None)
                code = getattr(function, "__code__", None)
            if code is not None:
                source = "|".join(
                    (
                        code.co_code.hex(),
                        repr(code.co_consts),
                        repr(code.co_names),
                    )
                )
            else:
                source = f"{type(run).__module__}.{type(run).__qualname__}"
    payload = "\n".join((version, description, source)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def migration_catalog_fingerprint(
    migrations: tuple[Migration, ...] | None = None,
) -> str:
    """Return a deterministic fingerprint for the ordered migration catalog."""
    selected = MIGRATIONS if migrations is None else migrations
    payload = "\n".join(
        f"{migration.version}:{migration_checksum(migration)}" for migration in selected
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


async def _initial_runtime_tables(db) -> None:
    """Create core runtime tables owned by the users and rooms managers."""
    await db.users.init(commit=False)
    await db.rooms.init(commit=False)


async def _audit_log(db) -> None:
    """Create the audit log table."""
    await db.audit.init(commit=False)


async def _message_cache(db) -> None:
    """Create the persistent shared recent-message cache."""
    await db.message_cache.init(commit=False)


async def _idlerpg_state(db) -> None:
    """Create normalized IdleRPG state tables and indexes."""
    await db.idlerpg.init(commit=False)


async def _outbox(db) -> None:
    """Create persistent outbound message queue."""
    await db.outbox.init(commit=False)


async def _command_usage(db) -> None:
    """Create privacy-preserving command usage aggregates."""
    await db.command_usage.init(commit=False)


async def _outbox_dead_timestamp(db) -> None:
    """Track when a message entered the dead-letter state for retention."""
    columns = {
        str(row["name"])
        for row in await db.fetch_all("PRAGMA table_info(outbox_messages)")
    }
    if "dead_at" not in columns:
        await db.write(
            "ALTER TABLE outbox_messages ADD COLUMN dead_at INTEGER",
            label="migration_outbox_dead_at",
        )


async def _room_invites(db) -> None:
    """Create the pending room invite table and indexes."""
    async with db.transaction(label="migration_room_invites") as conn:
        await conn.execute(
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
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_room_invites_created_at "
            "ON room_invites(created_at)"
        )


async def _outbox_origin_id(db) -> None:
    """Persist a stable XEP-0359 origin-id for every durable message."""
    columns = {
        str(row["name"])
        for row in await db.fetch_all("PRAGMA table_info(outbox_messages)")
    }
    if "origin_id" not in columns:
        await db.write(
            "ALTER TABLE outbox_messages ADD COLUMN origin_id TEXT",
            label="migration_outbox_origin_column",
        )

    rows = await db.fetch_all(
        "SELECT id, created_at, dedupe_key FROM outbox_messages "
        "WHERE origin_id IS NULL OR origin_id=''"
    )
    for row in rows:
        stable = uuid.uuid5(
            uuid.NAMESPACE_URL,
            "envsbot-outbox:"
            f"{int(row['id'])}:{int(row['created_at'])}:{str(row['dedupe_key'] or '')}",
        ).hex
        await db.write(
            "UPDATE outbox_messages SET origin_id=? WHERE id=?",
            (stable, int(row["id"])),
            label="migration_outbox_origin_backfill",
        )
    await db.write(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_outbox_origin_id "
        "ON outbox_messages(origin_id)",
        label="migration_outbox_origin_index",
    )


async def _reminders(db) -> None:
    """Create persistent reminder storage and lookup indexes."""
    async with db.transaction(label="migration_reminders") as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY,
                user_jid TEXT NOT NULL,
                room_jid TEXT,
                message TEXT NOT NULL,
                scheduled_at TIMESTAMP NOT NULL,
                remind_at TIMESTAMP NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_user_jid "
            "ON reminders(user_jid)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_remind_at "
            "ON reminders(remind_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_is_active "
            "ON reminders(is_active)"
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
    Migration(
        "0008_outbox_dead_timestamp",
        "Track when outbound messages enter dead-letter state",
        _outbox_dead_timestamp,
    ),
    Migration(
        "0009_outbox_origin_id",
        "Persist stable XEP-0359 origin IDs for durable message retries",
        _outbox_origin_id,
    ),
    Migration(
        "0010_reminders",
        "Create persistent reminder storage and indexes",
        _reminders,
    ),
)


def available_migrations() -> tuple[Migration, ...]:
    """Return all known migrations in application order."""
    return MIGRATIONS
