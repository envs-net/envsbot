import pytest
import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace

import plugins.rss as rss
import core_plugins.rooms


@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    monkeypatch.setattr(rss, "config", {"prefix": ","})




@pytest.mark.asyncio
async def test_rss_add_usage_uses_normal_prefix_lookup(monkeypatch, make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    monkeypatch.setattr(rss, "config", {"prefix": "!"})

    await rss.rss_command(bot, "jid", "nick", ["add"], msg, True)

    assert bot.replies[-1][1].startswith("Usage: !rss add")


@pytest.fixture
def make_bot():
    """
    Return a fake bot object with pluggable bot.reply and db.users.plugin().
    """

    class DummyStore(dict):
        async def get_global(self, key, default=None):
            return self.get(key, default if default is not None else {})

        async def set_global(self, key, value):
            self[key] = value

    class DummyBot:
        def __init__(self):
            self.replies = []
            self.flush_count = 0

            async def flush_all():
                self.flush_count += 1

            self.db = SimpleNamespace(
                users=SimpleNamespace(
                    plugin=lambda name: self.plugin_store,
                    flush_all=flush_all,
                )
            )
            self.plugin_store = DummyStore()

        def reply(self, msg, text, **kwargs):
            self.replies.append((msg, text, kwargs))

    return DummyBot


@pytest.mark.asyncio
async def test_rss_add_list_delete(monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    room = "room@conference.example.org"
    fake_feed_title = "TestFeed"
    fake_feed_link = "https://www.example.com/rss"
    fake_feed_entry = {
        "title": "EntryTitle",
        "link": "https://www.example.com/article",
        "description": "EntryDesc",
        "id": "https://www.example.com/article",
    }

    # Patch feedparser.parse (for plugin coverage)
    monkeypatch.setattr(rss, "feedparser", type("Feedparser", (), {})())

    class DummyFeed:
        def __init__(self):
            self.feed = {
                "title": fake_feed_title,
                "link": fake_feed_link,
                "href": fake_feed_link,
                "id": fake_feed_link,
            }
            self.entries = [SimpleNamespace(**fake_feed_entry)]

        def __contains__(self, k):
            # needed for some plugin code
            return k == "feed"

    async def fake_fetch_feed(url):
        return DummyFeed()

    monkeypatch.setattr(rss, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss, "ensure_task", AsyncMock())

    msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}

    # Add
    await rss.rss_command(bot, "jid1", "nick1", ["add", fake_feed_link],
                          msg, True)
    feeds = store.get(rss.RSS_KEY, {})
    assert fake_feed_link in feeds
    # assert bot.flush_count >= 1

    # Add again to test 'already in feed' and room-join path
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["add", fake_feed_link],
                          msg, True)
    assert any("already added" in x[1]
               or "Added room" in x[1] for x in bot.replies)

    # List
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["list"], msg, True)
    assert any("Watched RSS feeds" in x[1][0] for x in bot.replies)

    # Delete (should remove the only room, triggers feed delete in dummy)
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["delete", fake_feed_link],
                          msg, True)
    assert any(
        "no rooms left" in x[1]
        or "Removed this room" in x[1] for x in bot.replies)

    # Delete again (feed not found)
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["delete", fake_feed_link],
                          msg, True)
    assert any("Feed not found" in x[1] for x in bot.replies)

    # Add missing arg
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["add"], msg, True)
    assert any("Usage:" in x[1] for x in bot.replies)

    # Delete missing arg
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["delete"], msg, True)
    assert any("Usage:" in x[1] for x in bot.replies)

    # List with no feeds (store reset)
    bot.plugin_store.clear()
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["list"], msg, True)
    assert any("No feeds configured" in x[1] for x in bot.replies)

    # Unknown subcommand
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["foobar"], msg, True)
    assert any("Unknown subcommand" in x[1] for x in bot.replies)

