from .helpers import (
    Entry,
    SimpleNamespace,
    asyncio,
    logging,
    core_plugins,
    pytest,
    rss,
)
from plugins.rss import formatting as rss_formatting
from plugins.rss import tasks as rss_tasks


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

    monkeypatch.setattr(rss_tasks, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss_tasks, "_now", lambda: 1000)

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
            "users": {"alice@example.org": {"role": "trusted"}},
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

    monkeypatch.setattr(rss_tasks, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss_tasks, "_now", lambda: 1000)

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
    assert bot.sent_messages == [
        {
            "mto": "alice@example.org",
            "mbody": "[RSS] (Feed) ET2 - ED2\nhttp://f.com/a2",
            "mtype": "chat",
        }
    ]
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

    monkeypatch.setattr(rss_formatting, "RSS_TEMPLATE_MAX_LENGTH", 12)
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
    room_c = "room-c@conference.example.org"
    store[rss.RSS_KEY] = {
        url: {
            "title": "Feed",
            "link": "https://example.org/",
            "rooms": [room_a, room_b, room_c],
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
    store[rss.RSS_DEFAULT_TEMPLATE_KEY] = "GLOBAL $title -> $link"
    monkeypatch.setitem(core_plugins.rooms.JOINED_ROOMS, room_a, True)
    monkeypatch.setitem(core_plugins.rooms.JOINED_ROOMS, room_b, True)
    monkeypatch.setitem(core_plugins.rooms.JOINED_ROOMS, room_c, True)

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
        [room_a, room_b, room_c],
        [(entry, "entry-1")],
    )

    posted = [reply[1] for reply in bot.replies]
    assert "FEED Entry -> https://example.org/feed.xml" in posted
    assert "CUSTOM Feed :: Entry :: https://example.org/a" in posted
    assert "GLOBAL Entry -> https://example.org/a" in posted
    assert store[rss.RSS_KEY][url]["last_id"] == "entry-1"


def test_rss_template_helpers_cover_prefix_variables_and_context(monkeypatch):
    bot = SimpleNamespace(prefix="!")
    assert rss._template_command_prefix(bot) == "!"

    monkeypatch.setattr(rss_formatting, "config", {"prefix": "?"})
    assert rss._template_command_prefix(SimpleNamespace(prefix="")) == "?"
    monkeypatch.setattr(rss_formatting, "config", {"prefix": ""})
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

    monkeypatch.setattr(rss_formatting, "_post_entry_to_rooms", fake_post)
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

    monkeypatch.setattr(rss_formatting, "_post_rss_entry_to_rooms", fake_post)
    monkeypatch.setattr(rss_formatting, "_update_feed_for_post", fake_save)

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
async def test_update_feed_for_post_updates_last_id(make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/feed.xml"
    store[rss.RSS_KEY] = {url: {"last_id": "entry-1"}}

    assert await rss._update_feed_for_post(
        bot,
        store,
        url,
        lambda feed: rss._set_last_id_in_feed(feed, "entry-42"),
    ) is True
    assert store[rss.RSS_KEY][url]["last_id"] == "entry-42"


@pytest.mark.asyncio
async def test_post_entry_to_users_sends_exact_direct_messages(make_bot):
    bot = make_bot()
    users = ["alice@example.org", "bob@example.org"]
    message = "[RSS] exact message"

    assert await rss_formatting._post_entry_to_users(bot, [], message) == (0, 0)
    assert bot.replies == []
    assert bot.sent_messages == []

    assert await rss_formatting._post_entry_to_users(
        bot,
        users,
        message,
    ) == (2, 2)
    assert bot.replies == []
    assert bot.sent_messages == [
        {
            "mto": "alice@example.org",
            "mbody": message,
            "mtype": "chat",
        },
        {
            "mto": "bob@example.org",
            "mbody": message,
            "mtype": "chat",
        },
    ]


def test_normalize_direct_user_jid_accepts_users_and_rejects_invalid_targets():
    assert rss_formatting._normalize_direct_user_jid(
        " Alice@Example.ORG/Phone "
    ) == "alice@example.org"
    assert rss_formatting._normalize_direct_user_jid("example.org") is None
    assert rss_formatting._normalize_direct_user_jid("not a jid") is None
    assert rss_formatting._normalize_direct_user_jid("") is None


@pytest.mark.asyncio
async def test_post_entry_to_users_continues_after_invalid_or_failed_target(
    make_bot,
):
    bot = make_bot()
    attempted_targets = []

    async def selective_send(message):
        attempted_targets.append(message["mto"])
        if message["mto"] == "bob@example.org":
            return False
        bot.sent_messages.append(message)
        return True

    bot._safe_send_message = selective_send

    result = await rss_formatting._post_entry_to_users(
        bot,
        ["alice@example.org", "not a jid", "bob@example.org"],
        "[RSS] entry",
    )

    assert result == (1, 3)
    assert attempted_targets == ["alice@example.org", "bob@example.org"]
    assert [message["mto"] for message in bot.sent_messages] == [
        "alice@example.org"
    ]


@pytest.mark.asyncio
async def test_send_direct_rss_message_supports_send_fallback_and_errors():
    sent = []

    class Message:
        async def send(self):
            sent.append(True)

    class FallbackBot:
        def make_message(self, *, mto, mbody, mtype):
            assert (mto, mbody, mtype) == (
                "alice@example.org",
                "[RSS] entry",
                "chat",
            )
            return Message()

    assert await rss_formatting._send_direct_rss_message(
        FallbackBot(),
        "alice@example.org",
        "[RSS] entry",
    ) is True
    assert sent == [True]

    class BrokenBot:
        def make_message(self, **_kwargs):
            raise RuntimeError("cannot build stanza")

    assert await rss_formatting._send_direct_rss_message(
        BrokenBot(),
        "alice@example.org",
        "[RSS] entry",
    ) is False


@pytest.mark.asyncio
async def test_post_new_entries_delivers_direct_feed_and_updates_cursor(make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/direct.xml"
    feed = {
        "title": "Direct Feed",
        "link": "https://example.org/",
        "rooms": [],
        "users": {"alice@example.org": {"role": "trusted"}},
        "last_id": "old-entry",
        "posted_count": 0,
    }
    store[rss.RSS_KEY] = {url: feed}

    await rss._post_new_entries(
        bot,
        store,
        url,
        feed["title"],
        feed["link"],
        [],
        [(Entry(title="New entry", link="https://example.org/new"), "new-entry")],
        feed=feed,
    )

    assert bot.sent_messages == [
        {
            "mto": "alice@example.org",
            "mbody": "[RSS] (Direct Feed) New entry\nhttps://example.org/new",
            "mtype": "chat",
        }
    ]
    assert store[rss.RSS_KEY][url]["last_id"] == "new-entry"
    assert store[rss.RSS_KEY][url]["posted_count"] == 1
    assert store[rss.RSS_KEY][url]["last_posted"] > 0


@pytest.mark.asyncio
async def test_post_new_entries_uses_personal_direct_templates(make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/direct.xml"
    feed = {
        "title": "Direct Feed",
        "link": "https://example.org/",
        "rooms": [],
        "users": {
            "alice@example.org": {"role": "trusted"},
            "bob@example.org": {"role": "trusted"},
            "carol@example.org": {"role": "moderator"},
        },
        "last_id": "old-entry",
    }
    store[rss.RSS_KEY] = {url: feed}
    store[rss.RSS_FEED_TEMPLATES_KEY] = {
        "alice@example.org": {url: "ALICE FEED $title"},
    }
    store[rss.RSS_TEMPLATES_KEY] = {
        "bob@example.org": "BOB PERSONAL $feed_title :: $title",
    }
    store[rss.RSS_DEFAULT_TEMPLATE_KEY] = "GLOBAL $title"

    await rss._post_new_entries(
        bot,
        store,
        url,
        feed["title"],
        feed["link"],
        [],
        [(Entry(title="New entry", link="https://example.org/new"), "new-entry")],
        feed=feed,
    )

    assert bot.sent_messages == [
        {
            "mto": "alice@example.org",
            "mbody": "ALICE FEED New entry",
            "mtype": "chat",
        },
        {
            "mto": "bob@example.org",
            "mbody": "BOB PERSONAL Direct Feed :: New entry",
            "mtype": "chat",
        },
        {
            "mto": "carol@example.org",
            "mbody": "GLOBAL New entry",
            "mtype": "chat",
        },
    ]


@pytest.mark.asyncio
async def test_post_new_entries_retains_cursor_when_direct_delivery_fails(
    make_bot,
):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/direct.xml"
    feed = {
        "title": "Direct Feed",
        "link": "https://example.org/",
        "rooms": [],
        "users": {"alice@example.org": {"role": "trusted"}},
        "last_id": "old-entry",
        "posted_count": 0,
    }
    store[rss.RSS_KEY] = {url: feed}

    async def failed_send(_message):
        return False

    bot._safe_send_message = failed_send

    await rss._post_new_entries(
        bot,
        store,
        url,
        feed["title"],
        feed["link"],
        [],
        [(Entry(title="New entry", link="https://example.org/new"), "new-entry")],
        feed=feed,
    )

    assert store[rss.RSS_KEY][url]["last_id"] == "old-entry"
    assert store[rss.RSS_KEY][url]["posted_count"] == 0
    assert "last_posted" not in store[rss.RSS_KEY][url]
