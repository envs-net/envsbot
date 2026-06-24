from database.users import PluginRuntimeStore
import json
import logging
import pytest

pytestmark = pytest.mark.asyncio
# (pytest-asyncio required)


# Patch logging to silence noisy logs
logging.getLogger("core_plugins.users").setLevel(logging.CRITICAL)

# --------------------------
# Mock database and helpers
# --------------------------


class DummyCursor:
    def __init__(self, row):
        self.row = row
        self._iterated = False

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return [self.row] if self.row else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass


class DummyDB:
    def __init__(self):
        self.data = {}
        self.last_updated = {}
        self.execute_calls = []

    async def execute(self, query, params):
        self.execute_calls.append((query, params))
        # For SELECT "users_runtime" queries:
        if "SELECT data" in query:
            jid = params[0]
            val = self.data.get(jid, None)
            last_update = self.last_updated.get(jid, None)
            if val is not None:
                # Return as tuple (data, last_updated)
                return DummyCursor((val, last_update))
            else:
                return DummyCursor(None)
        # For UPDATE/INSERT operations, just record and pretend to accept.
        return DummyCursor(None)


class DummyUM:
    def __init__(self):
        self.db = DummyDB()
        self._runtime_cache = {}
        self._runtime_meta = {}
        self._dirty_runtime = set()

# --------------------------
# Fixtures
# --------------------------


@pytest.fixture
def dummy_um():
    return DummyUM()


@pytest.fixture
def plugin_store(dummy_um):
    return PluginRuntimeStore(dummy_um, "test_plugin")


def make_json_blob(plugin_name, value):
    """helper for plugin store layout"""
    return json.dumps({"plugins": {plugin_name: value}})

# --------------------------
# Tests
# --------------------------


@pytest.mark.asyncio
async def test_load_from_db_ok(plugin_store, dummy_um):
    jid = "user@domain"
    value = {"foo": "bar"}
    data_blob = make_json_blob(plugin_store.plugin_name, value)
    dummy_um.db.data[jid] = data_blob
    dummy_um.db.last_updated[jid] = "2021-03-11T11:11:11"

    # Should load the correct structure
    loaded = await plugin_store._load_from_db(jid)
    assert "plugins" in loaded
    assert loaded["plugins"][plugin_store.plugin_name] == value
    assert dummy_um._runtime_meta[jid] == "2021-03-11T11:11:11"


@pytest.mark.asyncio
async def test_load_from_db_blank(plugin_store, dummy_um):
    jid = "unknown@domain"
    loaded = await plugin_store._load_from_db(jid)
    assert loaded == {"plugins": {}}
    assert dummy_um._runtime_meta[jid] is None


@pytest.mark.asyncio
async def test_load_from_db_decoding_error(plugin_store, dummy_um, caplog):
    jid = "user@domain"
    dummy_um.db.data[jid] = "not a valid json"
    dummy_um.db.last_updated[jid] = "A"
    with caplog.at_level(logging.ERROR), caplog.at_level(logging.CRITICAL):
        loaded = await plugin_store._load_from_db(jid)
        assert loaded == {"plugins": {}}
        # Should not raise, but log failure


@pytest.mark.asyncio
async def test_ensure_cache_creates_structure(plugin_store, dummy_um):
    jid = "abc@domain"
    # No entry
    plugin_store._ensure_cache(jid)
    assert jid in dummy_um._runtime_cache
    assert "plugins" in dummy_um._runtime_cache[jid]


@pytest.mark.asyncio
async def test_get_and_set(plugin_store, dummy_um):
    jid = "u@d"
    # Simulate blank load
    dummy_um.db.data[jid] = json.dumps({"plugins": {}})
    # Should default to missing, then set
    result = await plugin_store.get(jid, "foo")
    assert result is None
    await plugin_store.set(jid, "foo", "bar")
    assert await plugin_store.get(jid, "foo") == "bar"


@pytest.mark.asyncio
async def test_set_and_get(plugin_store, dummy_um):
    jid = "u@d"
    await plugin_store.set(jid, "a", 123)
    v = await plugin_store.get(jid, "a")
    assert v == 123
    # Should register as dirty
    assert jid in dummy_um._dirty_runtime


