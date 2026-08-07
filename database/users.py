import asyncio
import json
import logging
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from utils.config import config

GLOBAL_JID = "__GLOBAL__"

log = logging.getLogger(__name__)


class PluginRuntimeStore:
    """
    Cache-backed runtime storage for plugin-specific user data.

    This store provides a per-plugin interface to the shared `users_runtime`
    table, which stores a single JSON blob per user (jid). The structure of
    that JSON is expected to be:

        {
            "plugins": {
                "<plugin_name>": { ... plugin-specific data ... }
            }
        }

    Key characteristics:
    - Read-through cache: data is loaded from the database on first access.
    - Write-behind cache: all mutations are applied in-memory and marked dirty.
    - No immediate database writes: persistence happens later via
      UserManager.flush_*.
    - Per-plugin isolation: each plugin only accesses its own namespace inside
      the shared JSON document.

    Important invariants:
    - `_runtime_cache[jid]` always contains the full JSON blob for that user.
    - `_dirty_runtime` tracks jids whose runtime data must be flushed.
    - The UserManager is responsible for writing cached data to the database,
      typically in the order: users → runtime.

    This design ensures:
    - High performance (fewer DB writes)
    - Consistent state across related tables
    - Compatibility with existing JSON-based SQL queries
    """

    def __init__(self, user_manager, plugin_name: str):
        self.um = user_manager
        self.plugin_name = plugin_name

    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------

    async def _load_from_db(self, jid: str) -> dict:
        """
        Load full runtime JSON for a user from the database.
        Ensures the returned structure always contains a "plugins" dict.
        """
        row = await self.um.db.fetch_one(
            "SELECT data, last_updated FROM users_runtime WHERE jid = ?",
            (jid,),
        )

        if not row:
            self.um._runtime_meta[jid] = None
            return {"plugins": {}}
        if row[0] is None:
            self.um._runtime_meta[jid] = None
            return {"plugins": {}}

        raw_data, last_updated = row

        try:
            data = json.loads(raw_data)
        except Exception:
            log.exception("[RUNTIME] Failed to decode JSON for %s", jid)
            return {"plugins": {}}

        if "plugins" not in data:
            data["plugins"] = {}

        # Store timestamp in meta
        self.um._runtime_meta[jid] = last_updated

        return data

    def _mark_runtime_dirty(self, jid: str) -> None:
        marker = getattr(self.um, "_mark_runtime_dirty", None)
        if marker is not None:
            marker(jid)
            return
        self.um._dirty_runtime.add(jid)

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------
    async def get_global(self, key, default=None):
        """
        Get plugin-global value (not tied to a user).
        """
        data = await self.get(GLOBAL_JID, key)
        return default if data is None else data

    async def set_global(self, key, value):
        """
        Set plugin-global value.
        """
        await self.set(GLOBAL_JID, key, value)

    async def delete_global(self, key):
        """Delete one plugin-global value from the runtime cache."""
        await self.delete(GLOBAL_JID, key)

    async def update_global(
        self,
        key,
        updater: Callable[[object], object],
        default=None,
    ):
        """
        Atomically update a plugin-global value in the runtime cache.

        The updater receives the current value or ``default`` and returns the
        replacement value.  A UserManager-level lock serializes these updates
        so read-modify-write callers do not overwrite concurrent cache changes
        within this bot process.
        """
        async with self.um._runtime_update_lock:
            current = await self.get_global(key, default)
            value = updater(current)
            await self.set_global(key, value)
            return value

    async def get(self, jid: str, key: str | None = None):
        """
        Retrieve runtime data for this plugin.

        If the user is not yet cached, data is loaded from the database.

        Args:
            jid: User JID
            key: Optional key within the plugin's data

        Returns:
            - Full plugin data dict if key is None
            - Value for the given key otherwise (or None if missing)
        """
        if jid not in self.um._runtime_cache:
            self.um._runtime_cache[jid] = await self._load_from_db(jid)
        self.um._touch_runtime_cache(jid)

        data = self.um._runtime_cache[jid]

        if "plugins" not in data:
            data["plugins"] = {}

        plugin_data = data["plugins"].setdefault(self.plugin_name, {})

        if key is None:
            return plugin_data

        return plugin_data.get(key)

    async def set(self, jid: str, key: str, value):
        """
        Set a runtime value for this plugin (cached only).

        Marks the user as dirty so the change will be persisted on flush.
        """

        # Get update time
        now = datetime.now(UTC).isoformat()

        if jid not in self.um._runtime_cache:
            self.um._runtime_cache[jid] = await self._load_from_db(jid)
        self.um._touch_runtime_cache(jid)

        data = self.um._runtime_cache[jid]

        if "plugins" not in data:
            data["plugins"] = {}

        plugin_data = data["plugins"].setdefault(self.plugin_name, {})

        plugin_data[key] = value

        self.um._runtime_meta[jid] = now
        self._mark_runtime_dirty(jid)

    async def delete(self, jid: str, key: str):
        """
        Delete a key from this plugin's runtime data (cached).
        """
        now = datetime.now(UTC).isoformat()

        if jid not in self.um._runtime_cache:
            self.um._runtime_cache[jid] = await self._load_from_db(jid)
        self.um._touch_runtime_cache(jid)

        data = self.um._runtime_cache[jid]

        plugin_data = data.get("plugins", {}).get(self.plugin_name, {})

        if key in plugin_data:
            del plugin_data[key]
            self.um._runtime_meta[jid] = now
            self._mark_runtime_dirty(jid)

    async def clear(self, jid: str):
        """
        Remove all runtime data for this plugin (cached).
        """
        now = datetime.now(UTC).isoformat()

        if jid not in self.um._runtime_cache:
            self.um._runtime_cache[jid] = await self._load_from_db(jid)
        self.um._touch_runtime_cache(jid)

        data = self.um._runtime_cache[jid]

        if "plugins" not in data:
            data["plugins"] = {}

        data["plugins"][self.plugin_name] = {}

        self.um._runtime_meta[jid] = now
        self._mark_runtime_dirty(jid)


