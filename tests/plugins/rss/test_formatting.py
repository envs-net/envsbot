from .helpers import (
    Entry,
    asyncio,
    core_plugins,
    pytest,
    rss,
)


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

    # Key step for your plugin: JOINED_ROOMS is a dict, not set.
    monkeypatch.setitem(core_plugins.rooms.JOINED_ROOMS, room, True)

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

    async def fake_fetch_feed(_):
        return DummyFeed()

    monkeypatch.setattr(rss, "fetch_feed", fake_fetch_feed)
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

    with pytest.raises(asyncio.CancelledError):
        await rss.rss_check_loop(bot, store, url, 1)

    assert posts == []
    assert store[rss.RSS_KEY][url]["last_id"] == "http://f.com/a1"


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

    monkeypatch.setitem(core_plugins.rooms.JOINED_ROOMS, room, True)

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

    async def fake_fetch_feed(_):
        return DummyFeed()

    monkeypatch.setattr(rss, "fetch_feed", fake_fetch_feed)
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

    with pytest.raises(asyncio.CancelledError):
        await rss.rss_check_loop(bot, store, url, 1)

    assert len(posts) == 1
    assert "ET2" in posts[0][1]
    assert "http://f.com/a2" in posts[0][1]
    assert store[rss.RSS_KEY][url]["last_id"] == "http://f.com/a2"


def test_rss_default_and_custom_template_rendering():
    msg = rss._build_rss_message(
        "Feed",
        "Entry",
        "Distinct summary",
        "https://example.org/a",
    )
    assert msg == "[RSS] (Feed) Entry - Distinct summary\nhttps://example.org/a"

    context = rss._build_rss_template_context(
        feed_title="Feed",
        entry_title="Entry",
        entry_desc="Entry",
        entry_link="https://example.org/a",
        feed_url="https://example.org/feed.xml",
        feed_link="https://example.org/",
        entry_id="entry-1",
        entry_date="2026-07-07",
    )
    rendered = rss._build_rss_message_from_context(
        context,
        "📰 $feed_title: $title$summary_line\n$link ($feed_url)",
    )
    assert rendered == (
        "📰 Feed: Entry\n"
        "https://example.org/a (https://example.org/feed.xml)"
    )
    assert context["summary"] == ""
    assert context["summary_line"] == ""


def test_rss_template_validation_and_input_normalization(monkeypatch):
    assert rss._validate_rss_template("$feed_title: $title") is None

    monkeypatch.setattr(rss, "RSS_TEMPLATE_MAX_LENGTH", 12)
    assert "Unknown template variable" in rss._validate_rss_template("$missing")
    assert "Invalid template syntax" in rss._validate_rss_template("${broken")
    assert "must not be empty" in rss._validate_rss_template("   ")
    assert "too long" in rss._validate_rss_template("$feed_title -- too long")
    assert rss._normalize_rss_template_input(" $title\\n$link ") == "$title\n$link"


@pytest.mark.asyncio
async def test_post_new_entries_uses_room_templates(monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/feed.xml"
    room_a = "room-a@conference.example.org"
    room_b = "room-b@conference.example.org"
    store[rss.RSS_KEY] = {
        url: {
            "title": "Feed",
            "link": "https://example.org/",
            "rooms": [room_a, room_b],
            "last_id": "old",
        }
    }
    store[rss.RSS_TEMPLATES_KEY] = {
        room_b: "CUSTOM $feed_title :: $title :: $link",
    }
    monkeypatch.setitem(core_plugins.rooms.JOINED_ROOMS, room_a, True)
    monkeypatch.setitem(core_plugins.rooms.JOINED_ROOMS, room_b, True)

    entry = Entry(
        title="Entry",
        link="https://example.org/a",
        description="Distinct summary",
        published="2026-07-07",
    )

    await rss._post_new_entries(
        bot,
        store,
        url,
        "Feed",
        "https://example.org/",
        [room_a, room_b],
        [(entry, "entry-1")],
    )

    posted = [reply[1] for reply in bot.replies]
    assert "[RSS] (Feed) Entry - Distinct summary\nhttps://example.org/a" in posted
    assert "CUSTOM Feed :: Entry :: https://example.org/a" in posted
    assert store[rss.RSS_KEY][url]["last_id"] == "entry-1"