@pytest.mark.asyncio
async def test_delete(plugin_store, dummy_um):
    jid = "test@domain"
    await plugin_store.set(jid, "toremove", 999)
    # Add another
    await plugin_store.set(jid, "keep", 1)
    await plugin_store.set(jid, "toremove", None)
    val = await plugin_store.get(jid, "toremove")
    assert val is None
    assert await plugin_store.get(jid, "keep") == 1


@pytest.mark.asyncio
async def test_default_value(plugin_store, dummy_um):
    jid = "def@domain"
    # PluginRuntimeStore.get does not take default=, will return None if
    # not set
    result = await plugin_store.get(jid, "notset")
    assert result is None


@pytest.mark.asyncio
async def test_global(plugin_store, dummy_um):
    # This tests the global store (under the __GLOBAL__ jid)
    await plugin_store.set_global("globkey", {"a": 1})
    v = await plugin_store.get_global("globkey")
    assert v == {"a": 1}
    await plugin_store.set_global("globkey", None)
    v2 = await plugin_store.get_global("globkey")
    assert v2 is None


@pytest.mark.asyncio
async def test_set_and_get_multiple_fields(plugin_store, dummy_um):
    jid = "multi@domain"
    await plugin_store.set(jid, "foo", 1)
    await plugin_store.set(jid, "bar", 2)
    for field, exp in [("foo", 1), ("bar", 2)]:
        v = await plugin_store.get(jid, field)
        assert v == exp


@pytest.mark.asyncio
async def test_dirty_flag_on_set_and_delete(plugin_store, dummy_um):
    jid = "flag@domain"
    dummy_um._dirty_runtime.clear()
    await plugin_store.set(jid, "x", 42)
    assert jid in dummy_um._dirty_runtime
    await plugin_store.set(jid, "x", None)
    assert jid in dummy_um._dirty_runtime


@pytest.mark.asyncio
async def test_delete_field_nop(plugin_store, dummy_um):
    jid = "noop@domain"
    await plugin_store.set(jid, "notset", None)  # should not fail
    # Should not throw or error


@pytest.mark.asyncio
async def test_global_does_not_affect_user(plugin_store, dummy_um):
    # Set global, then regular user
    await plugin_store.set_global("shared", 12)
    await plugin_store.set("abc@foo", "shared", 99)
    # Confirm the difference
    v1 = await plugin_store.get_global("shared")
    v2 = await plugin_store.get("abc@foo", "shared")
    assert v1 == 12
    assert v2 == 99


@pytest.mark.asyncio
async def test_local_global_keys_dont_leak(plugin_store, dummy_um):
    # Set a jid-specific key, ensure it doesn't appear in global
    await plugin_store.set("user@else", "mykey", 42)
    g = await plugin_store.get_global("mykey")
    assert g is None


@pytest.mark.asyncio
async def test_set_json_value(plugin_store, dummy_um):
    jid = "user@json"
    val = {"complex": [1, 2, {"a": "b"}]}
    await plugin_store.set(jid, "blob", val)
    got = await plugin_store.get(jid, "blob")
    assert got == val


@pytest.mark.asyncio
async def test_no_unintended_attr(plugin_store):
    # PluginRuntimeStore should only have required attributes
    assert hasattr(plugin_store, "plugin_name")
    assert hasattr(plugin_store, "um")
    # Should not have public dicts for data storage
    for attr in ["data", "cache", "values"]:
        assert not hasattr(plugin_store, attr)

from database.users import UserManager, GLOBAL_JID


class MappingRow(dict):
    """Tiny row object that behaves like sqlite Row for dict(row)."""

    def __iter__(self):
        return iter(self.items())


class RichCursor:
    def __init__(self, rows=None, one=None):
        self.rows = rows or []
        self.one = one

    async def fetchone(self):
        return self.one

    async def fetchall(self):
        return self.rows


class RichDummyDB:
    def __init__(self):
        self.users = {}
        self.runtime = {}
        self.calls = []
        self.fail_on = None

    async def execute(self, query, params=()):
        normalized = " ".join(query.split())
        self.calls.append((normalized, params))
        if self.fail_on and self.fail_on in normalized:
            raise RuntimeError("forced db failure")

        if normalized.startswith("SELECT * FROM users WHERE jid=?"):
            row = self.users.get(params[0])
            return RichCursor(one=MappingRow(row) if row else None)

        if normalized.startswith("SELECT * FROM users ORDER BY"):
            rows = [MappingRow(row) for row in self.users.values()]
            return RichCursor(rows=rows)

        if normalized.startswith("SELECT data, last_updated FROM users_runtime"):
            row = self.runtime.get(params[0])
            return RichCursor(one=row)

        if normalized.startswith("DELETE FROM users WHERE jid"):
            self.users.pop(params[0], None)
            return RichCursor()

        if normalized.startswith("DELETE FROM users_runtime WHERE jid"):
            self.runtime.pop(params[0], None)
            return RichCursor()

        return RichCursor()