class UserManager:
    """
    Manages users + in-memory cache.

    Responsibilities:
    - Cache users, runtime
    - Provide helper functions (get_value, set_value)
    - Manage users table

    Does NOT:
    - Write JSON blobs (handled by stores)
    - Parse JSON (handled by SQLite JSON1)
    """

    def __init__(self, db):
        self.db = db
        self._nick_index = {}
        self._nick_index_lock = asyncio.Lock()

        self._users_cache: dict[str, dict] = {}
        self._runtime_cache: dict[str, dict] = {}
        self._users_cache_access: dict[str, float] = {}
        self._runtime_cache_access: dict[str, float] = {}
        self._last_cache_prune = 0.0
        self._cache_evictions_users = 0
        self._cache_evictions_runtime = 0

        self._runtime_meta = {}
        self._runtime_update_lock = asyncio.Lock()
        self._flush_lock = asyncio.Lock()

        self._dirty_users = set()
        self._dirty_runtime = set()
        self._dirty_users_versions = {}
        self._dirty_runtime_versions = {}
        self._dirty_version = 0

    def _next_dirty_version(self) -> int:
        self._dirty_version += 1
        return self._dirty_version

    def _mark_user_dirty(self, jid: str) -> None:
        self._dirty_users.add(jid)
        self._dirty_users_versions[jid] = self._next_dirty_version()

    def _mark_runtime_dirty(self, jid: str) -> None:
        self._dirty_runtime.add(jid)
        self._dirty_runtime_versions[jid] = self._next_dirty_version()

    @staticmethod
    def _dirty_snapshot(dirty: set, versions: dict) -> dict:
        return {jid: versions.get(jid, 0) for jid in list(dirty)}

    @staticmethod
    def _clear_flushed_dirty(dirty: set, versions: dict, snapshot: dict) -> None:
        for jid, version in snapshot.items():
            if versions.get(jid, 0) == version:
                dirty.discard(jid)
                versions.pop(jid, None)

    @staticmethod
    def _cache_limit(key: str, default: int) -> int:
        try:
            return max(1, int(config.get(key, default) or default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _cache_ttl_seconds() -> float:
        try:
            return max(0.0, float(config.get("user_cache_ttl_seconds", 86400) or 0))
        except (TypeError, ValueError):
            return 86400.0

    @staticmethod
    def _cache_prune_interval_seconds() -> float:
        try:
            return max(1.0, float(config.get("user_cache_prune_interval_seconds", 300) or 300))
        except (TypeError, ValueError):
            return 300.0

    def _touch_user_cache(self, jid: str, *, now: float | None = None) -> None:
        self._users_cache_access[str(jid)] = time.monotonic() if now is None else float(now)
        self._maybe_prune_caches(now=now)

    def _touch_runtime_cache(self, jid: str, *, now: float | None = None) -> None:
        self._runtime_cache_access[str(jid)] = time.monotonic() if now is None else float(now)
        self._maybe_prune_caches(now=now)

    def _maybe_prune_caches(self, *, now: float | None = None, force: bool = False) -> None:
        current = time.monotonic() if now is None else float(now)
        if not force and current - self._last_cache_prune < self._cache_prune_interval_seconds():
            return
        self._last_cache_prune = current
        self._cache_evictions_users += self._prune_one_cache(
            cache=self._users_cache,
            access=self._users_cache_access,
            dirty=self._dirty_users,
            maximum=self._cache_limit("user_cache_max_entries", 5000),
            ttl=self._cache_ttl_seconds(),
            now=current,
            pinned=set(),
        )
        runtime_evicted = self._prune_one_cache(
            cache=self._runtime_cache,
            access=self._runtime_cache_access,
            dirty=self._dirty_runtime,
            maximum=self._cache_limit("user_runtime_cache_max_entries", 5000),
            ttl=self._cache_ttl_seconds(),
            now=current,
            pinned={GLOBAL_JID},
        )
        self._cache_evictions_runtime += runtime_evicted
        for jid in tuple(self._runtime_meta):
            if jid not in self._runtime_cache:
                self._runtime_meta.pop(jid, None)

    @staticmethod
    def _prune_one_cache(
        *,
        cache: dict[str, dict],
        access: dict[str, float],
        dirty: set[str],
        maximum: int,
        ttl: float,
        now: float,
        pinned: set[str],
    ) -> int:
        """Evict only clean LRU/expired entries; dirty state is never dropped."""
        removed = 0
        if ttl > 0:
            expired = sorted(
                jid
                for jid, touched in access.items()
                if jid in cache
                and jid not in dirty
                and jid not in pinned
                and now - touched >= ttl
            )
            for jid in expired:
                cache.pop(jid, None)
                access.pop(jid, None)
                removed += 1

        excess = max(0, len(cache) - maximum)
        if excess:
            candidates = sorted(
                (touched, jid)
                for jid, touched in access.items()
                if jid in cache and jid not in dirty and jid not in pinned
            )
            for _touched, jid in candidates[:excess]:
                cache.pop(jid, None)
                access.pop(jid, None)
                removed += 1
        return removed

    def prune_caches(self) -> dict[str, int]:
        """Force one cache-prune pass and return current diagnostics."""
        self._maybe_prune_caches(force=True)
        return self.cache_state()

    def cache_state(self) -> dict[str, int]:
        """Return bounded-cache diagnostics without exposing user identifiers."""
        return {
            "users": len(self._users_cache),
            "runtime": len(self._runtime_cache),
            "dirty_users": len(self._dirty_users),
            "dirty_runtime": len(self._dirty_runtime),
            "user_limit": self._cache_limit("user_cache_max_entries", 5000),
            "runtime_limit": self._cache_limit("user_runtime_cache_max_entries", 5000),
            "evicted_users": self._cache_evictions_users,
            "evicted_runtime": self._cache_evictions_runtime,
        }

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def ensure_global_exists(self):
        if await self.get(GLOBAL_JID) is None:
            await self.create(GLOBAL_JID, "__global__")

    async def init(self, *, commit: bool = True) -> None:
        """Create user tables through the central nested-safe DB API."""
        del commit
        async with self.db.transaction(label="users_init") as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    jid TEXT PRIMARY KEY,
                    nickname TEXT,
                    role INTEGER DEFAULT 80,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    registered INTEGER DEFAULT FALSE
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users_runtime (
                    jid TEXT PRIMARY KEY,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    data TEXT DEFAULT '{}' NOT NULL,
                    FOREIGN KEY (jid)
                        REFERENCES users(jid)
                        ON DELETE CASCADE
                        ON UPDATE CASCADE
                )
                """
            )

        await self.ensure_global_exists()
        index = await self.plugin("users").get_global("_nick_index")
        if isinstance(index, dict):
            self._nick_index = {
                nick: set(jids) if isinstance(jids, list) else jids
                for nick, jids in index.items()
            }

    # ------------------------------------------------------------------
    # Users (DB + cache)
    # ------------------------------------------------------------------

    async def create(self, jid, nickname=None):
        now = datetime.now(UTC).isoformat()
        if jid not in self._users_cache:
            self._users_cache[jid] = {
                "jid": jid,
                "nickname": nickname,
                "role": 80,
                "created_at": now,
                "last_seen": now,
                "registered": True,
            }
            self._mark_user_dirty(jid)
            self._touch_user_cache(jid)

    async def get(self, jid):
        if jid in self._users_cache:
            self._touch_user_cache(jid)
            return self._users_cache[jid]

        row = await self.db.fetch_one(
            "SELECT * FROM users WHERE jid=?",
            (jid,),
        )

        if not row:
            return None

        user = dict(row)
        self._users_cache[jid] = user
        self._touch_user_cache(jid)
        return user

    async def set(self, jid, key, value):
        user = await self.get(jid)
        if not user:
            return None
        user[key] = value
        self._mark_user_dirty(jid)
        return user

    async def list(self):
        """Return all users as dictionaries, including cached updates."""
        rows = [
            dict(row)
            for row in await self.db.fetch_all(
                "SELECT * FROM users ORDER BY role ASC, jid ASC"
            )
        ]
        seen = {row["jid"] for row in rows}

        for jid, user in self._users_cache.items():
            if jid in seen:
                rows = [user if row["jid"] == jid else row for row in rows]
            else:
                rows.append(user)

        return sorted(
            rows,
            key=lambda row: (int(row.get("role", 80)), row.get("jid", "")),
        )

    async def update_last_seen(self, jid):
        now = datetime.now(UTC).isoformat()
        await self.set(jid, "last_seen", now)

    async def delete(self, jid):
        # 1. Delete atomically through the shared DatabaseManager boundary.
        async with self.db.transaction(label="users_delete") as conn:
            await conn.execute("DELETE FROM users WHERE jid = ?", (jid,))
            await conn.execute("DELETE FROM users_runtime WHERE jid = ?", (jid,))

        # 2. Remove from caches
        self._users_cache.pop(jid, None)
        self._runtime_cache.pop(jid, None)
        self._users_cache_access.pop(jid, None)
        self._runtime_cache_access.pop(jid, None)
        self._runtime_meta.pop(jid, None)

        # 3. Clean dirty flags
        self._dirty_users.discard(jid)
        self._dirty_runtime.discard(jid)
        self._dirty_users_versions.pop(jid, None)
        self._dirty_runtime_versions.pop(jid, None)

        # 4. Remove from _nick_index
        for nick in list(self._nick_index.keys()):
            jids = self._nick_index[nick]
            # Convert to set if needed (for robustness)
            if not isinstance(jids, set):
                jids = set(jids) if isinstance(jids, list) else {jids}

            if jid in jids:
                jids.discard(jid)
                if not jids:
                    del self._nick_index[nick]
                else:
                    self._nick_index[nick] = jids

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def get_value(self, data, key_path):
        keys = key_path.split(".")
        value = data

        for k in keys:
            if not isinstance(value, dict):
                return None
            value = value.get(k)
            if value is None:
                return None

        return value

    async def set_value(self, cache, dirty, jid, key_path, value):
        data = cache.setdefault(jid, {})

        keys = key_path.split(".")
        target = data

        for k in keys[:-1]:
            target = target.setdefault(k, {})

        target[keys[-1]] = value
        dirty.add(jid)

    # ------------------------------------------------------------------
    # FLUSH LOGIC
    # ------------------------------------------------------------------

    async def _flush_users_to(self, conn, jids: Iterable[str]) -> None:
        for jid in list(jids):
            user = self._users_cache.get(jid)
            if user is None:
                continue
            await conn.execute(
                """
                INSERT INTO users (jid, nickname, role, last_seen, registered)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(jid) DO UPDATE SET
                    nickname=excluded.nickname,
                    role=excluded.role,
                    last_seen=excluded.last_seen,
                    registered=excluded.registered
                """,
                (
                    user["jid"],
                    user.get("nickname"),
                    user.get("role", 80),
                    user.get("last_seen"),
                    user.get("registered", 0),
                ),
            )

    async def flush_users(self, jids: Iterable[str] | None = None) -> None:
        """Persist selected cached users atomically."""
        selected = list(self._dirty_users if jids is None else jids)
        if not selected:
            return
        async with self.db.transaction(label="users_flush_users") as conn:
            await self._flush_users_to(conn, selected)

    async def _write_runtime_to(self, conn, jid: str, data: dict) -> None:
        timestamp = self._runtime_meta.get(jid)
        await conn.execute(
            """
            INSERT INTO users_runtime (jid, last_updated, data)
            VALUES (?, ?, ?)
            ON CONFLICT(jid) DO UPDATE SET
                last_updated = excluded.last_updated,
                data = excluded.data
            """,
            (jid, timestamp, json.dumps(data)),
        )

    async def _write_runtime(self, jid: str, data: dict) -> None:
        """Persist one runtime JSON blob atomically."""
        async with self.db.transaction(label="users_runtime_write") as conn:
            await self._write_runtime_to(conn, jid, data)

    async def flush_all(self) -> None:
        """Flush dirty user/runtime cache state in one nested-safe transaction."""
        async with self._flush_lock:
            index = getattr(self, "_nick_index", None)
            if index is not None:
                serializable_index = {
                    nick: list(jids) if isinstance(jids, set) else jids
                    for nick, jids in index.items()
                }
                await self.plugin("users").set_global("_nick_index", serializable_index)

            if not (self._dirty_users or self._dirty_runtime):
                self._maybe_prune_caches(force=True)
                return

            dirty_users = self._dirty_snapshot(
                self._dirty_users, self._dirty_users_versions
            )
            dirty_runtime = self._dirty_snapshot(
                self._dirty_runtime, self._dirty_runtime_versions
            )

            async with self.db.transaction(label="users_flush_all") as conn:
                if dirty_users:
                    await self._flush_users_to(conn, dirty_users.keys())
                for jid, version in dirty_runtime.items():
                    is_still_dirty = jid in self._dirty_runtime
                    is_same_version = self._dirty_runtime_versions.get(jid) == version
                    data = self._runtime_cache.get(jid)
                    if data is None and not is_still_dirty:
                        continue
                    if data is None:
                        data = {"plugins": {}}
                    if is_still_dirty or is_same_version:
                        await self._write_runtime_to(conn, jid, data)

            self._clear_flushed_dirty(
                self._dirty_users, self._dirty_users_versions, dirty_users
            )
            self._clear_flushed_dirty(
                self._dirty_runtime, self._dirty_runtime_versions, dirty_runtime
            )
            self._maybe_prune_caches(force=True)
            log.debug("[DB] ✅ UserManager.flush_all() SUCCESSFUL!")

    # ------------------------------------------------------------------
    # Plugin API
    # ------------------------------------------------------------------

    def plugin(self, plugin_name: str):
        return PluginRuntimeStore(self, plugin_name)
