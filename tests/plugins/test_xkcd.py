import aiohttp
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import plugins.xkcd as xkcd


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.make_message = MagicMock(return_value=MagicMock())
    bot.reply = MagicMock()
    return bot


@pytest.fixture(autouse=True)
def reset_joined_rooms():
    original = dict(xkcd.JOINED_ROOMS)
    try:
        yield
    finally:
        xkcd.JOINED_ROOMS.clear()
        xkcd.JOINED_ROOMS.update(original)

#
# --- normalize_image_url
#


def test_normalize_image_url_variants():
    assert xkcd.normalize_image_url(None) is None
    assert xkcd.normalize_image_url("") is None
    assert (xkcd.normalize_image_url(
        "https://imgs.xkcd.com/comics/test.png")
            == "https://imgs.xkcd.com/comics/test.png")
    assert (xkcd.normalize_image_url(
        "//imgs.xkcd.com/comics/test.png")
            == "https://imgs.xkcd.com/comics/test.png")
    assert xkcd.normalize_image_url(
        "/comics/test.png") == "https://imgs.xkcd.com/comics/test.png"
    assert xkcd.normalize_image_url("other.png") == "other.png"

#
# --- format_comic_message
#


def test_format_comic_message():
    comic = {"num": 42, "title": "The Answer", "alt": "Alt text"}
    msg = xkcd.format_comic_message(comic)
    assert "42" in msg
    assert "The Answer" in msg
    assert "Alt text" in msg
    assert "https://xkcd.com/42" in msg


def test_format_comic_message_minimal():
    comic = {}
    msg = xkcd.format_comic_message(comic)
    assert "#?" in msg
    assert "No title" in msg

#
# --- fetch_xkcd/get_latest_xkcd/get_xkcd
#


@pytest.mark.asyncio
async def test_fetch_xkcd_success(monkeypatch):
    class DummyResp:
        status = 200
        async def json(self): return {"num": 1}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    class DummySession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def get(self, url, timeout=None): return DummyResp()

    monkeypatch.setattr(aiohttp, "ClientSession", DummySession)
    url = "https://xkcd.com/1/info.0.json"
    data = await xkcd.fetch_xkcd(url)
    assert data["num"] == 1


@pytest.mark.asyncio
async def test_fetch_xkcd_http_error(monkeypatch):
    class DummyResp:
        status = 404
        async def json(self): return {"error": 404}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    class DummySession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def get(self, url, timeout=None): return DummyResp()

    monkeypatch.setattr(aiohttp, "ClientSession", DummySession)
    data = await xkcd.fetch_xkcd("https://xkcd.com/404/info.0.json")
    assert data is None


@pytest.mark.asyncio
async def test_fetch_xkcd_exception(monkeypatch):
    class DummySession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def get(self, url, timeout=None): raise Exception("fail")
    monkeypatch.setattr(aiohttp, "ClientSession", DummySession)
    data = await xkcd.fetch_xkcd("https://xkcd.com/1/info.0.json")
    assert data is None


@pytest.mark.asyncio
async def test_get_latest_xkcd(monkeypatch):
    called = {}

    async def fakefetch(url, session=None):
        called['url'] = url
        return {"num": 2222}
    monkeypatch.setattr(xkcd, "fetch_xkcd", fakefetch)
    result = await xkcd.get_latest_xkcd()
    assert "url" in called and xkcd.XKCD_LATEST_URL in called["url"]
    assert result["num"] == 2222


@pytest.mark.asyncio
async def test_get_xkcd(monkeypatch):
    test_id = 5

    async def fakefetch(url, session=None):
        assert str(test_id) in url
        return {"num": test_id}
    monkeypatch.setattr(xkcd, "fetch_xkcd", fakefetch)
    result = await xkcd.get_xkcd(test_id)
    assert result["num"] == 5

#
# --- send_url_with_oob
#


@pytest.mark.asyncio
async def test_send_url_with_oob_sets_field_and_sends():
    bot = MagicMock()
    msg_obj = MagicMock()
    bot.make_message.return_value = msg_obj

    class OOB:
        def __setitem__(self, k, v): self.url = v

    def getitem(key):
        if key == "oob":
            return OOB()
        raise KeyError(key)
    msg_obj.__getitem__.side_effect = getitem
    msg_obj.send = MagicMock()

    await xkcd.send_url_with_oob(bot, "jid@xmpp", "http://test", "chat")
    msg_obj.send.assert_called()


