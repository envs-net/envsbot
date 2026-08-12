from .helpers import (
    SimpleNamespace,
    asyncio,
    pytest,
    rss,
)
from plugins.rss import store as rss_store
from plugins.rss import tasks as rss_tasks


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

    async def fake_fetch_feed(_):
        raise Exception("fetch failed")

    monkeypatch.setattr(rss_tasks, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss_tasks, "_now", lambda: 1000)

    sleep_calls = []

    async def fake_sleep(secs):
        sleep_calls.append(secs)
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await rss.rss_check_loop(bot, store, url, 1)

    assert store[rss.RSS_KEY][url]["error_count"] == 1
    assert store[rss.RSS_KEY][url]["next_retry"] > 1000


def test_rss_now_is_integer_timestamp(monkeypatch):
    monkeypatch.setattr(rss_store.time, "time", lambda: 1234.9)
    assert rss._now() == 1234


def test_feed_numbers_keep_existing_values_and_fill_smallest_free_slots():
    feeds = {
        "https://example.org/two.xml": {"feed_no": 2},
        "https://example.org/legacy.xml": {},
        "https://example.org/duplicate.xml": {"feed_no": 2},
        "https://example.org/four.xml": {"feed_no": 4},
    }

    assert rss._ensure_feed_numbers(feeds) is True
    assert feeds["https://example.org/two.xml"]["feed_no"] == 2
    assert feeds["https://example.org/legacy.xml"]["feed_no"] == 1
    assert feeds["https://example.org/duplicate.xml"]["feed_no"] == 3
    assert feeds["https://example.org/four.xml"]["feed_no"] == 4
    assert rss._ensure_feed_numbers(feeds) is False


def test_next_feed_number_reuses_number_after_feed_record_is_removed():
    feeds = {
        "https://example.org/one.xml": {"feed_no": 1},
        "https://example.org/two.xml": {"feed_no": 2},
        "https://example.org/three.xml": {"feed_no": 3},
    }

    feeds.pop("https://example.org/two.xml")

    assert rss._next_feed_number(feeds) == 2
    assert rss._feed_url_by_number(feeds, 1) == "https://example.org/one.xml"
    assert rss._feed_url_by_number(feeds, 2) is None


@pytest.mark.asyncio
async def test_get_feeds_backfills_and_persists_legacy_feed_numbers(make_bot):
    bot = make_bot()
    store = bot.plugin_store
    store[rss.RSS_KEY] = {
        "https://example.org/a.xml": {"rooms": ["room@conf"]},
        "https://example.org/b.xml": {"rooms": ["room@conf"]},
    }

    feeds = await rss.get_feeds(store)

    assert [feed["feed_no"] for feed in feeds.values()] == [1, 2]
    assert store[rss.RSS_KEY] == feeds


@pytest.mark.asyncio
async def test_get_rss_store_uses_plugin_store(make_bot):
    marker = object()
    bot = make_bot()
    def plugin_store(_name):
        return marker

    bot.db.users.plugin = plugin_store

    assert await rss.get_rss_store(bot) is marker


def test_validate_parsed_feed_accepts_empty_feed_metadata():
    parsed = SimpleNamespace(feed={"title": "Empty but valid"}, entries=[])

    assert rss._validate_parsed_feed(parsed, "https://example.org/feed") is parsed


def test_validate_parsed_feed_rejects_bozo_without_feed_data():
    parsed = SimpleNamespace(
        feed={},
        entries=[],
        bozo=True,
        bozo_exception=ValueError("broken xml"),
    )

    with pytest.raises(ValueError, match="Invalid RSS/Atom feed"):
        rss._validate_parsed_feed(parsed, "https://example.org/feed")


def test_set_mapping_value_supports_dict_and_attribute_objects():
    feed_dict = {}
    rss._set_mapping_value(feed_dict, "href", "https://example.org/feed")
    assert feed_dict == {"href": "https://example.org/feed"}

    feed_object = SimpleNamespace()
    rss._set_mapping_value(feed_object, "id", "urn:feed")
    assert feed_object.id == "urn:feed"


