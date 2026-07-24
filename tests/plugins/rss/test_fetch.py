from .helpers import (
    SimpleNamespace,
    asyncio,
    pytest,
    rss,
)
from plugins.rss import fetch as rss_fetch
from plugins.rss import store as rss_store


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
    monkeypatch.setattr(rss_fetch, "feedparser", feedparser_mod)

    async def fake_to_thread(fn, *a, **kw):
        return fn(*a, **kw)

    async def fake_fetch_feed_bytes(url):
        assert url == "https://someurl.com/feed"
        return b"feed-data", url, "application/rss+xml"

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(rss_fetch, "_fetch_feed_bytes", fake_fetch_feed_bytes)

    result = await rss.fetch_feed("https://someurl.com/feed")

    assert result.feed["href"] == "https://someurl.com/feed"
    assert result.feed["id"] == "https://someurl.com/feed"
    assert result.feed["title"] == "Test"


@pytest.mark.asyncio
async def test_fetch_feed_normalizes_paginated_feed_metadata_link(monkeypatch):
    feed_url = "https://pleroma.example/users/envs.rss"
    parsed = SimpleNamespace(
        feed={
            "title": "envs",
            "link": (
                "https://pleroma.example/users/envs/feed.rss"
                "?max_id=B80wAMKUcbZQTt6nq4"
            ),
            "links": [
                {
                    "rel": "alternate",
                    "type": "text/html",
                    "href": "https://pleroma.example/users/envs",
                },
                {
                    "rel": "next",
                    "type": "application/rss+xml",
                    "href": (
                        "https://pleroma.example/users/envs/feed.rss"
                        "?max_id=B80wAMKUcbZQTt6nq4"
                    ),
                },
            ],
        },
        entries=[],
    )

    async def fake_fetch_bytes(url):
        assert url == feed_url
        return b"<rss></rss>", url, "application/rss+xml"

    monkeypatch.setattr(rss_fetch, "_fetch_feed_bytes", fake_fetch_bytes)
    monkeypatch.setattr(
        rss_fetch,
        "feedparser",
        SimpleNamespace(parse=lambda *_args, **_kwargs: parsed),
    )

    result = await rss.fetch_feed(feed_url)

    assert result.feed["link"] == "https://pleroma.example/users/envs"
    assert result.feed["href"] == feed_url
    assert result.feed["id"] == feed_url


@pytest.mark.asyncio
async def test_fetch_feed_rejects_unsafe_feed_url(monkeypatch):
    async def blocked(url, *, allow_private=False):
        assert url == "http://127.0.0.1/feed"
        assert allow_private is False
        raise rss_fetch.UnsafeFetchURL("blocked")

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def get(self, *args, **kwargs):
            pytest.fail("unsafe RSS URL should not be fetched")

    monkeypatch.setattr(rss_fetch, "validate_fetch_url_async", blocked)
    monkeypatch.setattr(
        rss_fetch.aiohttp,
        "ClientSession",
        lambda **kwargs: DummySession(),
    )

    with pytest.raises(rss_fetch.UnsafeFetchURL):
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
                raise rss_fetch.aiohttp.ClientResponseError(
                    None, (), status=self.status
                )

    session_calls = []

    class DummySession:
        def __init__(self, **kwargs):
            self.calls = session_calls

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def get(self, url, allow_redirects=False):
            self.calls.append(url)
            if len(self.calls) == 1:
                return DummyResp(
                    302, url, {"Location": "https://example.org/real.xml"}
                )
            return DummyResp(
                200,
                url,
                {"Content-Type": "application/rss+xml"},
                [b"abc"],
            )

    monkeypatch.setattr(rss_fetch, "validate_fetch_url_async", allow)
    monkeypatch.setattr(rss_fetch.aiohttp, "ClientSession", DummySession)

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

    monkeypatch.setattr(rss_fetch, "RSS_MAX_READ_BYTES", 4)

    class BigSession(DummySession):
        def get(self, url, allow_redirects=False):
            return DummyResp(200, url, {}, [b"123", b"45"])

    monkeypatch.setattr(rss_fetch.aiohttp, "ClientSession", BigSession)

    with pytest.raises(rss_fetch.FetchURLTooLarge):
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


def test_extract_feed_link_prefers_html_alternate_over_paginated_feed_link():
    feed_url = "https://pleroma.example/users/envs.rss"
    feed = {
        "link": (
            "https://pleroma.example/users/envs/feed.rss"
            "?max_id=B80wAMKUcbZQTt6nq4"
        ),
        "links": [
            {
                "rel": "next",
                "type": "application/rss+xml",
                "href": (
                    "https://pleroma.example/users/envs/feed.rss"
                    "?max_id=B80wAMKUcbZQTt6nq4"
                ),
            },
            {
                "rel": "alternate",
                "type": "text/html; charset=utf-8",
                "href": "/users/envs",
            },
        ],
    }

    assert rss._extract_feed_link(feed, feed_url) == (
        "https://pleroma.example/users/envs"
    )


