import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from utils.config import config
from utils.file_security import ensure_private_file
from utils.logging_helpers import kv

from .users import UserManager
from .rooms import Rooms
from .audit import AuditLog
from .message_cache import MessageCacheStore
from .idlerpg import IdleRPGStateStore
from .outbox import OutboxStore
from .command_usage import CommandUsageStore
from .migrations import available_migrations
from .locking import AsyncRLock

# logger for this module
log = logging.getLogger(__name__)


class DatabaseSchemaTooNewError(RuntimeError):
    """Raised when a database contains migrations unknown to this build."""


_WRITE_PREFIX_RE = re.compile(
    r"^\s*(?:--[^\n]*\n\s*)*(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER)\b",
    re.IGNORECASE,
)


class DatabaseManager:
    """
    Central database manager.

    Handles the SQLite connection and exposes
    table managers for users and rooms.

    Also runs background tasks that periodically
    flush cached user data to the database.
    """

    def __init__(self, path: str, flush_interval: int = 60):

        self.path = path
        self.conn = None

        self.users = None
        self.rooms = None
        self.audit = None
        self.message_cache = None
        self.idlerpg = None
        self.outbox = None
        self.command_usage = None

        self.flush_interval = flush_interval

        self._flush_task = None
        self._maintenance_task = None
        self.maintenance_state = {
            "runs": 0,
            "failures": 0,
            "consecutive_failures": 0,
            "last_run_at": 0,
            "last_duration_ms": 0,
            "last_error": None,
            "last_wal_checkpoint": None,
        }
        self._running = False
        self._stop_event = asyncio.Event()
        self._close_lock = asyncio.Lock()
        self.transaction_lock = AsyncRLock()

    async def connect(
        self,
        *,
        run_migrations: bool = True,
        start_background: bool = True,
        enforce_schema_compatibility: bool = True,
    ):
        """Open the database connection and optionally migrate/start workers."""
        if self.conn is not None:
            return

        self._stop_event = asyncio.Event()
        self._running = False
        try:
            self.conn = await aiosqlite.connect(self.path)
            self.conn.row_factory = aiosqlite.Row
            self._secure_database_files()

            # SQLite runtime pragmas. Keep these near connect() so every process
            # consistently applies them before table managers start using the DB.
            await self.conn.execute("PRAGMA foreign_keys = ON;")
            try:
                busy_timeout = max(0, int(config.get("database_busy_timeout_ms", 5000) or 0))
            except Exception:
                busy_timeout = 5000
            await self.conn.execute(f"PRAGMA busy_timeout = {busy_timeout};")
            if config.get("database_wal_enabled", False):
                await self.conn.execute("PRAGMA journal_mode = WAL;")
                self._secure_database_files()

            cursor = await self.conn.execute("PRAGMA foreign_keys;")
            row = await cursor.fetchone()
            if row["foreign_keys"] != 1:
                raise RuntimeError("Failed to enable foreign keys")

            self.users = UserManager(
                self.conn,
                transaction_lock=self.transaction_lock,
            )
            self.rooms = Rooms(self.conn, transaction_lock=self.transaction_lock)
            self.audit = AuditLog(self.conn, transaction_lock=self.transaction_lock)
            self.message_cache = MessageCacheStore(self)
            self.idlerpg = IdleRPGStateStore(self)
            self.outbox = OutboxStore(self)
            self.command_usage = CommandUsageStore(self)

            await self._init_schema_migrations()
            if enforce_schema_compatibility:
                await self.assert_schema_compatible()
            if run_migrations:
                await self.run_migrations()
            self._secure_database_files()

            self._running = True
            if start_background:
                self._flush_task = asyncio.create_task(self._flush_loop(), name="database-flush")
                self._maintenance_task = asyncio.create_task(
                    self._maintenance_loop(), name="database-maintenance"
                )
        except Exception:
            conn = self.conn
            self.conn = None
            self.users = None
            self.rooms = None
            self.audit = None
            self.message_cache = None
            self.idlerpg = None
            self.outbox = None
            self.command_usage = None
            self._running = False
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    log.exception("[DB] Failed to close connection after startup error")
            raise

    def _database_paths(self) -> tuple[Path, ...]:
        """Return on-disk SQLite files that should remain owner-only."""
        raw = str(self.path or "")
        if raw in {"", ":memory:"} or raw.startswith("file:"):
            return ()
        path = Path(raw).expanduser()
        return (path, Path(f"{path}-wal"), Path(f"{path}-shm"))

    def _secure_database_files(self) -> None:
        for path in self._database_paths():
            ensure_private_file(path)

    async def _init_schema_migrations(self) -> None:
        """Create and upgrade migration bookkeeping outside application migrations."""
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'applied',
                error TEXT
            )
            """
        )
        columns = {
            str(row["name"])
            for row in await (await self.conn.execute("PRAGMA table_info(schema_migrations)")).fetchall()
        }
        for name, ddl in (
            ("duration_ms", "INTEGER NOT NULL DEFAULT 0"),
            ("status", "TEXT NOT NULL DEFAULT 'applied'"),
            ("error", "TEXT"),
        ):
            if name not in columns:
                await self.conn.execute(f"ALTER TABLE schema_migrations ADD COLUMN {name} {ddl}")
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migration_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL,
                started_at TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                status TEXT NOT NULL,
                error TEXT
            )
            """
        )
        await self.conn.commit()

    async def mark_migration_applied(
        self,
        version: str,
        *,
        duration_ms: int = 0,
        commit: bool = True,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO schema_migrations (version, duration_ms, status, error)
            VALUES (?, ?, 'applied', NULL)
            ON CONFLICT(version) DO UPDATE SET
                duration_ms=excluded.duration_ms, status='applied', error=NULL
            """,
            (version, max(0, int(duration_ms))),
        )
        if commit:
            await self.conn.commit()

    async def _record_migration_history(
        self,
        version: str,
        *,
        started_at: str,
        duration_ms: int,
        status: str,
        error: str | None = None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO schema_migration_history (
                version, started_at, duration_ms, status, error
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (version, started_at, max(0, int(duration_ms)), status, error),
        )
        await self.conn.commit()

    async def list_migrations(self):
        cursor = await self.conn.execute(
            "SELECT version, applied_at, duration_ms, status, error "
            "FROM schema_migrations ORDER BY version"
        )
        return await cursor.fetchall()

    async def migration_history(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = await (
            await self.conn.execute(
                "SELECT version, started_at, duration_ms, status, error "
                "FROM schema_migration_history ORDER BY id DESC LIMIT ?",
                (max(1, min(200, int(limit))),),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    async def applied_migration_versions(self) -> set[str]:
        rows = await self.list_migrations()
        return {str(row["version"]) for row in rows}

    async def unknown_migration_versions(self) -> list[str]:
        known = {migration.version for migration in available_migrations()}
        return sorted((await self.applied_migration_versions()) - known)

    async def assert_schema_compatible(self) -> None:
        unknown = await self.unknown_migration_versions()
        if unknown:
            raise DatabaseSchemaTooNewError(
                "Database schema is newer than this envsbot build; unknown migration(s): "
                + ", ".join(unknown)
            )

    async def pending_migration_versions(self) -> list[str]:
        applied = await self.applied_migration_versions()
        return [
            migration.version
            for migration in available_migrations()
            if migration.version not in applied
        ]

    async def migration_status(self) -> dict[str, Any]:
        applied = sorted(await self.applied_migration_versions())
        known = [migration.version for migration in available_migrations()]
        applied_set = set(applied)
        pending = [version for version in known if version not in applied_set]
        unknown = sorted(applied_set - set(known))
        history = await self.migration_history(limit=1)
        return {
            "known": known,
            "applied": applied,
            "pending": pending,
            "unknown": unknown,
            "last_run": history[0] if history else None,
        }

    async def verify_read_write(self) -> None:
        await self.fetch_one("SELECT 1")
        async with self.transaction_lock:
            await self.conn.execute("SAVEPOINT envsbot_preflight_rw")
            try:
                await self.conn.execute(
                    "CREATE TEMP TABLE IF NOT EXISTS envsbot_preflight_check (value INTEGER)"
                )
                await self.conn.execute(
                    "INSERT INTO envsbot_preflight_check (value) VALUES (1)"
                )
            finally:
                await self.conn.execute("ROLLBACK TO envsbot_preflight_rw")
                await self.conn.execute("RELEASE envsbot_preflight_rw")

    def _migration_backup_path(self) -> Path | None:
        raw = str(self.path or "")
        if raw in {"", ":memory:"} or raw.startswith("file:"):
            return None
        from utils.backups import backup_dir

        directory = backup_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        return directory / f"envsbot-db-pre-migration-{stamp}.sqlite3"

    async def backup_database(
        self,
        *,
        destination: Path | None = None,
    ) -> Path | None:
        """Create a consistent SQLite snapshot without stopping the bot."""
        target = destination or self._migration_backup_path()
        if target is None:
            return None
        target = Path(target).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        async with self.transaction_lock:
            target_conn = await aiosqlite.connect(str(target))
            try:
                await self.conn.backup(target_conn)
                await target_conn.commit()
            finally:
                await target_conn.close()
        ensure_private_file(target)
        return target

    async def run_migrations(
        self,
        *,
        dry_run: bool = False,
        backup_before: bool | None = None,
    ) -> list[str]:
        """Run pending migrations transactionally and return affected versions."""
        await self.assert_schema_compatible()
        applied = await self.applied_migration_versions()
        pending = [m for m in available_migrations() if m.version not in applied]
        if dry_run:
            return [migration.version for migration in pending]
        if not pending:
            return []

        should_backup = (
            bool(config.get("database_backup_before_migrate", True))
            if backup_before is None
            else bool(backup_before)
        )
        if should_backup:
            backup = await self.backup_database()
            if backup is not None:
                log.info("[DB] Pre-migration snapshot created: %s", backup)

        completed: list[str] = []
        async with self.transaction_lock:
            for migration in pending:
                started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                started = time.monotonic()
                savepoint = "migration_" + re.sub(r"[^a-zA-Z0-9_]", "_", migration.version)
                log.info(
                    "[DB] event=migration status=applying %s",
                    kv(version=migration.version, description=migration.description),
                )
                await self.conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    await migration.run(self)
                    duration_ms = int((time.monotonic() - started) * 1000)
                    await self.mark_migration_applied(
                        migration.version,
                        duration_ms=duration_ms,
                        commit=False,
                    )
                    await self.conn.execute(f"RELEASE {savepoint}")
                except Exception as exc:
                    duration_ms = int((time.monotonic() - started) * 1000)
                    try:
                        await self.conn.execute(f"ROLLBACK TO {savepoint}")
                        await self.conn.execute(f"RELEASE {savepoint}")
                    finally:
                        await self._record_migration_history(
                            migration.version,
                            started_at=started_at,
                            duration_ms=duration_ms,
                            status="failed",
                            error=f"{type(exc).__name__}: {exc}"[:1000],
                        )
                    log.exception(
                        "[DB] event=migration status=failed %s",
                        kv(version=migration.version, duration_ms=duration_ms),
                    )
                    raise
                else:
                    await self._record_migration_history(
                        migration.version,
                        started_at=started_at,
                        duration_ms=duration_ms,
                        status="applied",
                    )
                    completed.append(migration.version)
                    applied.add(migration.version)
                    log.info(
                        "[DB] event=migration status=ok %s",
                        kv(version=migration.version, duration_ms=duration_ms),
                    )
        return completed

    async def _flush_loop(self):
        """Background loop that flushes data periodically with retry logic."""
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.flush_interval
                    )
                except asyncio.TimeoutError:
                    if self.users:
                        await self._flush_with_retry()
        finally:
            # final guaranteed flush with retry
            if self.users:
                await self._flush_with_retry()


    async def run_maintenance(self) -> dict[str, object]:
        """Run low-impact SQLite maintenance and return diagnostic state."""
        started = time.monotonic()
        checkpoint = None
        try:
            async with self.transaction_lock:
                await self.conn.execute("PRAGMA optimize;")
                if config.get("database_wal_enabled", False):
                    cursor = await self.conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
                    row = await cursor.fetchone()
                    checkpoint = tuple(row) if row is not None else None
                retention_days = int(config.get("command_usage_retention_days", 365) or 0)
                if self.command_usage is not None:
                    await self.command_usage.prune(retention_days=retention_days)
                if self.outbox is not None:
                    await self.outbox.prune_dead(
                        retention_days=int(config.get("outbox_dead_retention_days", 30) or 0)
                    )
                await self.conn.commit()
        except Exception as exc:
            self.maintenance_state["failures"] += 1
            self.maintenance_state["consecutive_failures"] += 1
            self.maintenance_state["last_error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.maintenance_state["last_duration_ms"] = int(
                (time.monotonic() - started) * 1000
            )
        self.maintenance_state["runs"] += 1
        self.maintenance_state["consecutive_failures"] = 0
        self.maintenance_state["last_run_at"] = int(time.time())
        self.maintenance_state["last_error"] = None
        self.maintenance_state["last_wal_checkpoint"] = checkpoint
        return dict(self.maintenance_state)

    async def _maintenance_loop(self) -> None:
        """Periodically optimize SQLite and checkpoint WAL without blocking shutdown."""
        interval = max(60, int(config.get("database_maintenance_interval_seconds", 21600) or 21600))
        try:
            while not self._stop_event.is_set():
                stop_requested = True
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=interval,
                    )
                except asyncio.TimeoutError:
                    stop_requested = False
                if stop_requested:
                    break
                try:
                    await self.run_maintenance()
                except Exception:
                    log.exception("[DB] Periodic maintenance failed")
        except asyncio.CancelledError:
            raise

    async def _flush_with_retry(
        self,
        max_retries: int = 3,
        backoff: float = 1.0,
        *,
        raise_on_failure: bool = False,
    ) -> bool:
        """
        Flush with exponential backoff retry logic.

        Args:
            max_retries: Maximum number of retry attempts
            backoff: Initial backoff in seconds (exponential growth)
        """
        for attempt in range(max_retries):
            try:
                await self.users.flush_all()
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = backoff * (2 ** attempt)
                    log.warning(
                        "[DatabaseManager] Flush attempt %d/%d failed, "
                        "retrying in %.1fs: %s",
                        attempt + 1, max_retries, wait_time, e
                    )
                    await asyncio.sleep(wait_time)
                else:
                    log.exception(
                        "[DatabaseManager] 🔴 Flush failed after %d attempts:"
                        " %s",
                        max_retries, e
                    )
                    if raise_on_failure:
                        raise
                    return False
        return False

    async def flush(self):
        """Manually flush cached data, raising when persistence fails."""
        if self.users:
            await self._flush_with_retry(raise_on_failure=True)

    async def integrity_check(self) -> list[str]:
        """Run SQLite PRAGMA integrity_check and return result rows."""
        cursor = await self.conn.execute("PRAGMA integrity_check;")
        rows = await cursor.fetchall()
        result: list[str] = []
        for row in rows:
            try:
                result.append(str(row[0]))
            except Exception:
                result.append(str(row))
        return result

    async def foreign_key_check(self) -> list[dict[str, Any]]:
        """Return SQLite foreign-key violations."""
        cursor = await self.conn.execute("PRAGMA foreign_key_check;")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def optimize(self) -> None:
        """Run SQLite PRAGMA optimize for opportunistic maintenance."""
        async with self.transaction_lock:
            await self.conn.execute("PRAGMA optimize;")
            await self.conn.commit()

    async def close(self):
        """Stop background tasks, flush caches, and close idempotently."""
        async with self._close_lock:
            self._stop_event.set()
            maintenance_task = self._maintenance_task
            self._maintenance_task = None
            if maintenance_task is not None:
                maintenance_task.cancel()
                await asyncio.gather(maintenance_task, return_exceptions=True)

            flush_task = self._flush_task
            self._flush_task = None
            if flush_task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(flush_task), timeout=5)
                except asyncio.TimeoutError:
                    flush_task.cancel()
                    await asyncio.gather(flush_task, return_exceptions=True)
                    log.warning("[DB] Timed out waiting for background flush task")
                except Exception:
                    log.exception("[DB] Background flush task failed during shutdown")

            conn = self.conn
            self.conn = None
            self._running = False
            if conn is not None:
                try:
                    await conn.close()
                finally:
                    self._secure_database_files()

            self.users = None
            self.rooms = None
            self.audit = None
            self.message_cache = None
            self.idlerpg = None
            self.outbox = None
            self.command_usage = None

    async def execute(
        self,
        query: str,
        params: tuple | None = None,
        auto_commit: bool = True,
    ):
        """Execute SQL while serializing writes on the shared connection."""
        if params is None:
            params = ()
        is_write = bool(_WRITE_PREFIX_RE.match(str(query)))
        if is_write:
            async with self.transaction_lock:
                cursor = await self.conn.execute(query, params)
                if auto_commit:
                    await self.conn.commit()
                return cursor
        return await self.conn.execute(query, params)

    async def fetch_one(self, query: str, params: tuple | None = None):
        """
        Execute a query and return a single row.
        """
        if params is None:
            params = ()

        async with self.conn.execute(query, params) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None
        return row

    async def fetch_all(self, query: str, params: tuple | None = None):
        """
        Execute a query and return all rows.
        """
        if params is None:
            params = ()

        async with self.conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return rows