@pytest.mark.asyncio
async def test_rss_room_template_store_helpers(make_bot):
    bot = make_bot()
    store = bot.plugin_store

    assert await rss.get_default_template(store) is None
    await rss.set_default_template(store, "GLOBAL $title")
    assert await rss.get_default_template(store) == "GLOBAL $title"
    assert await rss.get_effective_template(
        store,
        "room@conference.example.org",
        "https://example.org/feed.xml",
    ) == "GLOBAL $title"

    await rss.set_room_template(store, "Room@Conference.Example.org", "$title")

    assert await rss.get_room_template(store, "room@conference.example.org") == "$title"
    assert await rss.get_room_templates(store) == {
        "room@conference.example.org": "$title",
    }
    assert await rss.unset_room_template(store, "room@conference.example.org") is True
    assert await rss.unset_room_template(store, "room@conference.example.org") is False
    assert await rss.get_room_templates(store) == {}

    await rss.set_room_template(store, "room@conference.example.org", "ROOM $title")
    await rss.set_feed_template(
        store,
        "Room@Conference.Example.org",
        "https://example.org/feed.xml",
        "FEED $title",
    )

    assert await rss.get_feed_template(
        store,
        "room@conference.example.org",
        "https://example.org/feed.xml",
    ) == "FEED $title"
    assert await rss.get_effective_template(
        store,
        "room@conference.example.org",
        "https://example.org/feed.xml",
    ) == "FEED $title"
    assert await rss.get_effective_template(
        store,
        "room@conference.example.org",
        "https://example.org/other.xml",
    ) == "ROOM $title"

    assert await rss.unset_feed_template(
        store,
        "room@conference.example.org",
        "https://example.org/feed.xml",
    ) is True
    assert await rss.unset_feed_template(
        store,
        "room@conference.example.org",
        "https://example.org/feed.xml",
    ) is False
    assert await rss.get_feed_templates(store) == {}
    assert await rss.unset_default_template(store) is True
    assert await rss.unset_default_template(store) is False
    assert await rss.get_default_template(store) is None


@pytest.mark.asyncio
async def test_rss_template_store_sanitizes_invalid_shapes(make_bot):
    bot = make_bot()
    store = bot.plugin_store
    store[rss.RSS_TEMPLATES_KEY] = {
        " Room@Conference.Example.org ": "$title",
        "": "ignored",
        "bad@conference.example.org": 42,
    }
    store[rss.RSS_FEED_TEMPLATES_KEY] = {
        " Room@Conference.Example.org ": {
            " https://example.org/feed.xml ": "FEED $title",
            "": "ignored",
            "https://example.org/bad.xml": object(),
        },
        "bad@conference.example.org": "not a mapping",
        "": {"https://example.org/ignored.xml": "$title"},
    }

    assert await rss.get_room_templates(store) == {
        "room@conference.example.org": "$title",
    }
    assert await rss.get_feed_templates(store) == {
        "room@conference.example.org": {
            "https://example.org/feed.xml": "FEED $title",
        }
    }

    await rss.save_room_templates(store, {
        " Room@Conference.Example.org ": "$title",
        "": "ignored",
        "bad@conference.example.org": 42,
    })
    await rss.save_feed_templates(store, {
        " Room@Conference.Example.org ": {
            " https://example.org/feed.xml ": "FEED $title",
            "": "ignored",
            "https://example.org/bad.xml": object(),
        },
        "bad@conference.example.org": "not a mapping",
    })

    assert store[rss.RSS_TEMPLATES_KEY] == {
        "room@conference.example.org": "$title",
    }
    assert store[rss.RSS_FEED_TEMPLATES_KEY] == {
        "room@conference.example.org": {
            "https://example.org/feed.xml": "FEED $title",
        }
    }


@pytest.mark.asyncio
async def test_rss_feed_template_noop_and_cleanup_helpers(make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/feed.xml"
    other_url = "https://example.org/other.xml"
    room = "room@conference.example.org"
    other_room = "other@conference.example.org"

    await rss.set_room_template(store, "", "$title")
    assert store[rss.RSS_TEMPLATES_KEY] == {}

    await rss.set_feed_template(store, "", url, "$title")
    await rss.set_feed_template(store, room, "", "$title")
    assert store.get(rss.RSS_FEED_TEMPLATES_KEY, {}) == {}

    await rss.set_feed_template(store, room, url, "ROOM FEED $title")
    await rss.set_feed_template(store, room, other_url, "OTHER FEED $title")
    await rss.set_feed_template(store, other_room, url, "OTHER ROOM $title")

    assert await rss.unset_feed_templates_for_feed(store, url) == 2
    assert store[rss.RSS_FEED_TEMPLATES_KEY] == {
        room: {other_url: "OTHER FEED $title"},
    }
    assert await rss.unset_feed_templates_for_feed(store, url) == 0

    await rss.set_feed_template(store, other_room, other_url, "OTHER ROOM $title")
    assert await rss.unset_feed_templates_for_room(store, other_room) == 1
    assert other_room not in store[rss.RSS_FEED_TEMPLATES_KEY]
    assert await rss.unset_feed_templates_for_room(store, other_room) == 0


def test_normalize_template_room_jid_cases():
    from plugins.rss.store import _normalize_template_room_jid

    assert _normalize_template_room_jid(None) == ""
    assert _normalize_template_room_jid("") == ""
    assert _normalize_template_room_jid("   ") == ""
    assert _normalize_template_room_jid(
        " Room@Conference.Example.org "
    ) == "room@conference.example.org"