@pytest.mark.asyncio
async def test_send_url_with_oob_attach_oob_fails():
    bot = MagicMock()
    msg_obj = MagicMock()
    bot.make_message.return_value = msg_obj
    msg_obj.__getitem__.side_effect = Exception("No OOB")
    msg_obj.send = MagicMock()
    await xkcd.send_url_with_oob(bot, "jid@xmpp", "http://test", "chat")
    msg_obj.send.assert_called()

#
# --- send_xkcd_room / send_xkcd_dm
#


@pytest.mark.asyncio
async def test_send_xkcd_room_success(mock_bot):
    comic = {"img": "/comics/foo.png", "num": 13, "title": "foo"}
    with (patch("plugins.xkcd.send_url_with_oob", new_callable=AsyncMock)
          as send_oob):
        await xkcd.send_xkcd_room(mock_bot, "roomid@chat", comic)
        mock_bot.reply.assert_called()
        send_oob.assert_awaited()


@pytest.mark.asyncio
async def test_send_xkcd_room_no_img(mock_bot):
    comic = {"num": 5, "title": "fail"}
    with patch("plugins.xkcd.send_url_with_oob", new_callable=AsyncMock):
        await xkcd.send_xkcd_room(mock_bot, "room@conf", comic)
        mock_bot.reply.assert_not_called()


@pytest.mark.asyncio
async def test_send_xkcd_dm_success(mock_bot):
    comic = {"img": "/comics/bar.png", "num": 85, "title": "bar"}
    msg_obj = MagicMock()
    mock_bot.make_message.return_value = msg_obj
    msg_obj.send = MagicMock()
    with (patch("plugins.xkcd.send_url_with_oob", new_callable=AsyncMock)
          as send_oob):
        await xkcd.send_xkcd_dm(mock_bot, "me@xmpp", comic)
        msg_obj.send.assert_called()
        send_oob.assert_awaited()


@pytest.mark.asyncio
async def test_send_xkcd_dm_no_img(mock_bot):
    comic = {"title": "badcomic"}
    msg_obj = MagicMock()
    mock_bot.make_message.return_value = msg_obj
    msg_obj.send = MagicMock()
    with patch("plugins.xkcd.send_url_with_oob", new_callable=AsyncMock):
        await xkcd.send_xkcd_dm(mock_bot, "me@xmpp", comic)
        msg_obj.send.assert_not_called()


class DummyXkcdStore:
    def __init__(self, globals_=None):
        self._globals = dict(globals_ or {})

    async def get_global(self, key, default=None):
        return self._globals.get(key, default)

    async def set_global(self, key, value):
        self._globals[key] = value


def xkcd_bot_with_store(store):
    bot = MagicMock()
    bot.db.users.plugin.return_value = store
    bot.reply = MagicMock()
    bot.make_message = MagicMock(return_value=MagicMock())
    bot.plugin = {}
    bot.register_plugin = MagicMock()
    return bot


@pytest.mark.asyncio
async def test_xkcd_store_helpers_and_migration():
    store = DummyXkcdStore({
        xkcd.XKCD_LAST_ID_KEY: {"id": "7"},
        xkcd.XKCD_KEY: {"rooms": ["room1@conf", "", "room2@conf"]},
    })
    bot = xkcd_bot_with_store(store)

    assert await xkcd.get_last_comic_id(bot) == 7
    await xkcd.save_last_comic_id(bot, 8)
    assert store._globals[xkcd.XKCD_LAST_ID_KEY] == {"id": 8}

    await xkcd.add_comic_to_index(bot, {"num": 123, "title": "T", "alt": "A"})
    assert store._globals[xkcd.XKCD_INDEX_KEY]["123"] == {
        "title": "T",
        "alt": "A",
    }
    await xkcd.add_comic_to_index(bot, None)
    await xkcd.add_comic_to_index(bot, {"title": "missing-num"})
    assert list(store._globals[xkcd.XKCD_INDEX_KEY]) == ["123"]

    assert await xkcd.get_subscribed_rooms(bot) == ["room1@conf", "room2@conf"]
    await xkcd.migrate_xkcd_room_storage(bot)
    assert store._globals[xkcd.XKCD_KEY] == {
        "room1@conf": True,
        "room2@conf": True,
    }
    assert await xkcd.get_subscribed_rooms(bot) == ["room1@conf", "room2@conf"]