def test_extract_feed_link_removes_only_volatile_cursor_parameters():
    feed_url = "https://example.org/feed.rss"
    feed = {
        "link": (
            "https://example.org/feed.rss?category=news"
            "&max_id=cursor-123&since_id=old"
        ),
    }

    assert rss._extract_feed_link(feed, feed_url) == (
        "https://example.org/feed.rss?category=news"
    )


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
async def test_fetch_error_sleeps_retry_delay(monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/rss.xml"
    store[rss.RSS_KEY] = {url: {"error_count": 0, "next_retry": 0}}
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(rss_store, "RSS_RETRY_INITIAL_DELAY", 300)
    monkeypatch.setattr(rss_store, "RSS_RETRY_BACKOFF_MULTIPLIER", 2.0)
    monkeypatch.setattr(rss_store, "MAX_BACKOFF_TIME", 3600)

    await rss._handle_fetch_error(
        bot,
        store,
        url,
        period=1200,
        now=1000,
        error_count=0,
        exc=RuntimeError("boom"),
    )

    assert store[rss.RSS_KEY][url]["error_count"] == 1
    assert store[rss.RSS_KEY][url]["next_retry"] == 1300
    assert store[rss.RSS_KEY][url]["last_error"] == "boom"
    assert sleep_calls == [300]


@pytest.mark.asyncio
async def test_fetch_timeout_records_readable_error(monkeypatch, make_bot, caplog):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://slow.example.org/rss.xml"
    store[rss.RSS_KEY] = {url: {"error_count": 0, "next_retry": 0}}

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(rss_store, "RSS_RETRY_INITIAL_DELAY", 300)

    with caplog.at_level("WARNING", logger="plugins.rss.store"):
        await rss._handle_fetch_error(
            bot,
            store,
            url,
            period=1200,
            now=1000,
            error_count=0,
            exc=asyncio.TimeoutError(),
        )

    feed = store[rss.RSS_KEY][url]
    assert feed["last_error"] == "Timed out while fetching feed."
    assert (
        "[RSS] Fetch failed url=https://slow.example.org/rss.xml "
        "error=Timed out while fetching feed. retry_in=300s"
    ) in caplog.messages


def test_filter_feeds_for_room_matches_normalized_room_and_skips_missing_rooms():
    matching_feed = {
        "title": "Match",
        "rooms": ["other@conference.example.org", "Room@Conference.Example.Org"],
    }
    feeds = {
        "https://example.org/match.xml": matching_feed,
        "https://example.org/other.xml": {
            "title": "Other",
            "rooms": ["other@conference.example.org"],
        },
        "https://example.org/empty.xml": {"title": "Empty", "rooms": []},
        "https://example.org/missing.xml": {"title": "Missing"},
    }

    assert rss._filter_feeds_for_room(feeds, "room@conference.example.org") == {
        "https://example.org/match.xml": matching_feed,
    }


@pytest.mark.asyncio
async def test_fetch_feed_validates_parsed_feed_shape(monkeypatch):
    async def fake_fetch_bytes(url):
        return b"<html>not a feed</html>", url, "text/html"

    monkeypatch.setattr(rss_fetch, "_fetch_feed_bytes", fake_fetch_bytes)

    def parse_empty(*args, **kwargs):
        return SimpleNamespace(feed={}, entries=[], bozo=False)

    monkeypatch.setattr(rss_fetch, "feedparser", SimpleNamespace(parse=parse_empty))

    with pytest.raises(ValueError, match="does not look like an RSS/Atom feed"):
        await rss.fetch_feed("https://example.org/not-a-feed")


@pytest.mark.asyncio
async def test_fetch_feed_sets_fallback_feed_identifiers(monkeypatch):
    async def fake_fetch_bytes(url):
        return b"<rss></rss>", url, "application/rss+xml"

    parsed = SimpleNamespace(feed={"title": "Fallback Feed"}, entries=[])

    monkeypatch.setattr(rss_fetch, "_fetch_feed_bytes", fake_fetch_bytes)
    monkeypatch.setattr(
        rss_fetch,
        "feedparser",
        SimpleNamespace(parse=lambda *_args, **_kwargs: parsed),
    )

    result = await rss.fetch_feed("https://example.org/feed")

    assert result is parsed
    assert parsed.feed["href"] == "https://example.org/feed"
    assert parsed.feed["id"] == "https://example.org/feed"


@pytest.mark.asyncio
async def test_fetch_feed_overwrites_feed_identifiers_for_stable_storage(monkeypatch):
    async def fake_fetch_bytes(url):
        return b"<rss></rss>", url, "application/rss+xml"

    parsed = SimpleNamespace(
        feed={
            "title": "Existing Feed",
            "href": "https://feeds.example.org/original",
            "id": "urn:original-feed",
        },
        entries=[],
    )

    monkeypatch.setattr(rss_fetch, "_fetch_feed_bytes", fake_fetch_bytes)
    monkeypatch.setattr(
        rss_fetch,
        "feedparser",
        SimpleNamespace(parse=lambda *_args, **_kwargs: parsed),
    )

    result = await rss.fetch_feed("https://example.org/feed")

    assert result is parsed
    assert parsed.feed["href"] == "https://example.org/feed"
    assert parsed.feed["id"] == "https://example.org/feed"
