import json
import aiosqlite
import pytest

from database.users import ProfileStore, PluginRuntimeStore, GLOBAL_JID


class FakeUserManager:
    """
    Minimal fake user manager providing the DB handle and the
    cache/meta structures used by ProfileStore and PluginRuntimeStore.
    """

    def __init__(self, conn):
        self.db = conn

        # profile-related caches/meta
        self._profile_cache = {}
        self._profile_meta = {}
        self._dirty_profiles = set()

        # runtime-related caches/meta
        self._runtime_cache = {}
        self._runtime_meta = {}
        self._dirty_runtime = set()


# ----------------------------
# ProfileStore tests (kept)
# ----------------------------
@pytest.mark.asyncio
async def test_profilestore_load_no_row_and_null_and_valid_and_invalid():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    try:
        await conn.execute(
            "CREATE TABLE users_profile (jid TEXT PRIMARY KEY, data TEXT, last_updated TEXT)"
        )
        await conn.commit()

        um = FakeUserManager(conn)
        ps = ProfileStore(um)

        # no row
        got = await ps._load_from_db("alice@example")
        assert got == {"plugins": {}}
        assert um._profile_meta["alice@example"] is None

        # NULL data row
        await conn.execute(
            "INSERT INTO users_profile (jid, data, last_updated) VALUES (?, ?, ?)",
            ("bob@example", None, None),
        )
        await conn.commit()
        got2 = await ps._load_from_db("bob@example")
        assert got2 == {"plugins": {}}
        assert um._profile_meta["bob@example"] is None

        # valid JSON row
        payload = {"plugins": {"p": {"x": 1}}, "extra": "ok"}
        await conn.execute(
            "INSERT OR REPLACE INTO users_profile (jid, data, last_updated) VALUES (?, ?, ?)",
            ("carol@example", json.dumps(payload), "2025-01-01T00:00:00Z"),
        )
        await conn.commit()
        got3 = await ps._load_from_db("carol@example")
        assert got3 == payload
        assert "carol@example" not in um._profile_meta

        # invalid JSON row -> empty dict and meta set to last_updated
        await conn.execute(
            "INSERT OR REPLACE INTO users_profile (jid, data, last_updated) VALUES (?, ?, ?)",
            ("dave@example", "not-a-json", "2030-02-02T12:34:56Z"),
        )
        await conn.commit()
        got4 = await ps._load_from_db("dave@example")
        assert got4 == {}
        assert um._profile_meta["dave@example"] == "2030-02-02T12:34:56Z"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_profilestore_get_delete_and_clear_cache_mutation():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    try:
        await conn.execute(
            "CREATE TABLE users_profile (jid TEXT PRIMARY KEY, data TEXT, last_updated TEXT)"
        )
        await conn.commit()

        um = FakeUserManager(conn)
        ps = ProfileStore(um)

        jid = "eve@example"
        um._profile_cache[jid] = {"k1": "v1", "k2": 2}

        full = await ps.get(jid)
        assert full["k1"] == "v1"

        val = await ps.get(jid, "k2")
        assert val == 2

        await ps.delete(jid, "k2")
        assert "k2" not in um._profile_cache[jid]
        assert jid in um._dirty_profiles

        await ps.clear(jid)
        assert um._profile_cache[jid] == {}
        assert jid in um._dirty_profiles
    finally:
        await conn.close()