@pytest.mark.asyncio
async def test_xkcd_store_helpers_handle_bad_state():
    store = DummyXkcdStore({
        xkcd.XKCD_LAST_ID_KEY: "bad",
        xkcd.XKCD_KEY: "bad",
        xkcd.XKCD_INDEX_KEY: "bad",
    })
    bot = xkcd_bot_with_store(store)

    assert await xkcd.get_last_comic_id(bot) == 0
    assert await xkcd.get_subscribed_rooms(bot) == []
    await xkcd.migrate_xkcd_room_storage(bot)
    await xkcd.add_comic_to_index(bot, {"num": 5})
    assert store._globals[xkcd.XKCD_INDEX_KEY] == {"5": {"title": "", "alt": ""}}


def test_xkcd_index_and_search_helpers(monkeypatch):
    assert xkcd._normalize_xkcd_index("bad") == {}
    assert xkcd._normalize_xkcd_index({"1": {}}) == {"1": {}}
    assert xkcd._expected_xkcd_count(405) == 404
    assert xkcd._xkcd_should_skip_comic(404, {}) is True
    assert xkcd._xkcd_should_skip_comic(10, {"10": {}}) is True
    assert xkcd._xkcd_should_skip_comic(11, {}) is False

    index = {
        "10": {"title": "Python", "alt": "snake"},
        "bad": {"title": "Python", "alt": "not numeric"},
        "11": {"title": "Other", "alt": "A python alt"},
        "12": "ignored",
    }
    assert [item["id"] for item in xkcd._search_xkcd_index(index, "python")] == [10, 11]
    assert xkcd._parse_xkcd_search_args(["search", "python", "3"]) == (3, "python")
    assert xkcd._parse_xkcd_search_args(["search", "python", "comic"]) == (1, "python comic")
    assert xkcd._truncate_alt_text("x" * 81).endswith("...")
    assert xkcd._truncate_alt_text("short") == "short"

    picks = iter([404, 5])

    def fake_randint(start, end):
        assert start == 1
        assert end == 500
        return next(picks)

    monkeypatch.setattr(xkcd.random, "randint", fake_randint)
    assert xkcd._pick_valid_random_xkcd_id(500) == 5


@pytest.mark.asyncio
async def test_index_single_xkcd_comic_success_failure_and_cancel(monkeypatch):
    store = DummyXkcdStore()
    monkeypatch.setattr(xkcd.asyncio, "sleep", AsyncMock())

    async def fake_get_xkcd(comic_id, session=None):
        return {"num": comic_id, "title": f"Title {comic_id}", "alt": "Alt"}

    monkeypatch.setattr(xkcd, "get_xkcd", fake_get_xkcd)
    search_index = {}
    indexed, failed = await xkcd._index_single_xkcd_comic(
        1, object(), store, search_index, 199, 0
    )
    assert indexed == 200
    assert failed == 0
    assert search_index["1"] == {"title": "Title 1", "alt": "Alt"}
    assert store._globals[xkcd.XKCD_INDEX_KEY] is search_index

    async def missing_get_xkcd(comic_id, session=None):
        return None

    monkeypatch.setattr(xkcd, "get_xkcd", missing_get_xkcd)
    assert await xkcd._index_single_xkcd_comic(2, object(), store, {}, 0, 0) == (0, 1)

    async def cancelled_get_xkcd(comic_id, session=None):
        raise xkcd.asyncio.CancelledError

    monkeypatch.setattr(xkcd, "get_xkcd", cancelled_get_xkcd)
    with pytest.raises(xkcd.asyncio.CancelledError):
        await xkcd._index_single_xkcd_comic(3, object(), store, {}, 4, 0)


@pytest.mark.asyncio
async def test_broadcast_comic_only_sends_to_joined_rooms(monkeypatch, mock_bot):
    sent = []
    monkeypatch.setattr(xkcd, "get_subscribed_rooms", AsyncMock(return_value=[
        "joined@conf",
        "missing@conf",
    ]))
    def record_sent_room(bot, room, comic):
        assert bot is mock_bot
        assert comic == {"num": 9}
        sent.append(room)

    monkeypatch.setattr(xkcd, "send_xkcd_room", AsyncMock(side_effect=record_sent_room))
    monkeypatch.setattr(xkcd.asyncio, "sleep", AsyncMock())
    monkeypatch.setitem(xkcd.JOINED_ROOMS, "joined@conf", {"nicks": {}})
    await xkcd.broadcast_comic_to_subscribed_rooms(mock_bot, {"num": 9})
    assert sent == ["joined@conf"]


