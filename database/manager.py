import asyncio
import logging
import aiosqlite

from utils.config import config

from .users import UserManager
from .rooms import Rooms
from .audit import AuditLog
from .migrations import available_migrations

# logger for this module
log = logging.getLogger(__name__)


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

        self.flush_interval = flush_interval

        self._flush_task = None
        self._running = False

    async def connect(self):
        """Open the database connection and initialize tables."""

        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row

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

        # (optional but clean)
        cursor = await self.conn.execute("PRAGMA foreign_keys;")
        row = await cursor.fetchone()
        if row["foreign_keys"] != 1:
            raise RuntimeError("Failed to enable foreign keys")

        self.users = UserManager(self.conn)
        self.rooms = Rooms(self.conn)
        self.audit = AuditLog(self.conn)

        await self._init_schema_migrations()
        await self.run_migrations()

        # add asyncio sqlite3 stop event
        self._stop_event = asyncio.Event()

        # start background flush task
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())


    async def _init_schema_migrations(self):
        """Create the lightweight migration bookkeeping table."""
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.conn.commit()

    async def mark_migration_applied(self, version: str):
        """Mark a schema migration as applied.

        envsbot currently has simple idempotent table creation.  This table is
        intentionally tiny but gives future schema changes a safe place to land.
        """
        await self.conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
            (version,),
        )
        await self.conn.commit()

    async def list_migrations(self):
        """Return applied schema migrations."""
        cursor = await self.conn.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        )
        return await cursor.fetchall()


    async def applied_migration_versions(self) -> set[str]:
        """Return migration versions that have already been applied."""
        rows = await self.list_migrations()
        return {row["version"] for row in rows}

    async def run_migrations(self):
        """Run all pending database migrations in order."""
        applied = await self.applied_migration_versions()
        for migration in available_migrations():
            if migration.version in applied:
                continue
            log.info(
                "[DatabaseManager] Applying migration %s: %s",
                migration.version,
                migration.description,
            )
            await migration.run(self)
            await self.mark_migration_applied(migration.version)
            applied.add(migration.version)

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

    async def _flush_with_retry(self, max_retries: int = 3,
                                backoff: float = 1.0):
        """
        Flush with exponential backoff retry logic.

        Args:
            max_retries: Maximum number of retry attempts
            backoff: Initial backoff in seconds (exponential growth)
        """
        for attempt in range(max_retries):
            try:
                await self.users.flush_all()
                return  # Success
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

    async def flush(self):
        """Manually flush cached data with retry logic."""
        if self.users:
            await self._flush_with_retry()

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

    async def optimize(self) -> None:
        """Run SQLite PRAGMA optimize for opportunistic maintenance."""
        await self.conn.execute("PRAGMA optimize;")
        await self.conn.commit()

    async def close(self):
        """
        Stop background tasks, flush caches, and close the database.
        """

        # signal shutdown
        self._stop_event.set()

        flush_task = self._flush_task
        if flush_task:
            await asyncio.wait_for(asyncio.shield(flush_task), timeout=5)

        if self.conn:
            await self.conn.close()

    async def execute(self, query: str, params: tuple | None = None,
                      auto_commit: bool = True):
        """
        Execute a write query (INSERT/UPDATE/DELETE).

        Args:
            query: SQL query string
            params: Query parameters (optional)
            auto_commit: If True, automatically commits. If False, caller
            must commit

        When used within an explicit transaction (BEGIN...COMMIT),
        set auto_commit=False to prevent premature commits.
        """
        if params is None:
            params = ()

        cursor = await self.conn.execute(query, params)

        # Only commit when desired and not within a transaction
        if auto_commit:
            await self.conn.commit()

        return cursor

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
