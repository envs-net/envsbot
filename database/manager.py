import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from utils.config import config
from utils.file_security import ensure_private_file
from utils.logging_helpers import kv
from utils.task_supervisor import ExpectedTaskExit

from .audit import AuditLog
from .command_usage import CommandUsageStore
from .idlerpg import IdleRPGStateStore
from .locking import AsyncRLock
from .message_cache import MessageCacheStore
from .migrations import available_migrations
from .outbox import OutboxStore
from .rooms import Rooms
from .users import UserManager

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

    def __init__(
        self,
        path: str,
        flush_interval: int = 60,
        *,
        task_supervisor: Any | None = None,
    ):

        self.path = path
        self.task_supervisor = task_supervisor
        self.conn: aiosqlite.Connection | None = None

        self.users: UserManager | None = None
        self.rooms: Rooms | None = None
        self.audit: AuditLog | None = None
        self.message_cache: MessageCacheStore | None = None
        self.idlerpg: IdleRPGStateStore | None = None
        self.outbox: OutboxStore | None = None
        self.command_usage: CommandUsageStore | None = None

        self.flush_interval = flush_interval

        self._flush_task: asyncio.Task[Any] | None = None
        self._maintenance_task: asyncio.Task[Any] | None = None
        self.maintenance_state: dict[str, Any] = {
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
        self._savepoint_counter = 0

    def _connection(self) -> aiosqlite.Connection:
        """Return the live connection or fail with a clear lifecycle error."""
        conn = self.conn
        if conn is None:
            raise RuntimeError("database is not connected")
        return conn

    @asynccontextmanager
    async def transaction(
        self,
        *,
        label: str = "transaction",
    ) -> AsyncIterator[aiosqlite.Connection]:
        """Serialize one nested-safe SQLite write transaction.

        SAVEPOINT is deliberately used even for top-level writes.  SQLite
        allows SAVEPOINT inside an existing transaction, so callers remain
        safe if a legacy path already opened a transaction on the shared
        connection.  The task-reentrant lock prevents other coroutines from
        observing or committing this unit of work.
        """
        conn = self._connection()
        safe_label = re.sub(r"[^A-Za-z0-9_]", "_", str(label or "transaction"))
        async with self.transaction_lock:
            self._savepoint_counter += 1
            savepoint = f"envsbot_{safe_label}_{self._savepoint_counter}"
            await conn.execute(f"SAVEPOINT {savepoint}")
            try:
                yield conn
            except BaseException:
                await conn.execute(f"ROLLBACK TO {savepoint}")
                await conn.execute(f"RELEASE {savepoint}")
                raise
            else:
                await conn.execute(f"RELEASE {savepoint}")

    async def write(
        self,
        query: str,
        params: Sequence[Any] = (),
        *,
        label: str = "write",
    ) -> aiosqlite.Cursor:
        """Execute one atomic write through the shared transaction boundary."""
        async with self.transaction(label=label) as conn:
            return await conn.execute(query, tuple(params))

    async def write_many(
        self,
        query: str,
        rows: Sequence[Sequence[Any]],
        *,
        label: str = "write_many",
    ) -> aiosqlite.Cursor:
        """Execute an atomic executemany operation."""
        async with self.transaction(label=label) as conn:
            return await conn.executemany(query, [tuple(row) for row in rows])

    def _start_service(
        self,
        factory,
        *,
        name: str,
        fallback_factory=None,
    ) -> asyncio.Task[Any]:
        """Start a core DB worker through the shared supervisor when available."""
        supervisor = self.task_supervisor
        creator = getattr(supervisor, "create_resilient", None)
        if callable(creator):
            return creator(
                "_runtime",
                factory,
                name=name,
                service=True,
            )
        fallback = fallback_factory or factory
        return asyncio.create_task(fallback(), name=name)

    def _heartbeat(self, name: str) -> None:
        heartbeat = getattr(self.task_supervisor, "heartbeat", None)
        if callable(heartbeat):
            heartbeat("_runtime", name)

    async def _supervised_flush_loop(self) -> None:
        await self._flush_loop()
        if self._stop_event.is_set():
            raise ExpectedTaskExit("database flush stop requested")

    async def _supervised_maintenance_loop(self) -> None:
        await self._maintenance_loop()
        if self._stop_event.is_set():
            raise ExpectedTaskExit("database maintenance stop requested")

    async def connect(
        self,
        *,
        run_migrations: bool = True,
        start_background: bool = True,
        enforce_schema_compatibility: bool = True,
    ) -> None:
        """Open the database connection and optionally migrate/start workers."""
        if self.conn is not None:
            return

        self._stop_event = asyncio.Event()
        self._running = False
        try:
            conn = await aiosqlite.connect(self.path)
            self.conn = conn
            conn.row_factory = aiosqlite.Row
            self._secure_database_files()

            # SQLite runtime pragmas. Keep these near connect() so every process
            # consistently applies them before table managers start using the DB.
            await conn.execute("PRAGMA foreign_keys = ON;")
            try:
                busy_timeout = max(0, int(config.get("database_busy_timeout_ms", 5000) or 0))
            except Exception:
                busy_timeout = 5000
            await conn.execute(f"PRAGMA busy_timeout = {busy_timeout};")
            if config.get("database_wal_enabled", False):
                await conn.execute("PRAGMA journal_mode = WAL;")
                self._secure_database_files()

            cursor = await conn.execute("PRAGMA foreign_keys;")
            row = await cursor.fetchone()
            if row is None or int(row["foreign_keys"]) != 1:
                raise RuntimeError("Failed to enable foreign keys")

            self.users = UserManager(self)
            self.rooms = Rooms(self)
            self.audit = AuditLog(self)
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
                self._flush_task = self._start_service(
                    self._supervised_flush_loop,
                    name="database-flush",
                    fallback_factory=self._flush_loop,
                )
                self._maintenance_task = self._start_service(
                    self._supervised_maintenance_loop,
                    name="database-maintenance",
                    fallback_factory=self._maintenance_loop,
                )
        except Exception:
            failed_conn = self.conn
            self.conn = None
            self.users = None
            self.rooms = None
            self.audit = None
            self.message_cache = None
            self.idlerpg = None
            self.outbox = None
            self.command_usage = None
            self._running = False
            if failed_conn is not None:
                try:
                    await failed_conn.close()
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
        """Create/upgrade migration bookkeeping through the shared DB API."""
        async with self.transaction(label="schema_migrations_init") as conn:
            await conn.execute(
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
                for row in await (
                    await conn.execute("PRAGMA table_info(schema_migrations)")
                ).fetchall()
            }
            for name, ddl in (
                ("duration_ms", "INTEGER NOT NULL DEFAULT 0"),
                ("status", "TEXT NOT NULL DEFAULT 'applied'"),
                ("error", "TEXT"),
            ):
                if name not in columns:
                    await conn.execute(
                        f"ALTER TABLE schema_migrations ADD COLUMN {name} {ddl}"
                    )
            await conn.execute(
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

    async def mark_migration_applied(
        self,
        version: str,
        *,
        duration_ms: int = 0,
        commit: bool = True,
    ) -> None:
        query = """
            INSERT INTO schema_migrations (version, duration_ms, status, error)
            VALUES (?, ?, 'applied', NULL)
            ON CONFLICT(version) DO UPDATE SET
                duration_ms=excluded.duration_ms, status='applied', error=NULL
            """
        params = (version, max(0, int(duration_ms)))
        if commit:
            await self.write(query, params, label="migration_mark_applied")
        else:
            # Used only while run_migrations() already owns transaction().
            await self._connection().execute(query, params)

    async def _record_migration_history(
        self,
        version: str,
        *,
        started_at: str,
        duration_ms: int,
        status: str,
        error: str | None = None,
    ) -> None:
        await self.write(
            """
            INSERT INTO schema_migration_history (
                version, started_at, duration_ms, status, error
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (version, started_at, max(0, int(duration_ms)), status, error),
            label="migration_history",
        )

    async def list_migrations(self) -> list[aiosqlite.Row]:
        return await self.fetch_all(
            "SELECT version, applied_at, duration_ms, status, error "
            "FROM schema_migrations ORDER BY version"
        )

    async def migration_history(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.fetch_all(
            "SELECT version, started_at, duration_ms, status, error "
            "FROM schema_migration_history ORDER BY id DESC LIMIT ?",
            (max(1, min(200, int(limit))),),
        )
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
        class _RollbackProbe(RuntimeError):
            pass

        try:
            async with self.transaction(label="preflight_rw") as conn:
                await conn.execute(
                    "CREATE TEMP TABLE IF NOT EXISTS envsbot_preflight_check (value INTEGER)"
                )
                await conn.execute(
                    "INSERT INTO envsbot_preflight_check (value) VALUES (1)"
                )
                raise _RollbackProbe
        except _RollbackProbe:
            return

    def _database_backup_path(self, *, pre_migration: bool = False) -> Path | None:
        raw = str(self.path or "")
        if raw in {"", ":memory:"} or raw.startswith("file:"):
            return None
        from utils.backups import backup_dir

        directory = backup_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        prefix = "envsbot-db-pre-migration" if pre_migration else "envsbot-db-backup"
        return directory / f"{prefix}-{stamp}.sqlite3"

    async def backup_database(
        self,
        *,
        destination: Path | None = None,
        pre_migration: bool = False,
    ) -> Path | None:
        """Create and verify a consistent SQLite snapshot without stopping."""
        target = destination or self._database_backup_path(
            pre_migration=pre_migration
        )
        if target is None:
            return None
        target = Path(target).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        async with self.transaction_lock:
            target_conn = await aiosqlite.connect(str(target))
            try:
                await self._connection().backup(target_conn)
                await target_conn.commit()
            finally:
                await target_conn.close()
        ensure_private_file(target)
        from utils.backups import (
            prune_migration_snapshots,
            verify_sqlite_snapshot,
        )

        verification = await asyncio.to_thread(verify_sqlite_snapshot, target)
        if not bool(verification.get("ok")):
            target.unlink(missing_ok=True)
            errors = ", ".join(
                str(item) for item in verification.get("errors", [])
            )
            snapshot_kind = "pre-migration" if pre_migration else "database"
            raise RuntimeError(
                f"{snapshot_kind} snapshot failed verification: "
                + (errors or "unknown error")
            )
        if pre_migration:
            await asyncio.to_thread(
                prune_migration_snapshots,
                directory=target.parent,
            )
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
            backup = await self.backup_database(pre_migration=True)
            if backup is not None:
                log.info("[DB] Pre-migration snapshot created: %s", backup)

        completed: list[str] = []
        async with self.transaction_lock:
            for migration in pending:
                started_at = datetime.now(UTC).isoformat(timespec="seconds")
                started = time.monotonic()
                savepoint = "migration_" + re.sub(r"[^a-zA-Z0-9_]", "_", migration.version)
                log.info(
                    "[DB] event=migration status=applying %s",
                    kv(version=migration.version, description=migration.description),
                )
                try:
                    async with self.transaction(label=savepoint):
                        await migration.run(self)
                        duration_ms = int((time.monotonic() - started) * 1000)
                        await self.mark_migration_applied(
                            migration.version,
                            duration_ms=duration_ms,
                            commit=False,
                        )
                except Exception as exc:
                    duration_ms = int((time.monotonic() - started) * 1000)
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

    async def _flush_loop(self) -> None:
        """Background loop that flushes data periodically with retry logic."""
        try:
            while not self._stop_event.is_set():
                self._heartbeat("database-flush")
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.flush_interval
                    )
                except TimeoutError:
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
            # WAL checkpointing must not run inside a SQLite transaction. Hold
            # the shared lock so no other task can open a write SAVEPOINT while
            # optimize/checkpoint run, then let retention stores use the normal
            # transaction API for their DELETE operations.
            async with self.transaction_lock:
                conn = self._connection()
                await conn.execute("PRAGMA optimize;")
                if config.get("database_wal_enabled", False):
                    cursor = await conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
                    row = await cursor.fetchone()
                    checkpoint = tuple(row) if row is not None else None
            retention_days = int(config.get("command_usage_retention_days", 365) or 0)
            if self.command_usage is not None:
                await self.command_usage.prune(retention_days=retention_days)
            if self.outbox is not None:
                await self.outbox.prune_dead(
                    retention_days=int(config.get("outbox_dead_retention_days", 30) or 0)
                )
            if self.idlerpg is not None:
                idlerpg_config = config.get("idlerpg", {})
                retention_days = (
                    int(idlerpg_config.get("event_retention_days", 90) or 0)
                    if isinstance(idlerpg_config, dict)
                    else 90
                )
                await self.idlerpg.prune_events(retention_days=retention_days)
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
                self._heartbeat("database-maintenance")
                stop_requested = True
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=interval,
                    )
                except TimeoutError:
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
        users = self.users
        if users is None:
            return True
        for attempt in range(max_retries):
            try:
                await users.flush_all()
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

    async def flush(self) -> None:
        """Manually flush cached data, raising when persistence fails."""
        if self.users:
            await self._flush_with_retry(raise_on_failure=True)

    async def integrity_check(self) -> list[str]:
        """Run SQLite PRAGMA integrity_check and return result rows."""
        rows = await self.fetch_all("PRAGMA integrity_check;")
        result: list[str] = []
        for row in rows:
            try:
                result.append(str(row[0]))
            except Exception:
                result.append(str(row))
        return result

    async def foreign_key_check(self) -> list[dict[str, Any]]:
        """Return SQLite foreign-key violations."""
        rows = await self.fetch_all("PRAGMA foreign_key_check;")
        return [dict(row) for row in rows]

    async def optimize(self) -> None:
        """Run SQLite PRAGMA optimize without opening an application transaction."""
        async with self.transaction_lock:
            await self._connection().execute("PRAGMA optimize;")

    async def stop_background_tasks(self, *, timeout: float = 10.0) -> None:
        """Gracefully stop supervised DB workers before global task cancellation."""
        self._stop_event.set()
        tasks = [
            task
            for task in (self._flush_task, self._maintenance_task)
            if task is not None
        ]
        self._flush_task = None
        self._maintenance_task = None
        if not tasks:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=max(0.1, float(timeout)),
            )
        except TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            log.warning("[DB] Timed out waiting for supervised database workers")

    async def close(self) -> None:
        """Stop background tasks, flush caches, and close idempotently."""
        async with self._close_lock:
            await self.stop_background_tasks(timeout=5.0)
            if self.users is not None:
                await self._flush_with_retry(raise_on_failure=False)

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
        params: tuple[Any, ...] | None = None,
        auto_commit: bool = True,
    ) -> aiosqlite.Cursor:
        """Compatibility SQL helper backed by the hardened DB API.

        New code should prefer :meth:`write`, :meth:`fetch_one`,
        :meth:`fetch_all` or :meth:`transaction`.
        """
        values = () if params is None else params
        is_write = bool(_WRITE_PREFIX_RE.match(str(query)))
        if is_write and auto_commit:
            return await self.write(query, values, label="compat_execute")
        conn = self._connection()
        if is_write:
            # ``auto_commit=False`` is retained only for callers that are
            # already inside ``transaction()``/migration savepoints.
            async with self.transaction_lock:
                return await conn.execute(query, values)
        async with self.transaction_lock:
            return await conn.execute(query, values)

    async def fetch_one(
        self,
        query: str,
        params: tuple[Any, ...] | None = None,
    ) -> aiosqlite.Row | None:
        """Execute a read without crossing another task's write transaction."""
        values = () if params is None else params
        async with self.transaction_lock:
            conn = self._connection()
            cursor = (
                await conn.execute(query, values)
                if values
                else await conn.execute(query)
            )
            return await cursor.fetchone()

    async def fetch_all(
        self,
        query: str,
        params: tuple[Any, ...] | None = None,
    ) -> list[aiosqlite.Row]:
        """Execute a read and return all rows under the shared DB lock."""
        values = () if params is None else params
        async with self.transaction_lock:
            conn = self._connection()
            cursor = (
                await conn.execute(query, values)
                if values
                else await conn.execute(query)
            )
            rows = await cursor.fetchall()
        return list(rows)