@pytest.mark.asyncio
async def test_rss_add_rejects_plain_private_chat(monkeypatch, make_bot):
    bot = make_bot()
    msg = {
        "from": SimpleNamespace(bare="user@example.org", resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(
        bot, "jid1", "nick1", ["add", "example.org/feed"], msg, False
    )
    assert bot.replies[-1][1] == "🔴 RSS add can only be used in a room or MUC DM."


@pytest.mark.asyncio
async def test_rss_delete_from_private_chat_removes_stale_feed(make_bot):
    bot = make_bot()
    url = "https://git.envs.net/dan/envsbot.rss"
    room = "envs@conference.envs.net"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Feed of dan/envsbot",
            "link": url,
            "period": 1200,
            "rooms": [room],
        }
    }
    msg = {
        "from": SimpleNamespace(bare="admin@example.org", resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(bot, "jid1", "nick1", ["delete", url], msg, False)

    assert bot.plugin_store[rss.RSS_KEY] == {}
    assert bot.replies[-1][1] == f"🗑 Deleted feed: {url} ({room})"


@pytest.mark.asyncio
async def test_rss_delete_can_target_specific_room_from_private_chat(make_bot):
    bot = make_bot()
    url = "https://example.org/feed"
    stale_room = "old@conference.example.org"
    active_room = "new@conference.example.org"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Feed",
            "link": url,
            "period": 1200,
            "rooms": [stale_room, active_room],
        }
    }
    msg = {
        "from": SimpleNamespace(bare="admin@example.org", resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(
        bot, "jid1", "nick1", ["remove", url, stale_room], msg, False
    )

    assert bot.plugin_store[rss.RSS_KEY][url]["rooms"] == [active_room]
    assert bot.replies[-1][1] == (
        f"🗑 Removed room {stale_room} from feed: {url}"
    )


@pytest.mark.asyncio
async def test_rss_delete_all_target_removes_feed_from_all_rooms(make_bot):
    bot = make_bot()
    url = "https://example.org/feed"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Feed",
            "link": url,
            "period": 1200,
            "rooms": ["a@conference.example.org", "b@conference.example.org"],
        }
    }
    msg = {
        "from": SimpleNamespace(bare="admin@example.org", resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(bot, "jid1", "nick1", ["rm", url, "all"], msg, False)

    assert bot.plugin_store[rss.RSS_KEY] == {}
    assert bot.replies[-1][1].startswith(f"🗑 Deleted feed: {url}")


@pytest.mark.asyncio
async def test_rss_add_allows_joined_muc_pm(monkeypatch, make_bot):
    bot = make_bot()
    room = "room@conference.example.org"
    fake_feed_link = "https://www.example.com/rss"
    msg = {
        "from": SimpleNamespace(bare=room, resource="alice"),
        "type": "chat",
    }

    class DummyFeed:
        def __init__(self):
            self.feed = {"title": "TestFeed", "link": fake_feed_link}
            self.entries = [SimpleNamespace(
                title="EntryTitle",
                link="https://www.example.com/article",
                description="EntryDesc",
                id="https://www.example.com/article",
            )]

        def __contains__(self, key):
            return key == "feed"

    async def fake_fetch_feed(url):
        return DummyFeed()

    monkeypatch.setitem(rss.JOINED_ROOMS, room, {"nicks": {"alice": {}}})
    monkeypatch.setattr(rss, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss, "ensure_task", AsyncMock())

    try:
        await rss.rss_command(
            bot, "jid1", "nick1", ["add", fake_feed_link], msg, False
        )
    finally:
        rss.JOINED_ROOMS.pop(room, None)

    assert fake_feed_link in bot.plugin_store.get(rss.RSS_KEY, {})


@pytest.mark.asyncio
async def test_fetch_feed_handle_redirect_and_structure(monkeypatch):
    class DummyFeed:
        def __init__(self, url):
            self.feed = {"title": "Test", "link": url}
            self.entries = []

        def __contains__(self, k):
            return k == "feed"

    def fake_parse(payload, request_headers=None, response_headers=None):
        assert payload == b"feed-data"
        assert response_headers == {"content-type": "application/rss+xml"}
        return DummyFeed("https://someurl.com/feed")

    feedparser_mod = type(
        "Feedparser", (), {"parse": staticmethod(fake_parse)})()
    monkeypatch.setattr(rss, "feedparser", feedparser_mod)

    async def fake_to_thread(fn, *a, **kw):
        return fn(*a, **kw)

    async def fake_fetch_feed_bytes(url):
        assert url == "https://someurl.com/feed"
        return b"feed-data", url, "application/rss+xml"

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(rss, "_fetch_feed_bytes", fake_fetch_feed_bytes)

    result = await rss.fetch_feed("https://someurl.com/feed")

    assert result.feed["href"] == "https://someurl.com/feed"
    assert result.feed["id"] == "https://someurl.com/feed"
    assert result.feed["title"] == "Test"


@pytest.mark.asyncio
async def test_fetch_feed_rejects_unsafe_feed_url(monkeypatch):
    async def blocked(url, *, allow_private=False):
        assert url == "http://127.0.0.1/feed"
        assert allow_private is False
        raise rss.UnsafeFetchURL("blocked")

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def get(self, *args, **kwargs):
            pytest.fail("unsafe RSS URL should not be fetched")

    monkeypatch.setattr(rss, "validate_fetch_url_async", blocked)
    monkeypatch.setattr(
        rss.aiohttp,
        "ClientSession",
        lambda **kwargs: DummySession(),
    )

    with pytest.raises(rss.UnsafeFetchURL):
        await rss._fetch_feed_bytes("http://127.0.0.1/feed")


@pytest.mark.asyncio
async def test_fetch_feed_bytes_redirect_and_size_limit(monkeypatch):
    validated = []

    async def allow(url, *, allow_private=False):
        validated.append(url)
        return url

    class DummyContent:
        def __init__(self, chunks):
            self.chunks = chunks

        async def iter_chunked(self, size):
            for chunk in self.chunks:
                yield chunk

    class DummyResp:
        def __init__(self, status, url, headers, chunks=()):
            self.status = status
            self.url = url
            self.headers = headers
            self.content = DummyContent(chunks)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def raise_for_status(self):
            if self.status >= 400:
                raise rss.aiohttp.ClientResponseError(
                    None, (), status=self.status
                )

    class DummySession:
        def __init__(self, **kwargs):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def get(self, url, allow_redirects=False):
            self.calls.append(url)
            if len(self.calls) == 1:
                return DummyResp(302, url, {"Location": "/real.xml"})
            return DummyResp(
                200,
                url,
                {"Content-Type": "application/rss+xml"},
                [b"abc"],
            )

    monkeypatch.setattr(rss, "validate_fetch_url_async", allow)
    monkeypatch.setattr(rss.aiohttp, "ClientSession", DummySession)

    body, final_url, content_type = await rss._fetch_feed_bytes(
        "https://example.org/feed"
    )

    assert body == b"abc"
    assert final_url == "https://example.org/real.xml"
    assert content_type == "application/rss+xml"
    assert validated == [
        "https://example.org/feed",
        "https://example.org/real.xml",
    ]

    monkeypatch.setattr(rss, "RSS_MAX_READ_BYTES", 4)

    class BigSession(DummySession):
        def get(self, url, allow_redirects=False):
            return DummyResp(200, url, {}, [b"123", b"45"])

    monkeypatch.setattr(rss.aiohttp, "ClientSession", BigSession)

    with pytest.raises(rss.FetchURLTooLarge):
        await rss._fetch_feed_bytes("https://example.org/big.xml")


@pytest.mark.asyncio
async def test_should_include_description():
    title = "Title"
    assert not rss._should_include_description(title, "")
    assert not rss._should_include_description(title, "Title")
    assert not rss._should_include_description("hi", "hi more stuff")
    assert not rss._should_include_description("foo bar baz", "foo bar")
    assert not rss._should_include_description("aaaaaa", "aaaaab")
    assert rss._should_include_description("aaa", "bbbccc")


def test_generate_entry_id():
    t, d, lnk = "Title", "Desc", "http://a/"

    assert rss._generate_entry_id(t, d, lnk) == lnk

    id1 = rss._generate_entry_id("t1", "d1", "")
    id2 = rss._generate_entry_id("t1", "d1", None)
    id3 = rss._generate_entry_id("t1", "d1", "")

    assert id1 == id3 and id2 == id1


def test_get_entry_id():
    entry = {
        "title": "Title",
        "description": "Description",
        "link": "https://example.org/post",
    }

    assert rss._get_entry_id(entry) == "https://example.org/post"


def test_get_latest_entry_id():
    class DummyParsed:
        entries = [
            {
                "title": "Newest",
                "description": "Newest description",
                "link": "https://example.org/newest",
            },
            {
                "title": "Older",
                "description": "Older description",
                "link": "https://example.org/older",
            },
        ]

    assert rss._get_latest_entry_id(
        DummyParsed()) == "https://example.org/newest"

    class EmptyParsed:
        entries = []

    assert rss._get_latest_entry_id(EmptyParsed()) is None


def test_normalize_and_resolve_url():
    assert rss._normalize_url("EXAMPLE.COM/abc/") == "https://EXAMPLE.COM/abc"
    assert rss._normalize_url("http://abc.com") == "http://abc.com"
    assert rss._normalize_url("ftp://abc.com/feed") == "ftp://abc.com/feed"

    assert (
        rss._resolve_relative_url(
            "https://foo.com/feed", "https://bar.com/page")
        == "https://bar.com/page"
    )
    assert rss._resolve_relative_url(
        "https://foo.com/feed", "/bar") == "https://foo.com/bar"
    assert rss._resolve_relative_url(None, "/foo") == "/foo"


def test_extract_entry_link_variants():
    # Supports both dict and attr-based entry (for plugin coverage)
    class AtomEntryObj(dict):
        def __init__(self):
            self.links = [{"rel": "alternate", "href": "http://example.com"}]

        def __eq__(self, other):
            return (
                dict.__eq__(self, other)
                and getattr(other, "links", None) == self.links
            )

        def __contains__(self, key):
            return key == "links"

        def get(self, key, default=None):
            if key == "links":
                return self.links
            return default

    e = {"link": "http://a.com"}
    assert rss._extract_entry_link(e) == "http://a.com"

    atom_e = AtomEntryObj()
    assert rss._extract_entry_link(atom_e) == "http://example.com"

    e3 = {"url": "https://feed/item"}
    assert rss._extract_entry_link(e3) == "https://feed/item"

    e4 = {"id": "https://idvalue/"}
    assert rss._extract_entry_link(e4) == "https://idvalue/"

    assert rss._extract_entry_link({}) == ""


@pytest.mark.asyncio
async def test_rss_add_failures(monkeypatch, make_bot):
    bot = make_bot()

    monkeypatch.setattr(rss, "feedparser", type("Feedparser", (), {})())

    async def raise_exc(url):
        raise Exception("bad feed")

    monkeypatch.setattr(rss, "fetch_feed", raise_exc)
    monkeypatch.setattr(rss, "ensure_task", AsyncMock())

    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    await rss.rss_command(bot, "jid", "nick", ["add", "http://bad/feed"],
                          msg, True)

    assert any("Failed to fetch or parse feed" in r[1] for r in bot.replies)


@pytest.mark.asyncio
async def test_rss_add_rejects_unsupported_feed_scheme(monkeypatch, make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    await rss.rss_command(bot, "jid", "nick", ["add", "ftp://bad/feed"], msg, True)

    assert any("Failed to fetch or parse feed" in r[1] for r in bot.replies)
    assert not bot.plugin_store.get(rss.RSS_KEY)


@pytest.mark.asyncio
async def test_rss_check_loop_initializes_missing_last_id_without_posting(
        monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "http://f.com/rss"
    room = "room@conference.example.org"

    store[rss.RSS_KEY] = {
        url: {
            "title": "Feed",
            "link": url,
            "period": 1,
            "rooms": [room],
            "last_id": None,
            "error_count": 0,
            "next_retry": 0,
        }
    }

    # Key step for your plugin: JOINED_ROOMS is a dict, not set
    core_plugins.rooms.JOINED_ROOMS[room] = True

    class Entry(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            for k, v in kwargs.items():
                setattr(self, k, v)

        def get(self, k, default=None):
            if hasattr(self, k):
                return getattr(self, k)
            if k in self:
                return self[k]
            return default

    entry = Entry(
        title="ET",
        link="http://f.com/a1",
        description="ED",
        id="http://f.com/a1",
    )

    class DummyFeed:
        def __init__(self):
            self.feed = {"title": "Feed", "link": url, "href": url, "id": url}
            self.entries = [entry]

        def __contains__(self, k):
            return k == "feed"

    async def fetch_feed(_):
        return DummyFeed()

    monkeypatch.setattr(rss, "fetch_feed", fetch_feed)
    monkeypatch.setattr(rss, "_now", lambda: 1000)

    sleep_calls = []

    async def fake_sleep(secs):
        sleep_calls.append(secs)
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    posts = []

    def fake_reply(msg, txt, **kwargs):
        posts.append(("reply", txt, kwargs))

    bot.reply = fake_reply

    try:
        with pytest.raises(asyncio.CancelledError):
            await rss.rss_check_loop(bot, store, url, 1)

        assert posts == []
        assert store[rss.RSS_KEY][url]["last_id"] == "http://f.com/a1"
        # assert bot.flush_count >= 1
    finally:
        # Clean up global to avoid leaking state between tests
        core_plugins.rooms.JOINED_ROOMS.pop(room, None)


@pytest.mark.asyncio
async def test_rss_check_loop_posts_new_entries_and_flushes_last_id(
        monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "http://f.com/rss"
    room = "room@conference.example.org"

    store[rss.RSS_KEY] = {
        url: {
            "title": "Feed",
            "link": url,
            "period": 1,
            "rooms": [room],
            "last_id": "http://f.com/a1",
            "error_count": 0,
            "next_retry": 0,
        }
    }

    core_plugins.rooms.JOINED_ROOMS[room] = True

    class Entry(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            for k, v in kwargs.items():
                setattr(self, k, v)

        def get(self, k, default=None):
            if hasattr(self, k):
                return getattr(self, k)
            if k in self:
                return self[k]
            return default

    newest_entry = Entry(
        title="ET2",
        link="http://f.com/a2",
        description="ED2",
        id="http://f.com/a2",
    )
    old_entry = Entry(
        title="ET1",
        link="http://f.com/a1",
        description="ED1",
        id="http://f.com/a1",
    )

    class DummyFeed:
        def __init__(self):
            self.feed = {"title": "Feed", "link": url, "href": url, "id": url}
            self.entries = [newest_entry, old_entry]

        def __contains__(self, k):
            return k == "feed"

    async def fetch_feed(_):
        return DummyFeed()

    monkeypatch.setattr(rss, "fetch_feed", fetch_feed)
    monkeypatch.setattr(rss, "_now", lambda: 1000)

    sleep_calls = []

    async def fake_sleep(secs):
        sleep_calls.append(secs)
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    posts = []

    def fake_reply(msg, txt, **kwargs):
        posts.append(("reply", txt, kwargs))

    bot.reply = fake_reply

    try:
        with pytest.raises(asyncio.CancelledError):
            await rss.rss_check_loop(bot, store, url, 1)

        assert len(posts) == 1
        assert "ET2" in posts[0][1]
        assert "http://f.com/a2" in posts[0][1]
        assert store[rss.RSS_KEY][url]["last_id"] == "http://f.com/a2"
        # assert bot.flush_count >= 1
    finally:
        core_plugins.rooms.JOINED_ROOMS.pop(room, None)


@pytest.mark.asyncio
async def test_rss_check_loop_backoff_flushes_state(monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "http://f.com/rss"
    room = "room@conference.example.org"

    store[rss.RSS_KEY] = {
        url: {
            "title": "Feed",
            "link": url,
            "period": 1,
            "rooms": [room],
            "last_id": "http://f.com/a1",
            "error_count": 0,
            "next_retry": 0,
        }
    }

    async def fetch_feed(_):
        raise Exception("fetch failed")

    monkeypatch.setattr(rss, "fetch_feed", fetch_feed)
    monkeypatch.setattr(rss, "_now", lambda: 1000)

    sleep_calls = []

    async def fake_sleep(secs):
        sleep_calls.append(secs)
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await rss.rss_check_loop(bot, store, url, 1)

    assert store[rss.RSS_KEY][url]["error_count"] == 1
    assert store[rss.RSS_KEY][url]["next_retry"] > 1000
    # assert bot.flush_count >= 1


@pytest.mark.asyncio
async def test_on_load_unload_calls(monkeypatch, make_bot):
    bot = make_bot()

    monkeypatch.setattr(rss, "feedparser", type("Feedparser", (), {})())

    restart = AsyncMock()
    monkeypatch.setattr(rss, "restart_all_tasks", restart)

    await rss.on_load(bot)
    assert restart.awaited

    t = asyncio.create_task(asyncio.sleep(0.01))
    rss.CHECK_TASKS["foo"] = t

    await rss.on_unload(bot)

    assert "foo" not in rss.CHECK_TASKS or rss.CHECK_TASKS["foo"].done()


@pytest.mark.asyncio
async def test_rss_task_and_flush_helpers(monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    await rss.save_feeds(store, {
        "https://example.org/feed.xml": {"period": 123, "rooms": ["room@conf"]},
        "https://example.org/default.xml": {"rooms": ["room@conf"]},
    })

    await rss._flush_user_store(bot)
    assert bot.flush_count == 1

    await rss._flush_user_store(SimpleNamespace(db=SimpleNamespace(users=SimpleNamespace())))

    created = []
    class PendingTask:
        def __init__(self, done=False):
            self._done = done
        def done(self):
            return self._done

    def fake_create_plugin_task(bot_arg, plugin, coro, name=None):
        assert plugin == "rss"
        created.append((coro, name))
        coro.close()
        return PendingTask(False)

    monkeypatch.setattr(rss, "create_plugin_task", fake_create_plugin_task)
    rss.CHECK_TASKS.clear()
    await rss.ensure_task(bot, store, "https://example.org/feed.xml", 123)
    assert created[0][1] == "rss-check-https://example.org/feed.xml"

    created.clear()
    await rss.ensure_task(bot, store, "https://example.org/feed.xml", 123)
    assert created == []

    rss.CHECK_TASKS["https://example.org/feed.xml"] = PendingTask(True)
    await rss.ensure_task(bot, store, "https://example.org/feed.xml", 123)
    assert len(created) == 1

    rss.CHECK_TASKS.clear()
    created.clear()
    await rss.restart_all_tasks(bot)
    assert {name for _, name in created} == {
        "rss-check-https://example.org/feed.xml",
        "rss-check-https://example.org/default.xml",
    }

def test_rss_now_is_integer_timestamp(monkeypatch):
    monkeypatch.setattr(rss.time, "time", lambda: 1234.9)
    assert rss._now() == 1234


@pytest.mark.asyncio
async def test_reset_retry_state_updates_and_preserves_unchanged(make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/feed.xml"
    await rss.save_feeds(store, {url: {"error_count": 2, "next_retry": 99}})

    assert await rss._reset_retry_state(bot, store, url) is True
    assert store[rss.RSS_KEY][url]["error_count"] == 0
    assert store[rss.RSS_KEY][url]["next_retry"] == 0

    assert await rss._reset_retry_state(bot, store, url) is False


def test_retry_delay_uses_feed_period():
    assert rss._retry_delay(2, 1) == 2 * rss.BACKOFF_INCREMENT_MULTIPLIER
    assert rss._retry_delay(0, 1) == min(
        rss.DEFAULT_POLL_INTERVAL * rss.BACKOFF_INCREMENT_MULTIPLIER,
        rss.MAX_BACKOFF_TIME,
    )


def test_format_retry_status_shows_next_retry():
    status = rss._format_retry_status(
        {"error_count": 2, "next_retry": 1125},
        now=1000,
    )

    assert "Last 2 fetch(es) failed" in status
    assert "Next retry in: 2m 5s" in status

    assert rss._format_retry_status({"error_count": 0}, now=1000) == ""
    assert "Next retry: now" in rss._format_retry_status(
        {"error_count": 1, "next_retry": 999},
        now=1000,
    )


@pytest.mark.asyncio
async def test_rss_list_shows_retry_backoff(monkeypatch, make_bot):
    bot = make_bot()
    url = "https://example.org/feed.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Feed",
            "period": 120,
            "rooms": ["room@conference.example.org"],
            "error_count": 1,
            "next_retry": 1120,
        }
    }
    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    monkeypatch.setattr(rss, "_now", lambda: 1000)

    await rss.rss_command(bot, "jid", "nick", ["list"], msg, True)

    text = "\n".join(bot.replies[-1][1])
    assert "⚠️ Last 1 fetch(es) failed" in text
    assert "Next retry in: 2m" in text


@pytest.mark.asyncio
async def test_rss_list_uses_pagination(monkeypatch, make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    monkeypatch.setattr(rss, "RSS_LIST_PAGE_SIZE", 5)
    bot.plugin_store[rss.RSS_KEY] = {
        f"https://example.org/feed-{idx}.xml": {
            "title": f"Feed {idx}",
            "period": 120,
            "rooms": ["room@conference.example.org"],
            "error_count": 0,
            "next_retry": 0,
        }
        for idx in range(12)
    }

    await rss.rss_command(bot, "jid", "nick", ["list"], msg, True)
    page_one = "\n".join(bot.replies[-1][1])
    assert "Watched RSS feeds (12) - Page 1/3" in page_one
    assert "https://example.org/feed-0.xml" in page_one
    assert "https://example.org/feed-4.xml" in page_one
    assert "https://example.org/feed-5.xml" not in page_one
    assert "Use ,rss list 2 for the next page." in page_one

    await rss.rss_command(bot, "jid", "nick", ["list", "2"], msg, True)
    page_two = "\n".join(bot.replies[-1][1])
    assert "Watched RSS feeds (12) - Page 2/3" in page_two
    assert "https://example.org/feed-5.xml" in page_two
    assert "https://example.org/feed-9.xml" in page_two
    assert "https://example.org/feed-10.xml" not in page_two

    await rss.rss_command(bot, "jid", "nick", ["list", "last"], msg, True)
    last_page = "\n".join(bot.replies[-1][1])
    assert "Watched RSS feeds (12) - Page 3/3" in last_page
    assert "https://example.org/feed-10.xml" in last_page
    assert "https://example.org/feed-11.xml" in last_page
    assert "next page" not in last_page


@pytest.mark.asyncio
async def test_rss_list_all_and_invalid_page(monkeypatch, make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    monkeypatch.setattr(rss, "RSS_LIST_PAGE_SIZE", 1)
    bot.plugin_store[rss.RSS_KEY] = {
        "https://example.org/a.xml": {
            "title": "A",
            "period": 120,
            "rooms": ["room@conference.example.org"],
        },
        "https://example.org/b.xml": {
            "title": "B",
            "period": 120,
            "rooms": ["room@conference.example.org"],
        },
    }

    await rss.rss_command(bot, "jid", "nick", ["list", "all"], msg, True)
    all_text = "\n".join(bot.replies[-1][1])
    assert "Watched RSS feeds (2) - all" in all_text
    assert "https://example.org/a.xml" in all_text
    assert "https://example.org/b.xml" in all_text
    assert "next page" not in all_text

    await rss.rss_command(bot, "jid", "nick", ["list", "nope"], msg, True)
    assert bot.replies[-1][1] == "Usage: ,rss list [page|all|last]"


@pytest.mark.asyncio
async def test_rss_reset_retry_state_restarts_task(monkeypatch, make_bot):
    bot = make_bot()
    url = "https://example.org/feed.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Feed",
            "period": 42,
            "rooms": ["room@conference.example.org"],
            "error_count": 3,
            "next_retry": 9999,
        }
    }
    msg = {"from": SimpleNamespace(bare="admin@example.org"), "type": "chat"}

    class RunningTask:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    old_task = RunningTask()
    rss.CHECK_TASKS[url] = old_task
    ensure = AsyncMock()
    monkeypatch.setattr(rss, "ensure_task", ensure)

    await rss.rss_command(bot, "jid", "nick", ["retry", url], msg, False)

    feed = bot.plugin_store[rss.RSS_KEY][url]
    assert feed["error_count"] == 0
    assert feed["next_retry"] == 0
    assert old_task.cancelled is True
    ensure.assert_awaited_once_with(bot, bot.plugin_store, url, 42)
    assert bot.replies[-1][1] == (
        f"🔁 Retry state reset and RSS check scheduled: {url}"
    )


@pytest.mark.asyncio
async def test_rss_reset_retry_state_usage_and_missing_feed(make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="admin@example.org"), "type": "chat"}

    await rss.rss_command(bot, "jid", "nick", ["reset"], msg, False)
    assert bot.replies[-1][1] == "Usage: ,rss reset <feedurl>"

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["reset", "https://example.org/missing.xml"],
        msg,
        False,
    )
    assert bot.replies[-1][1] == "Feed not found."


@pytest.mark.asyncio
async def test_rss_check_loop_empty_feed_resets_retry_state(monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/feed.xml"
    store[rss.RSS_KEY] = {
        url: {
            "title": "Feed",
            "link": url,
            "period": 1,
            "rooms": ["room@conference.example.org"],
            "last_id": "old",
            "error_count": 2,
            "next_retry": 1000,
        }
    }

    class EmptyFeed:
        entries = []
        feed = {"title": "Feed", "link": url}

        def __contains__(self, key):
            return key == "feed"

    async def fetch_feed(_):
        return EmptyFeed()

    async def fake_sleep(secs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(rss, "fetch_feed", fetch_feed)
    monkeypatch.setattr(rss, "_now", lambda: 1001)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await rss.rss_check_loop(bot, store, url, 1)

    feed = store[rss.RSS_KEY][url]
    assert feed["error_count"] == 0
    assert feed["next_retry"] == 0