@pytest.mark.asyncio
async def test_xkcd_command_handlers(monkeypatch, mock_bot):
    msg = {"from": "user@example.org/resource"}

    monkeypatch.setattr(xkcd, "get_latest_xkcd", AsyncMock(return_value={"num": 20, "img": "/a.png"}))
    monkeypatch.setattr(xkcd, "get_xkcd", AsyncMock(return_value={"num": 4, "img": "/b.png"}))
    send_room = AsyncMock()
    send_dm = AsyncMock()
    monkeypatch.setattr(xkcd, "send_xkcd_room", send_room)
    monkeypatch.setattr(xkcd, "send_xkcd_dm", send_dm)
    def fake_pick_valid_random_xkcd_id(max_id):
        assert max_id == 20
        return 4

    monkeypatch.setattr(xkcd, "_pick_valid_random_xkcd_id", fake_pick_valid_random_xkcd_id)

    await xkcd._handle_xkcd_random(mock_bot, msg, "room@conf", "user@example.org", True)
    send_room.assert_awaited_with(mock_bot, "room@conf", {"num": 4, "img": "/b.png"})

    await xkcd._handle_specific_xkcd(mock_bot, msg, ["4"], "room@conf", "user@example.org", False)
    send_dm.assert_awaited_with(mock_bot, "user@example.org", {"num": 4, "img": "/b.png"})

    await xkcd._handle_latest_xkcd(mock_bot, msg, "room@conf", "user@example.org", False)
    assert send_dm.await_count >= 2

    assert await xkcd._handle_specific_xkcd(mock_bot, msg, ["not-a-number"], "room", "jid", False) is False
    assert await xkcd._handle_specific_xkcd(mock_bot, msg, ["404"], "room", "jid", False) is True
    assert "does not exist" in mock_bot.reply.call_args[0][1]
    assert await xkcd._handle_specific_xkcd(mock_bot, msg, ["0"], "room", "jid", False) is True
    assert "1 or greater" in mock_bot.reply.call_args[0][1]


@pytest.mark.asyncio
async def test_xkcd_search_handler_branches(monkeypatch, mock_bot):
    msg = {"from": "user@example.org/resource"}

    await xkcd._handle_xkcd_search(mock_bot, msg, ["search"], ["search"], ",")
    assert "Usage" in mock_bot.reply.call_args[0][1]

    store = DummyXkcdStore({xkcd.XKCD_INDEX_KEY: {}})
    monkeypatch.setattr(xkcd, "get_xkcd_store", AsyncMock(return_value=store))
    await xkcd._handle_xkcd_search(mock_bot, msg, ["search", "python"], ["search", "python"], ",")
    assert "Search index" in mock_bot.reply.call_args[0][1]

    store._globals[xkcd.XKCD_INDEX_KEY] = {
        "10": {"title": "Python", "alt": "Snake"},
        "11": {"title": "Other", "alt": "No match"},
    }
    await xkcd._handle_xkcd_search(mock_bot, msg, ["search", "python"], ["search", "python"], ",")
    assert "Found 1 results" in mock_bot.reply.call_args[0][1]
    assert "#10" in mock_bot.reply.call_args[0][1]

    await xkcd._handle_xkcd_search(mock_bot, msg, ["search", "missing"], ["search", "missing"], ",")
    assert "No XKCDs found" in mock_bot.reply.call_args[0][1]


@pytest.mark.asyncio
async def test_block_muc_pm_when_disabled(monkeypatch, mock_bot):
    monkeypatch.setattr(xkcd, "get_subscribed_rooms", AsyncMock(return_value=["enabled@conf"]))
    assert await xkcd._block_muc_pm_when_disabled(mock_bot, {}, False, "room@conf", ",") is False
    assert await xkcd._block_muc_pm_when_disabled(mock_bot, {}, True, "enabled@conf", ",") is False
    assert await xkcd._block_muc_pm_when_disabled(mock_bot, {}, True, "room@conf", ",") is True
    assert "not enabled" in mock_bot.reply.call_args[0][1]


