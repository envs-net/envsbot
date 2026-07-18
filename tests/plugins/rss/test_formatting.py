from .helpers import (
    AsyncMock,
    Entry,
    SimpleNamespace,
    asyncio,
    logging,
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


def test_rss_template_rendering_preserves_one_trailing_separator_line():
    context = dict(rss._SAMPLE_TEMPLATE_CONTEXT)

    assert rss._render_rss_template("$title", context) == "Example entry"
    assert rss._render_rss_template("$title\n", context) == "Example entry\n"
    assert rss._render_rss_template("$title\n\n", context) == "Example entry\n\n"
    assert rss._render_rss_template("$title\n\n\n\n", context) == "Example entry\n\n"


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
    store[rss.RSS_FEED_TEMPLATES_KEY] = {
        room_a: {url: "FEED $title -> $feed_url"},
        room_b: {"https://example.org/other.xml": "IGNORED $title"},
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
    assert "FEED Entry -> https://example.org/feed.xml" in posted
    assert "CUSTOM Feed :: Entry :: https://example.org/a" in posted
    assert store[rss.RSS_KEY][url]["last_id"] == "entry-1"


def test_rss_template_helpers_cover_prefix_variables_and_context(monkeypatch):
    bot = SimpleNamespace(prefix="!")
    assert rss._template_command_prefix(bot) == "!"

    monkeypatch.setattr(rss, "config", {"prefix": "?"})
    assert rss._template_command_prefix(SimpleNamespace(prefix="")) == "?"
    monkeypatch.setattr(rss, "config", {"prefix": ""})
    assert rss._template_command_prefix(SimpleNamespace(prefix=None)) == ","

    usage = rss._rss_template_usage(SimpleNamespace(prefix="."))
    assert usage.startswith("Usage: .rss template")
    assert "template set" in usage
    assert "template unset" in usage
    assert "template test" in usage

    variables = rss._rss_template_variables_text()
    for name in rss.RSS_TEMPLATE_VARIABLES:
        assert f"${name}" in variables
    assert "Use $$" in variables

    assert rss._normalize_template_room_jid(" Room@Conference.Example.org ") == (
        "room@conference.example.org"
    )
    assert rss._validate_rss_template(None) == "Template must not be empty."

    context = rss._build_rss_template_context(
        feed_title="",
        entry_title="",
        entry_desc="Distinct summary",
        entry_link="",
        feed_url="https://example.org/feed.xml",
        feed_link="",
        entry_id=None,
        entry_date=None,
    )
    assert context == {
        "feed_title": "https://example.org/feed.xml",
        "title": "No title",
        "summary": "",
        "summary_line": "",
        "link": "",
        "feed_url": "https://example.org/feed.xml",
        "feed_link": "",
        "id": "",
        "date": "",
    }

    with_summary = rss._build_rss_template_context(
        feed_title="Feed",
        entry_title="Title",
        entry_desc="Distinct summary",
        entry_link="https://example.org/a",
    )
    assert with_summary["summary"] == "Distinct summary"
    assert with_summary["summary_line"] == " - Distinct summary"


def test_entry_date_checks_all_supported_fields():
    assert rss._entry_date(Entry(updated="updated date")) == "updated date"
    assert rss._entry_date(Entry(created="created date")) == "created date"
    assert rss._entry_date(Entry(date="plain date")) == "plain date"
    assert rss._entry_date(Entry()) == ""


def test_invalid_stored_rss_template_falls_back_to_default(caplog):
    context = rss._build_rss_template_context(
        feed_title="Feed",
        entry_title="Entry",
        entry_desc="Summary",
        entry_link="https://example.org/a",
    )

    with caplog.at_level(logging.WARNING):
        rendered = rss._build_rss_message_from_context(context, "$missing")

    assert rendered == "[RSS] (Feed) Entry - Summary\nhttps://example.org/a"
    assert "Invalid stored template" in caplog.text


@pytest.mark.asyncio
async def test_post_rss_entry_to_rooms_reports_any_success(monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/feed.xml"
    context = rss._build_rss_template_context(
        feed_title="Feed",
        entry_title="Entry",
        entry_desc="",
        entry_link="https://example.org/a",
        feed_url=url,
    )
    calls = []

    async def fake_post(_bot, rooms, msg):
        calls.append((rooms, msg))
        return rooms == ["joined@conference.example.org"]

    monkeypatch.setattr(rss, "_post_entry_to_rooms", fake_post)
    store[rss.RSS_TEMPLATES_KEY] = {
        "silent@conference.example.org": "SILENT $title",
        "joined@conference.example.org": "JOINED $title",
    }

    posted = await rss._post_rss_entry_to_rooms(
        bot,
        store,
        ["silent@conference.example.org", "joined@conference.example.org"],
        url,
        context,
    )

    assert posted is True
    assert calls == [
        (["silent@conference.example.org"], "SILENT Entry"),
        (["joined@conference.example.org"], "JOINED Entry"),
    ]


@pytest.mark.asyncio
async def test_post_new_entries_stops_when_feed_was_deleted(monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/feed.xml"
    room = "room@conference.example.org"
    calls = []

    async def fake_post(_bot, _store, rooms, feed_url, context):
        calls.append((rooms, feed_url, context["title"]))
        return False

    async def fake_save(_bot, _store, _url, _entry_id):
        return False

    monkeypatch.setattr(rss, "_post_rss_entry_to_rooms", fake_post)
    monkeypatch.setattr(rss, "_save_last_id_for_template_post", fake_save)

    await rss._post_new_entries(
        bot,
        store,
        url,
        "Feed",
        "https://example.org/",
        [room],
        [(Entry(title="First", link="/first"), "first"),
         (Entry(title="Second", link="/second"), "second")],
    )

    assert calls == [([room], url, "Second")]


@pytest.mark.asyncio
async def test_save_last_id_for_template_post_delegates_to_feed_field(monkeypatch):
    set_field = AsyncMock(return_value=True)
    monkeypatch.setattr(rss, "_set_feed_field", set_field)

    bot = object()
    store = object()
    assert await rss._save_last_id_for_template_post(
        bot,
        store,
        "https://example.org/feed.xml",
        "entry-42",
    ) is True

    set_field.assert_awaited_once_with(
        bot,
        store,
        "https://example.org/feed.xml",
        "last_id",
        "entry-42",
    )