# ---------------------------------------
# PluginRuntimeStore: thorough tests
# ---------------------------------------
@pytest.mark.asyncio
async def test_pluginruntimestore_load_variants_and_meta_behavior():
    """
    Test loading from DB:
    - missing row -> returns {"plugins": {}} and sets profile_meta to None
      (per implementation)
    - NULL data -> treated as empty and profile_meta set to None
    - valid JSON without 'plugins' -> 'plugins' injected and runtime_meta set
      to last_updated
    - invalid JSON -> returns {"plugins": {}} and does not set runtime_meta
    """
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    try:
        await conn.execute(
            "CREATE TABLE users_runtime (jid TEXT PRIMARY KEY, data TEXT, last_updated TEXT)"
        )
        await conn.commit()

        um = FakeUserManager(conn)
        prs = PluginRuntimeStore(um, plugin_name="myp")

        # missing row
        missing = await prs._load_from_db("noone@example")
        assert missing == {"plugins": {}}
        # implementation sets profile_meta (oddly) for missing runtime rows
        assert um._profile_meta["noone@example"] is None

        # NULL data
        await conn.execute(
            "INSERT INTO users_runtime (jid, data, last_updated) VALUES (?, ?, ?)",
            ("nullrow@example", None, None),
        )
        await conn.commit()
        null_loaded = await prs._load_from_db("nullrow@example")
        assert null_loaded == {"plugins": {}}
        assert um._profile_meta["nullrow@example"] is None

        # valid JSON WITHOUT 'plugins' -> plugin loader should add 'plugins' key
        payload_without_plugins = {"some": "value"}
        last_updated = "2024-10-10T10:10:10Z"
        await conn.execute(
            "INSERT OR REPLACE INTO users_runtime (jid, data, last_updated) VALUES (?, ?, ?)",
            ("no_plugins@example", json.dumps(payload_without_plugins), last_updated),
        )
        await conn.commit()
        got = await prs._load_from_db("no_plugins@example")
        assert isinstance(got, dict)
        # 'plugins' must exist (injected by implementation)
        assert "plugins" in got
        # runtime_meta should be set to last_updated for successful parse
        assert um._runtime_meta["no_plugins@example"] == last_updated

        # invalid JSON -> returns {"plugins": {}} and DOES NOT set runtime_meta
        await conn.execute(
            "INSERT OR REPLACE INTO users_runtime (jid, data, last_updated) VALUES (?, ?, ?)",
            ("badjson@example", "not-json", "2029-09-09T09:09:09Z"),
        )
        await conn.commit()
        bad = await prs._load_from_db("badjson@example")
        assert bad == {"plugins": {}}
        assert "badjson@example" not in um._runtime_meta
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_pluginruntimestore_get_set_delete_and_globals_modify_cache_and_meta():
    """
    Exercise the public API:
    - get on uncached jid loads from DB and returns plugin dict
    - set updates _runtime_cache, _runtime_meta (to a timestamp string), and
      marks dirty
    - get with key returns value
    - delete removes key and marks dirty
    - get_global/set_global use GLOBAL_JID
    """
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    try:
        await conn.execute(
            "CREATE TABLE users_runtime (jid TEXT PRIMARY KEY, data TEXT, last_updated TEXT)"
        )
        await conn.commit()

        um = FakeUserManager(conn)
        prs = PluginRuntimeStore(um, plugin_name="myp")

        jid = "user1@example"

        # initially uncached: get should load an empty plugin dict
        got_plugin = await prs.get(jid)
        assert isinstance(got_plugin, dict)
        assert got_plugin == {}  # no data yet
        # loading from missing row sets profile_meta (per implementation)
        assert um._profile_meta[jid] is None

        # set a value -> should create nested structures and mark dirty + set runtime_meta
        await prs.set(jid, "alpha", "one")
        assert jid in um._dirty_runtime
        assert jid in um._runtime_cache
        assert um._runtime_cache[jid]["plugins"]["myp"]["alpha"] == "one"
        # runtime meta should be a recent ISO string
        assert jid in um._runtime_meta
        assert isinstance(um._runtime_meta[jid], str)

        # get a single key
        val = await prs.get(jid, "alpha")
        assert val == "one"

        # delete the key
        await prs.delete(jid, "alpha")
        # after delete, key should not exist and jid should be in dirty set
        assert "alpha" not in um._runtime_cache[jid]["plugins"]["myp"]
        assert jid in um._dirty_runtime

        # Test global helpers (use GLOBAL_JID)
        await prs.set_global("gk", 123)
        # set_global uses set(GLOBAL_JID, ...)
        assert GLOBAL_JID in um._runtime_cache
        assert um._runtime_cache[GLOBAL_JID]["plugins"]["myp"]["gk"] == 123

        got_global = await prs.get_global("gk", default=None)
        assert got_global == 123

    finally:
        await conn.close()