@pytest.mark.asyncio
async def test_xkcd_on_load_and_unload_manage_tasks(monkeypatch):
    bot = xkcd_bot_with_store(DummyXkcdStore())
    created = []

    async def noop_migrate(_bot):
        return None

    async def noop_cancel(task, name):
        created.append(("cancel", task, name))

    def fake_create_plugin_task(_bot, plugin, coro, name):
        coro.close()
        task = MagicMock(name=name)
        created.append(("create", plugin, name))
        return task

    monkeypatch.setattr(xkcd, "migrate_xkcd_room_storage", noop_migrate)
    monkeypatch.setattr(xkcd, "_cancel_task", noop_cancel)
    monkeypatch.setattr(xkcd, "create_plugin_task", fake_create_plugin_task)
    xkcd.CHECK_TASK = MagicMock(name="old-check")
    xkcd.INDEX_TASK = MagicMock(name="old-index")

    await xkcd.on_load(bot)
    bot.register_plugin.assert_called_once_with("xep_0066")
    assert ("create", "xkcd", "xkcd-index") in created
    assert ("create", "xkcd", "xkcd-check") in created
    assert xkcd.INDEX_TASK is not None
    assert xkcd.CHECK_TASK is not None

    await xkcd.on_unload(bot)
    assert xkcd.INDEX_TASK is None
    assert xkcd.CHECK_TASK is None


class DummyAiohttpSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_build_full_index_handles_missing_up_to_date_and_indexes(monkeypatch):
    monkeypatch.setattr(xkcd.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(xkcd.aiohttp, "ClientSession", DummyAiohttpSession)

    store = DummyXkcdStore()
    bot = xkcd_bot_with_store(store)

    monkeypatch.setattr(xkcd, "get_latest_xkcd", AsyncMock(return_value=None))
    await xkcd.build_full_index(bot)
    assert xkcd.XKCD_INDEX_KEY not in store._globals

    store._globals[xkcd.XKCD_INDEX_KEY] = {"1": {}, "2": {}, "3": {}}
    monkeypatch.setattr(xkcd, "get_latest_xkcd", AsyncMock(return_value={"num": 3}))
    index_mock = AsyncMock()
    monkeypatch.setattr(xkcd, "_index_single_xkcd_comic", index_mock)
    await xkcd.build_full_index(bot)
    index_mock.assert_not_awaited()

    store._globals[xkcd.XKCD_INDEX_KEY] = {"1": {"title": "one", "alt": ""}}
    calls = []

    async def fake_index_single(comic_id, session, store_arg, search_index, indexed, failed):
        calls.append(comic_id)
        search_index[str(comic_id)] = {"title": str(comic_id), "alt": ""}
        return indexed + 1, failed

    monkeypatch.setattr(xkcd, "_index_single_xkcd_comic", fake_index_single)
    await xkcd.build_full_index(bot)
    assert calls == [2, 3]
    assert store._globals[xkcd.XKCD_INDEX_KEY]["2"] == {"title": "2", "alt": ""}
    assert store._globals[xkcd.XKCD_INDEX_KEY]["3"] == {"title": "3", "alt": ""}


@pytest.mark.asyncio
async def test_catch_up_missing_comics_skips_missing_fetches_and_persists(monkeypatch):
    bot = xkcd_bot_with_store(DummyXkcdStore())
    fetched = []
    indexed = []
    broadcasted = []
    saved = []

    monkeypatch.setattr(xkcd.aiohttp, "ClientSession", DummyAiohttpSession)

    async def fake_get_xkcd(comic_id, session=None):
        fetched.append(comic_id)
        if comic_id == 406:
            return None
        return {"num": comic_id, "title": str(comic_id), "img": "/comic.png"}

    async def fake_add(bot_arg, comic):
        indexed.append(comic["num"])

    async def fake_broadcast(bot_arg, comic):
        broadcasted.append(comic["num"])

    async def fake_save(bot_arg, comic_id):
        saved.append(comic_id)

    monkeypatch.setattr(xkcd, "get_xkcd", fake_get_xkcd)
    monkeypatch.setattr(xkcd, "add_comic_to_index", fake_add)
    monkeypatch.setattr(xkcd, "broadcast_comic_to_subscribed_rooms", fake_broadcast)
    monkeypatch.setattr(xkcd, "save_last_comic_id", fake_save)

    await xkcd.catch_up_missing_comics(bot, 404, 406)
    assert fetched == [405, 406]
    assert indexed == [405]
    assert broadcasted == [405]
    assert saved == [404, 405]
    assert xkcd.LAST_COMIC_ID == 405

    await xkcd.catch_up_missing_comics(bot, 10, 9)
    assert fetched == [405, 406]


@pytest.mark.asyncio
async def test_xkcd_check_loop_initializes_catches_up_and_cancels(monkeypatch):
    bot = xkcd_bot_with_store(DummyXkcdStore())
    saved = []
    caught_up = []

    async def fake_save(_bot, comic_id):
        saved.append(comic_id)

    async def fake_catch_up(_bot, start_id, end_id):
        caught_up.append((start_id, end_id))

    monkeypatch.setattr(xkcd, "get_latest_xkcd", AsyncMock(return_value={"num": 10}))
    monkeypatch.setattr(xkcd, "get_last_comic_id", AsyncMock(return_value=0))
    monkeypatch.setattr(xkcd, "save_last_comic_id", fake_save)
    monkeypatch.setattr(xkcd.asyncio, "sleep", AsyncMock(side_effect=xkcd.asyncio.CancelledError))

    with pytest.raises(xkcd.asyncio.CancelledError):
        await xkcd.xkcd_check_loop(bot)
    assert saved == [10]
    assert xkcd.LAST_COMIC_ID == 10

    monkeypatch.setattr(xkcd, "get_last_comic_id", AsyncMock(return_value=7))
    monkeypatch.setattr(xkcd, "catch_up_missing_comics", fake_catch_up)
    with pytest.raises(xkcd.asyncio.CancelledError):
        await xkcd.xkcd_check_loop(bot)
    assert caught_up == [(8, 10)]

    monkeypatch.setattr(xkcd, "get_latest_xkcd", AsyncMock(return_value=None))
    assert await xkcd.xkcd_check_loop(bot) is None


@pytest.mark.asyncio
async def test_cancel_task_none_done_cancelled_and_error(caplog):
    await xkcd._cancel_task(None, "none")

    done_task = xkcd.asyncio.create_task(xkcd.asyncio.sleep(0))
    assert await done_task is None
    await xkcd._cancel_task(done_task, "done")

    pending_task = xkcd.asyncio.create_task(xkcd.asyncio.sleep(60))
    await xkcd._cancel_task(pending_task, "pending")
    assert pending_task.cancelled()

    async def failing_on_cancel():
        try:
            await xkcd.asyncio.sleep(60)
        except xkcd.asyncio.CancelledError as exc:
            raise RuntimeError("boom") from exc

    error_task = xkcd.asyncio.create_task(failing_on_cancel())
    await xkcd.asyncio.sleep(0)
    await xkcd._cancel_task(error_task, "error")
    assert "Error while cancelling error task" in caplog.text


@pytest.mark.asyncio
async def test_cleanup_room_state_removes_legacy_room_entries():
    store = DummyXkcdStore({
        xkcd.XKCD_KEY: {
            "rooms": ["Room@Conference.Example.Org", "other@conf"],
            "other": True,
        }
    })
    bot = xkcd_bot_with_store(store)

    summary = await xkcd.cleanup_room_state(
        bot,
        "room@conference.example.org/nick",
    )

    assert summary == {"legacy_rooms": 1}
    assert store._globals[xkcd.XKCD_KEY]["rooms"] == ["other@conf"]

    summary = await xkcd.cleanup_room_state(bot, "missing@conf")
    assert summary == {"legacy_rooms": 0}

    store = DummyXkcdStore({xkcd.XKCD_KEY: {"rooms": ["room@conf"]}})
    bot = xkcd_bot_with_store(store)
    summary = await xkcd.cleanup_room_state(bot, "room@conf")
    assert summary == {"legacy_rooms": 1}
    assert "rooms" not in store._globals[xkcd.XKCD_KEY]

    store = DummyXkcdStore({xkcd.XKCD_KEY: []})
    bot = xkcd_bot_with_store(store)
    assert await xkcd.cleanup_room_state(bot, "room@conf") == {"legacy_rooms": 0}