def _queries(db):
    return [query for query, _params in db.calls]


@pytest.mark.asyncio
async def test_runtime_store_delete_clear_and_uncached_shapes():
    db = RichDummyDB()
    um = UserManager(db)
    store = um.plugin("shape")

    um._runtime_cache["broken@jid"] = {"shape": {"old": True}}
    await store.set("broken@jid", "new", 1)
    assert um._runtime_cache["broken@jid"]["plugins"]["shape"] == {"new": 1}

    await store.delete("broken@jid", "new")
    assert await store.get("broken@jid", "new") is None
    assert "broken@jid" in um._dirty_runtime

    await store.set("broken@jid", "keep", "value")
    await store.clear("broken@jid")
    assert await store.get("broken@jid") == {}

    await store.delete("missing@jid", "absent")
    assert um._runtime_cache["missing@jid"] == {"plugins": {}}


@pytest.mark.asyncio
async def test_user_manager_create_get_set_list_update_and_delete_cache_cleanup():
    db = RichDummyDB()
    db.users["db@jid"] = {
        "jid": "db@jid",
        "nickname": "DbNick",
        "role": 20,
        "created_at": "old",
        "last_seen": "old",
        "registered": 1,
    }
    um = UserManager(db)

    assert await um.get("missing@jid") is None
    db_user = await um.get("db@jid")
    assert db_user["nickname"] == "DbNick"

    await um.create("new@jid", "NewNick")
    assert await um.set("new@jid", "role", 60) is um._users_cache["new@jid"]
    assert await um.set("absent@jid", "role", 60) is None
    await um.update_last_seen("new@jid")

    listed = await um.list()
    assert [row["jid"] for row in listed] == ["db@jid", "new@jid"]

    um._runtime_cache["new@jid"] = {"plugins": {"demo": {"x": 1}}}
    um._dirty_runtime.add("new@jid")
    um._nick_index = {"Nick": {"new@jid", "other@jid"}, "Solo": ["new@jid"]}
    await um.delete("new@jid")

    assert "new@jid" not in um._users_cache
    assert "new@jid" not in um._runtime_cache
    assert "new@jid" not in um._dirty_runtime
    assert um._nick_index == {"Nick": {"other@jid"}}


@pytest.mark.asyncio
async def test_user_manager_value_helpers_and_flush_all_success():
    db = RichDummyDB()
    um = UserManager(db)

    data = {"a": {"b": {"c": 3}}, "plain": "text"}
    assert await um.get_value(data, "a.b.c") == 3
    assert await um.get_value(data, "a.b.missing") is None
    assert await um.get_value(data, "plain.child") is None

    cache = {}
    dirty = set()
    await um.set_value(cache, dirty, "jid@x", "nested.key", "value")
    assert cache == {"jid@x": {"nested": {"key": "value"}}}
    assert dirty == {"jid@x"}

    await um.create("flush@jid", "FlushNick")
    await um.plugin("demo").set("flush@jid", "seen", True)
    um._nick_index = {"FlushNick": {"flush@jid"}}
    await um.flush_all()

    queries = _queries(db)
    assert "SAVEPOINT flush_checkpoint" in queries
    assert "RELEASE flush_checkpoint" in queries
    assert not um._dirty_users
    assert not um._dirty_runtime
    assert GLOBAL_JID in um._runtime_cache
    assert um._runtime_cache[GLOBAL_JID]["plugins"]["users"]["_nick_index"] == {
        "FlushNick": ["flush@jid"]
    }


@pytest.mark.asyncio
async def test_user_manager_flush_all_rolls_back_and_keeps_dirty_flags():
    db = RichDummyDB()
    db.fail_on = "INSERT INTO users (jid"
    um = UserManager(db)
    await um.create("bad@jid", "Bad")

    with pytest.raises(RuntimeError, match="forced db failure"):
        await um.flush_all()

    queries = _queries(db)
    assert "ROLLBACK TO flush_checkpoint" in queries
    assert um._dirty_users == {"bad@jid"}
