from .helpers import (
    AsyncMock,
    Role,
    SimpleNamespace,
    _reply_text,
    logging,
    pytest,
    rss,
)
from plugins.rss import command_support as rss_support
from plugins.rss import commands as rss_commands
from plugins.rss import subscriptions as rss_subscriptions
from plugins.rss import fetch as rss_fetch
from plugins.rss import formatting as rss_formatting
import aiohttp


@pytest.mark.asyncio
async def test_add_existing_feed_replays_persisted_article_numbers(
    monkeypatch, make_bot,
):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/shared.xml"
    old_room = "old@conference.example.org"
    new_room = "new@conference.example.org"
    store[rss.RSS_KEY] = {
        url: {
            "feed_no": 5,
            "title": "Shared feed",
            "link": "https://example.org/",
            "period": 300,
            "rooms": [old_room],
            "last_id": "https://example.org/known-3",
            "posted_count": 12,
        }
    }

    class DummyFeed:
        feed = {"title": "Shared feed", "link": "https://example.org/"}
        entries = [
            SimpleNamespace(
                title="Unseen",
                link="https://example.org/unseen",
                description="",
            ),
            SimpleNamespace(
                title="Known 3",
                link="https://example.org/known-3",
                description="",
            ),
            SimpleNamespace(
                title="Known 2",
                link="https://example.org/known-2",
                description="",
            ),
            SimpleNamespace(
                title="Known 1",
                link="https://example.org/known-1",
                description="",
            ),
        ]

    async def fake_fetch_feed(_url):
        return DummyFeed()

    monkeypatch.setattr(rss_subscriptions, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())
    monkeypatch.setattr(
        rss_subscriptions,
        "config",
        {"max_new_feed_entries": 3},
    )

    msg = {"from": SimpleNamespace(bare=new_room), "type": "groupchat"}
    await rss_subscriptions._add_feed(bot, msg, url, store, new_room)

    burst_texts = [
        _reply_text(reply)
        for reply in bot.replies
        if "Article #" in _reply_text(reply)
    ]
    assert len(burst_texts) == 3
    assert "Article #10" in burst_texts[0]
    assert "known-1" in burst_texts[0]
    assert "Article #11" in burst_texts[1]
    assert "known-2" in burst_texts[1]
    assert "Article #12" in burst_texts[2]
    assert "known-3" in burst_texts[2]
    assert all("unseen" not in text for text in burst_texts)

    saved = store[rss.RSS_KEY][url]
    assert saved["posted_count"] == 12
    assert saved["last_id"] == "https://example.org/known-3"
    assert saved["rooms"] == [old_room, new_room]


@pytest.mark.asyncio
async def test_add_existing_feed_skips_burst_when_persisted_cursor_is_missing(
    monkeypatch, make_bot, caplog,
):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/shared.xml"
    old_room = "old@conference.example.org"
    new_room = "new@conference.example.org"
    store[rss.RSS_KEY] = {
        url: {
            "feed_no": 5,
            "title": "Shared feed",
            "link": "https://example.org/",
            "period": 300,
            "rooms": [old_room],
            "last_id": "https://example.org/no-longer-in-feed",
            "posted_count": 12,
        }
    }

    class DummyFeed:
        feed = {"title": "Shared feed", "link": "https://example.org/"}
        entries = [
            SimpleNamespace(
                title="Unseen",
                link="https://example.org/unseen",
                description="",
            ),
            SimpleNamespace(
                title="Also unseen",
                link="https://example.org/also-unseen",
                description="",
            ),
        ]

    monkeypatch.setattr(
        rss_subscriptions,
        "fetch_feed",
        AsyncMock(return_value=DummyFeed()),
    )
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())

    msg = {"from": SimpleNamespace(bare=new_room), "type": "groupchat"}
    with caplog.at_level(logging.WARNING):
        await rss_subscriptions._add_feed(bot, msg, url, store, new_room)

    texts = [_reply_text(reply) for reply in bot.replies]
    assert all("unseen" not in text.casefold() for text in texts)
    assert "persisted cursor" in caplog.text
    assert store[rss.RSS_KEY][url]["posted_count"] == 12
    assert store[rss.RSS_KEY][url]["last_id"] == (
        "https://example.org/no-longer-in-feed"
    )
    assert store[rss.RSS_KEY][url]["rooms"] == [old_room, new_room]


@pytest.mark.asyncio
async def test_add_existing_feed_without_cursor_skips_historical_fetch_and_burst(
    monkeypatch, make_bot, caplog,
):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/shared.xml"
    old_room = "old@conference.example.org"
    new_room = "new@conference.example.org"
    store[rss.RSS_KEY] = {
        url: {
            "feed_no": 5,
            "title": "Shared feed",
            "link": "https://example.org/",
            "period": 300,
            "rooms": [old_room],
            "last_id": "",
            "posted_count": 0,
        }
    }
    fetch_feed = AsyncMock()
    monkeypatch.setattr(rss_subscriptions, "fetch_feed", fetch_feed)
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())

    msg = {"from": SimpleNamespace(bare=new_room), "type": "groupchat"}
    with caplog.at_level(logging.WARNING):
        await rss_subscriptions._add_feed(bot, msg, url, store, new_room)

    fetch_feed.assert_not_awaited()
    assert "no persisted cursor" in caplog.text
    assert store[rss.RSS_KEY][url]["rooms"] == [old_room, new_room]


@pytest.mark.asyncio
async def test_rss_add_usage_uses_normal_prefix_lookup(monkeypatch, make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    monkeypatch.setattr(rss_support, "config", {"prefix": "!"})

    await rss.rss_command(bot, "jid", "nick", ["add"], msg, True)

    assert bot.replies[-1][1].startswith("Usage: !rss add")


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
    monkeypatch.setattr(rss_fetch, "feedparser", type("Feedparser", (), {})())

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

    monkeypatch.setattr(rss_subscriptions, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())

    msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}

    # Add
    await rss.rss_command(bot, "jid1", "nick1", ["add", fake_feed_link],
                          msg, True)
    feeds = store.get(rss.RSS_KEY, {})
    assert fake_feed_link in feeds
    assert feeds[fake_feed_link]["feed_no"] == 1
    assert feeds[fake_feed_link]["posted_count"] == 1

    # Add again to test 'already in feed' and room-join path
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["add", fake_feed_link],
                          msg, True)
    assert any(
        "already added" in _reply_text(reply)
        or "Added room" in _reply_text(reply)
        for reply in bot.replies
    )

    # List
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["list"], msg, True)
    assert any("Watched RSS feeds" in _reply_text(reply) for reply in bot.replies)
    assert any("Feed #1" in _reply_text(reply) for reply in bot.replies)
    assert any("Article: #1" in _reply_text(reply) for reply in bot.replies)

    # Delete (should remove the only room, triggers feed delete in dummy)
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["delete", fake_feed_link],
                          msg, True)
    assert any(
        "no rooms left" in _reply_text(reply)
        or "Removed this room" in _reply_text(reply)
        for reply in bot.replies
    )

    # Delete again (feed not found)
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["delete", fake_feed_link],
                          msg, True)
    assert any("Feed not found" in _reply_text(reply) for reply in bot.replies)

    # Add missing arg
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["add"], msg, True)
    assert any("Usage:" in _reply_text(reply) for reply in bot.replies)

    # Delete missing arg
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["delete"], msg, True)
    assert any("Usage:" in _reply_text(reply) for reply in bot.replies)

    # List with no feeds (store reset)
    bot.plugin_store.clear()
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["list"], msg, True)
    assert any("No feeds configured" in _reply_text(reply) for reply in bot.replies)


@pytest.mark.asyncio
async def test_rss_delete_accepts_feed_number(monkeypatch, make_bot):
    bot = make_bot()
    room = "room@conference.example.org"
    url_one = "https://example.org/one.xml"
    url_two = "https://example.org/two.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        url_one: {"feed_no": 1, "rooms": [room], "period": 120},
        url_two: {"feed_no": 2, "rooms": [room], "period": 120},
    }
    assert rss._resolve_feed_selector(bot.plugin_store[rss.RSS_KEY], "2") == url_two
    assert rss._resolve_feed_selector(bot.plugin_store[rss.RSS_KEY], url_one) == url_one
    assert rss._resolve_feed_selector(bot.plugin_store[rss.RSS_KEY], "99") is None
    monkeypatch.setattr(rss_subscriptions, "_cancel_feed_task", AsyncMock())
    msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}

    await rss.rss_command(bot, "admin@example.org", "admin", ["delete", "1"], msg, True)

    assert url_one not in bot.plugin_store[rss.RSS_KEY]
    assert url_two in bot.plugin_store[rss.RSS_KEY]
    assert rss._next_feed_number(bot.plugin_store[rss.RSS_KEY]) == 1

    bot.replies.clear()
    await rss.rss_command(bot, "admin@example.org", "admin", ["delete", "99"], msg, True)
    assert bot.replies[-1][1] == "Feed #99 not found."

    # Unknown subcommand
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["foobar"], msg, True)
    assert any("Unknown subcommand" in _reply_text(reply) for reply in bot.replies)


@pytest.mark.asyncio
async def test_rss_add_rejects_plain_private_chat(monkeypatch, make_bot):
    bot = make_bot()
    msg = {
        "from": SimpleNamespace(bare="user@example.org", resource="desktop"),
        "type": "chat",
    }

    async def user_role(_jid, room=None):
        return Role.USER

    bot.get_user_role = user_role
    await rss.rss_command(
        bot, "jid1", "nick1", ["add", "example.org/feed"], msg, False
    )
    assert bot.replies[-1][1] == "🔴 Direct RSS subscriptions require trusted role or higher."


@pytest.mark.asyncio
async def test_rss_delete_all_from_private_chat_removes_stale_feed(make_bot):
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

    await rss.rss_command(bot, "jid1", "nick1", ["delete", url, "all"], msg, False)

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

    monkeypatch.setitem(rss_support.JOINED_ROOMS, room, {"nicks": {"alice": {}}})
    monkeypatch.setattr(rss_subscriptions, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())

    try:
        await rss.rss_command(
            bot, "jid1", "nick1", ["add", fake_feed_link], msg, False
        )
    finally:
        rss_support.JOINED_ROOMS.pop(room, None)

    assert fake_feed_link in bot.plugin_store.get(rss.RSS_KEY, {})


@pytest.mark.asyncio
async def test_rss_add_failures(monkeypatch, make_bot):
    bot = make_bot()

    monkeypatch.setattr(rss_fetch, "feedparser", type("Feedparser", (), {})())

    async def raise_exc(url):
        raise Exception("bad feed")

    monkeypatch.setattr(rss_subscriptions, "fetch_feed", raise_exc)
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())

    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    await rss.rss_command(bot, "jid", "nick", ["add", "http://bad/feed"],
                          msg, True)

    assert any("Failed to fetch or parse feed" in r[1] for r in bot.replies)


@pytest.mark.asyncio
async def test_rss_add_expected_failures_log_without_traceback(
        monkeypatch, make_bot, caplog):
    bot = make_bot()

    monkeypatch.setattr(rss_fetch, "feedparser", type("Feedparser", (), {})())

    async def raise_exc(url):
        raise aiohttp.ClientResponseError(
            request_info=None,
            history=(),
            status=404,
            message="Not Found",
        )

    monkeypatch.setattr(rss_subscriptions, "fetch_feed", raise_exc)
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())

    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    with caplog.at_level(logging.WARNING, logger="plugins.rss"):
        await rss.rss_command(
            bot,
            "jid",
            "nick",
            ["add", "https://github.com/envs-net/commits/main.atom"],
            msg,
            True,
        )

    reply = bot.replies[-1][1]
    assert "HTTP 404 Not Found" in reply
    assert "repository name must be part of the URL" in reply
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert not any(record.levelno >= logging.ERROR for record in caplog.records)


@pytest.mark.asyncio
async def test_rss_add_rejects_unsupported_feed_scheme(monkeypatch, make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    await rss.rss_command(bot, "jid", "nick", ["add", "ftp://bad/feed"], msg, True)

    assert any("Failed to fetch or parse feed" in r[1] for r in bot.replies)
    assert not bot.plugin_store.get(rss.RSS_KEY)


@pytest.mark.asyncio
async def test_rss_list_uses_pagination(monkeypatch, make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    monkeypatch.setattr(rss_formatting, "RSS_LIST_PAGE_SIZE", 5)
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
    all_page = "\n".join(bot.replies[-1][1])
    assert "Watched RSS feeds (12) - all" in all_page
    assert "https://example.org/feed-0.xml" in all_page
    assert "https://example.org/feed-11.xml" in all_page
    assert "next page" not in all_page

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

    monkeypatch.setattr(rss_formatting, "RSS_LIST_PAGE_SIZE", 1)
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
    assert bot.replies[-1][1] == (
        "Usage: ,rss list "
        "[own|rooms|mods|trusted|room_jid] [page|all|last]"
    )


@pytest.mark.asyncio
async def test_rss_reset_all_rejects_extra_room_argument(make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="admin@example.org"), "type": "chat"}

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["reset", "all", "room@conference.example.org"],
        msg,
        False,
    )

    assert bot.replies[-1][1] == "Usage: ,rss reset <feedurl|feed_no>|all [room_jid]"


@pytest.mark.asyncio
async def test_rss_plugin_grant_allows_explicit_room_add(monkeypatch, make_bot):
    bot = make_bot()
    bot.get_user_role = AsyncMock(return_value=Role.USER)
    room = "room@conference.example.org"
    url = "https://example.org/feed.rss"

    class DummyFeed:
        def __init__(self):
            self.feed = {"title": "GrantFeed", "link": url}
            self.entries = []

        def __contains__(self, key):
            return key == "feed"

    monkeypatch.setattr(rss_subscriptions, "fetch_feed", AsyncMock(return_value=DummyFeed()))
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())
    monkeypatch.setattr(
        rss_support,
        "user_has_room_plugin_grant",
        AsyncMock(return_value=True),
    )
    msg = {
        "from": SimpleNamespace(bare="alice@example.org", resource="desk"),
        "type": "chat",
    }

    await rss.rss_command(
        bot,
        "alice@example.org",
        "alice",
        ["add", url, room],
        msg,
        False,
    )

    assert url in bot.plugin_store[rss.RSS_KEY]
    assert bot.plugin_store[rss.RSS_KEY][url]["rooms"] == [room]
    rss_support.user_has_room_plugin_grant.assert_awaited_once_with(
        bot, "alice@example.org", "rss", room
    )


@pytest.mark.asyncio
async def test_rss_plugin_grant_requires_target_room_affiliation(monkeypatch, make_bot):
    bot = make_bot()
    bot.get_user_role = AsyncMock(return_value=Role.USER)
    room = "room@conference.example.org"
    url = "https://example.org/feed.rss"
    monkeypatch.setattr(rss_subscriptions, "fetch_feed", AsyncMock())
    monkeypatch.setattr(
        rss_support,
        "user_has_room_plugin_grant",
        AsyncMock(return_value=False),
    )
    msg = {
        "from": SimpleNamespace(bare="alice@example.org", resource="desk"),
        "type": "chat",
    }

    await rss.rss_command(
        bot,
        "alice@example.org",
        "alice",
        ["add", url, room],
        msg,
        False,
    )

    assert rss.RSS_KEY not in bot.plugin_store
    rss_subscriptions.fetch_feed.assert_not_awaited()
    assert "RSS plugin grant" in bot.replies[-1][1]


@pytest.mark.asyncio
async def test_rss_template_show_set_test_unset(make_bot):
    bot = make_bot()
    room = "room@conference.example.org"
    msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}

    await rss.rss_command(bot, "jid", "nick", ["template"], msg, True)
    assert "RSS template for room@conference.example.org (built-in default)" in bot.replies[-1][1]
    assert "$summary_line" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "set", "📰", "$feed_title:", "$title\\n$link"],
        msg,
        True,
    )
    assert "RSS template set" in bot.replies[-1][1]
    assert bot.plugin_store[rss.RSS_TEMPLATES_KEY][room] == "📰 $feed_title: $title\n$link"

    await rss.rss_command(bot, "jid", "nick", ["template", "show"], msg, True)
    assert "(custom)" in bot.replies[-1][1]
    assert "📰 $feed_title" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "test", "[$feed_title]", "$title"],
        msg,
        True,
    )
    assert "RSS template preview" in bot.replies[-1][1]
    assert "[Example Feed] Example entry" in bot.replies[-1][1]

    await rss.rss_command(bot, "jid", "nick", ["template", "unset"], msg, True)
    assert "reset to default" in bot.replies[-1][1]
    assert bot.plugin_store[rss.RSS_TEMPLATES_KEY] == {}


@pytest.mark.asyncio
async def test_rss_global_default_template_show_set_test_unset(make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="admin@example.org"), "type": "chat"}

    await rss.rss_command(
        bot, "admin@example.org", "admin", ["template", "default"], msg, False
    )
    assert "RSS template for global default (built-in)" in bot.replies[-1][1]
    assert rss.DEFAULT_RSS_TEMPLATE in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "set", "default", "GLOBAL", "$title\\n$link"],
        msg,
        False,
    )
    assert "Global default RSS template set for all destinations" in bot.replies[-1][1]
    assert bot.plugin_store[rss.RSS_DEFAULT_TEMPLATE_KEY] == "GLOBAL $title\n$link"

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "show", "global"],
        msg,
        False,
    )
    assert "RSS template for global default (custom)" in bot.replies[-1][1]

    room = "room@conference.example.org"
    room_msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}
    await rss.rss_command(
        bot, "admin@example.org", "admin", ["template", "show"], room_msg, True
    )
    assert "(global default)" in bot.replies[-1][1]
    assert "GLOBAL $title" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "test", "default"],
        msg,
        False,
    )
    assert "GLOBAL Example entry" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "unset", "default"],
        msg,
        False,
    )
    assert "reset to the built-in default" in bot.replies[-1][1]
    assert bot.plugin_store[rss.RSS_DEFAULT_TEMPLATE_KEY] is None


@pytest.mark.asyncio
async def test_rss_global_default_template_requires_global_moderator(make_bot):
    bot = make_bot()
    bot.get_user_role = AsyncMock(return_value=Role.USER)
    msg = {"from": SimpleNamespace(bare="user@example.org"), "type": "chat"}

    await rss.rss_command(
        bot,
        "user@example.org",
        "user",
        ["template", "set", "default", "$title"],
        msg,
        False,
    )

    assert "global moderator role" in bot.replies[-1][1]
    assert rss.RSS_DEFAULT_TEMPLATE_KEY not in bot.plugin_store


@pytest.mark.asyncio
async def test_rss_feed_template_show_set_test_unset(make_bot):
    bot = make_bot()
    room = "room@conference.example.org"
    url = "https://example.org/feed.rss"
    msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "feed_no": 9,
            "title": "Feed Title",
            "link": "https://example.org/",
            "rooms": [room],
            "period": 1200,
        }
    }
    bot.plugin_store[rss.RSS_TEMPLATES_KEY] = {
        room: "ROOM $feed_title :: $title",
    }

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "show", "9"],
        msg,
        True,
    )
    assert "(room custom)" in bot.replies[-1][1]
    assert "ROOM $feed_title" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "set", "9", "FEED", "$feed_title:", "$title"],
        msg,
        True,
    )
    assert "RSS feed template set" in bot.replies[-1][1]
    assert bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY][room][url] == (
        "FEED $feed_title: $title"
    )
    assert "Feed Title" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "show", "9"],
        msg,
        True,
    )
    assert "(feed custom)" in bot.replies[-1][1]
    assert "FEED $feed_title" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "test", "9"],
        msg,
        True,
    )
    assert "RSS template preview" in bot.replies[-1][1]
    assert "FEED Feed Title: Example entry" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "unset", "9"],
        msg,
        True,
    )
    assert "RSS feed template reset" in bot.replies[-1][1]
    assert bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY] == {}


@pytest.mark.asyncio
async def test_rss_feed_template_requires_subscribed_feed(make_bot):
    bot = make_bot()
    room = "room@conference.example.org"
    url = "https://example.org/feed.rss"
    msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}
    bot.plugin_store[rss.RSS_KEY] = {
        url: {"title": "Feed", "rooms": ["other@conference.example.org"]}
    }

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "set", url, "$title"],
        msg,
        True,
    )

    assert "Feed is not configured for room@conference.example.org" in bot.replies[-1][1]
    assert rss.RSS_FEED_TEMPLATES_KEY not in bot.plugin_store

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "show", "99"],
        msg,
        True,
    )
    assert bot.replies[-1][1] == "🔴 Feed #99 not found."


@pytest.mark.asyncio
async def test_rss_delete_cleans_feed_specific_templates(monkeypatch, make_bot):
    bot = make_bot()
    room = "room@conference.example.org"
    other = "other@conference.example.org"
    url = "https://example.org/feed.rss"
    msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Feed",
            "link": "https://example.org/",
            "period": 1200,
            "rooms": [room, other],
        }
    }
    bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY] = {
        room: {url: "ROOM $title"},
        other: {url: "OTHER $title"},
    }
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())

    await rss.rss_command(bot, "jid", "nick", ["delete", url], msg, True)

    assert bot.plugin_store[rss.RSS_KEY][url]["rooms"] == [other]
    assert bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY] == {
        other: {url: "OTHER $title"}
    }

    await rss.rss_command(bot, "jid", "nick", ["delete", url, "all"], msg, True)

    assert url not in bot.plugin_store[rss.RSS_KEY]
    assert bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY] == {}


@pytest.mark.asyncio
async def test_rss_template_validates_unknown_vars_and_direct_room(make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="admin@example.org"), "type": "chat"}
    room = "room@conference.example.org"

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "set", room, "$missing"],
        msg,
        False,
    )
    assert "Unknown template variable: $missing" in bot.replies[-1][1]
    assert rss.RSS_TEMPLATES_KEY not in bot.plugin_store

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "set", room, "$title", "via", "$feed_title"],
        msg,
        False,
    )
    assert bot.plugin_store[rss.RSS_TEMPLATES_KEY][room] == "$title via $feed_title"


def test_rss_template_scope_and_sample_helpers(make_bot):
    room = "room@conference.example.org"
    url = "https://example.org/feed.rss"
    public_msg = {"from": SimpleNamespace(bare=room, resource="nick"), "type": "groupchat"}
    private_msg = {"from": SimpleNamespace(bare="admin@example.org"), "type": "chat"}

    assert rss._looks_like_feed_arg(url) is True
    assert rss._looks_like_feed_arg(room) is False
    assert rss._looks_like_feed_arg("") is False

    class GetterOnlyMessage:
        def __getitem__(self, key):
            raise KeyError(key)

        def get(self, key):
            return "normal" if key == "type" else None

    class AttributeOnlyMessage:
        type = "CHAT"

        def __getitem__(self, key):
            raise KeyError(key)

    assert rss_commands._message_type(GetterOnlyMessage()) == "normal"
    assert rss_commands._message_type(AttributeOnlyMessage()) == "chat"

    assert rss._split_template_scope_args(public_msg, True, [url, "$title"]) == (
        room,
        url,
        ["$title"],
    )
    assert rss._split_template_scope_args(public_msg, True, ["7", "$title"]) == (
        room,
        "7",
        ["$title"],
    )
    assert rss._split_template_scope_args(private_msg, False, [room, url, "$title"]) == (
        room,
        url,
        ["$title"],
    )
    assert rss._split_template_scope_args(private_msg, False, [url]) == (
        None,
        url,
        [],
    )
    assert rss._split_template_scope_args(
        private_msg,
        False,
        [url, "DIRECT", "$title"],
        sender_jid="admin@example.org",
    ) == (
        "admin@example.org",
        url,
        ["$title"],
    )
    assert rss._split_template_scope_args(
        private_msg,
        False,
        ["direct", url, "$title"],
        sender_jid="admin@example.org",
    ) == (
        "admin@example.org",
        url,
        ["$title"],
    )

    assert rss._sample_template_context_for_feed(None, url)["feed_url"] == url
    assert rss._sample_template_context_for_feed(
        {
            "title": "Real Feed",
            "link": "https://example.org/",
            "feed_no": 7,
            "posted_count": 9,
        },
        url,
    )["feed_title"] == "Real Feed"
    assert rss._sample_template_context_for_feed(
        {"feed_no": 7, "posted_count": 9},
        url,
    )["feed_ref"] == f"Feed #7 · Article #9 · {url}"
    assert rss._sample_rss_template_preview("$feed_title $feed_url", None, url) == (
        f"Example Feed {url}"
    )
    assert rss._join_template_args([" $title", "via", "$feed_title "]) == (
        "$title via $feed_title"
    )


@pytest.mark.asyncio
async def test_rss_template_command_usage_permission_and_error_paths(make_bot):
    bot = make_bot()
    room = "room@conference.example.org"
    msg = {"from": SimpleNamespace(bare="admin@example.org"), "type": "chat"}

    await rss.rss_command(bot, "admin@example.org", "admin", ["template"], msg, False)
    assert "RSS template for direct user admin@example.org" in bot.replies[-1][1]
    assert "built-in default" in bot.replies[-1][1]

    bot.get_user_role = AsyncMock(return_value=Role.USER)
    await rss.rss_command(
        bot,
        "user@example.org",
        "user",
        ["template", "show", room],
        msg,
        False,
    )
    assert "RSS plugin grant" in bot.replies[-1][1]

    bot.get_user_role = AsyncMock(return_value=Role.MODERATOR)
    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "show", room, "extra"],
        msg,
        False,
    )
    assert "Usage:" in bot.replies[-1][1]

    room_msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}
    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "set", "direct", "$title"],
        room_msg,
        True,
    )
    assert "Usage:" in bot.replies[-1][1]
    assert rss.RSS_TEMPLATES_KEY not in bot.plugin_store

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "unset", room, "extra"],
        msg,
        False,
    )
    assert "Usage:" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "unset", room],
        msg,
        False,
    )
    assert "already uses the default" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "set", room],
        msg,
        False,
    )
    assert "Template must not be empty" in bot.replies[-1][1]


@pytest.mark.asyncio
async def test_rss_feed_template_command_private_room_and_default_paths(make_bot):
    bot = make_bot()
    room = "room@conference.example.org"
    url = "https://example.org/feed.rss"
    msg = {"from": SimpleNamespace(bare="admin@example.org"), "type": "chat"}
    bot.plugin_store[rss.RSS_KEY] = {
        url: {"title": "Feed", "link": "https://example.org/", "rooms": [room]}
    }

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "show", room, url],
        msg,
        False,
    )
    assert "(built-in default)" in bot.replies[-1][1]
    assert rss.DEFAULT_RSS_TEMPLATE in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "test", room, url, "${broken"],
        msg,
        False,
    )
    assert "Invalid template syntax" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "set", room, url, "$title"],
        msg,
        False,
    )
    assert bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY][room][url] == "$title"

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["template", "reset", room, url],
        msg,
        False,
    )
    assert "RSS feed template reset" in bot.replies[-1][1]

@pytest.mark.asyncio
async def test_rss_personal_template_show_set_test_unset_in_direct_chat(make_bot):
    bot = make_bot()
    user = "trusted@example.org"
    msg = {"from": SimpleNamespace(bare=user), "type": "chat"}
    bot.get_user_role = AsyncMock(return_value=Role.TRUSTED)

    await rss.rss_command(bot, user, "trusted", ["template"], msg, False)
    assert f"RSS template for direct user {user}" in bot.replies[-1][1]
    assert "built-in default" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        user,
        "trusted",
        ["template", "set", "$feed_title", "::", "$title"],
        msg,
        False,
    )
    assert f"Personal RSS template set for {user}" in bot.replies[-1][1]
    assert bot.plugin_store[rss.RSS_TEMPLATES_KEY][user] == (
        "$feed_title :: $title"
    )

    await rss.rss_command(
        bot,
        user,
        "trusted",
        ["template", "test"],
        msg,
        False,
    )
    assert "Example Feed :: Example entry" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        user,
        "trusted",
        ["template", "unset"],
        msg,
        False,
    )
    assert "Personal RSS template reset" in bot.replies[-1][1]
    assert bot.plugin_store[rss.RSS_TEMPLATES_KEY] == {}


@pytest.mark.asyncio
async def test_rss_personal_feed_template_requires_direct_subscription(make_bot):
    bot = make_bot()
    user = "trusted@example.org"
    other = "other@example.org"
    url = "https://example.org/direct.rss"
    msg = {"from": SimpleNamespace(bare=user), "type": "chat"}
    bot.get_user_role = AsyncMock(return_value=Role.TRUSTED)
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Direct Feed",
            "link": "https://example.org/",
            "rooms": [],
            "users": {other: {"role": "trusted"}},
        }
    }

    await rss.rss_command(
        bot,
        user,
        "trusted",
        ["template", "set", url, "DIRECT", "$title"],
        msg,
        False,
    )
    assert f"Feed is not configured for direct user {user}" in bot.replies[-1][1]

    bot.plugin_store[rss.RSS_KEY][url]["users"][user] = {"role": "trusted"}
    await rss.rss_command(
        bot,
        user,
        "trusted",
        ["template", "set", url, "DIRECT", "$title"],
        msg,
        False,
    )
    assert f"direct user {user} / {url}" in bot.replies[-1][1]
    assert bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY][user][url] == "$title"


@pytest.mark.asyncio
async def test_rss_personal_template_supports_index_only_stanza(make_bot):
    bot = make_bot()
    user = "trusted@example.org"
    bot.get_user_role = AsyncMock(return_value=Role.TRUSTED)

    class IndexOnlyMessage:
        def __init__(self):
            self.values = {
                "from": SimpleNamespace(bare=user, resource="desktop"),
                "type": "chat",
            }

        def __getitem__(self, key):
            return self.values[key]

    msg = IndexOnlyMessage()
    await rss.rss_command(
        bot,
        user,
        "trusted",
        ["template", "set", "📰", "$title\\n$link"],
        msg,
        False,
    )

    assert f"Personal RSS template set for {user}" in bot.replies[-1][1]
    assert bot.plugin_store[rss.RSS_TEMPLATES_KEY][user] == "📰 $title\n$link"


@pytest.mark.asyncio
async def test_rss_personal_template_requires_trusted_role(make_bot):
    bot = make_bot()
    user = "user@example.org"
    msg = {"from": SimpleNamespace(bare=user), "type": "chat"}
    bot.get_user_role = AsyncMock(return_value=Role.USER)

    await rss.rss_command(
        bot,
        user,
        "user",
        ["template", "set", "$title"],
        msg,
        False,
    )

    assert "Direct RSS templates require trusted role or higher" in bot.replies[-1][1]
    assert rss.RSS_TEMPLATES_KEY not in bot.plugin_store


@pytest.mark.asyncio
async def test_direct_feed_delete_cleans_personal_feed_template(make_bot):
    bot = make_bot()
    user = "trusted@example.org"
    other = "other@example.org"
    url = "https://example.org/direct.rss"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Direct Feed",
            "rooms": [],
            "users": {
                user: {"role": "trusted"},
                other: {"role": "trusted"},
            },
        }
    }
    bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY] = {
        user: {url: "USER $title"},
        other: {url: "OTHER $title"},
    }

    await rss_commands._delete_direct_feed_target(
        bot,
        {"type": "chat"},
        url,
        bot.plugin_store,
        user,
    )

    assert user not in bot.plugin_store[rss.RSS_KEY][url]["users"]
    assert bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY] == {
        other: {url: "OTHER $title"}
    }


def test_rss_health_helpers_show_paused_backoff_errors(monkeypatch):
    now = 1_700_000_000
    feeds = {
        "https://ok.example/feed": {
            "title": "OK",
            "rooms": ["room@conf"],
            "users": {"alice@example.org": {"role": "trusted"}},
            "error_count": 0,
            "next_retry": 0,
            "last_success": now - 60,
            "last_posted": now - 30,
        },
        "https://paused.example/feed": {
            "title": "Paused",
            "rooms": ["room@conf"],
            "paused": True,
            "error_count": 0,
            "next_retry": 0,
        },
        "https://backoff.example/feed": {
            "title": "Backoff",
            "rooms": ["room@conf", "other@conf"],
            "paused_rooms": ["other@conf"],
            "error_count": 2,
            "next_retry": now + 120,
            "last_error": "x" * 140,
        },
        "not-a-dict": "ignored",
    }

    monkeypatch.setattr(rss_support, "_now", lambda: now)

    summary = rss._rss_health_summary(feeds)
    assert summary == "RSS health: 3 feeds · 1 paused · 1 in backoff · 1 with errors"

    lines = rss._rss_health_lines(feeds, now=now)
    joined = "\n".join(lines)
    assert "✅ ok: OK" in joined
    assert "⏸️ paused: Paused" in joined
    assert "🟡 backoff: Backoff" in joined
    assert "rooms: 1/2 active · paused: 1" in joined
    assert "direct users: 1/1 active" in joined
    assert "last post: " + rss._format_rss_timestamp(now - 30) in joined
    assert "last error: " + ("x" * 117) + "..." in joined

    broken = rss._rss_health_lines(feeds, broken_only=True, now=now)
    broken_joined = "\n".join(broken)
    assert "Paused" in broken_joined
    assert "Backoff" in broken_joined
    assert "OK" not in broken_joined


@pytest.mark.asyncio
async def test_rss_pause_resume_state_room_and_global(monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    room = "room@conference.example.org"
    url = "https://example.org/feed.xml"
    store[rss.RSS_KEY] = {
        url: {
            "feed_no": 7,
            "title": "Feed",
            "period": 300,
            "rooms": [room, room.upper(), "other@conference.example.org"],
            "paused_rooms": [],
            "paused": False,
        }
    }
    monkeypatch.setattr(rss_commands, "_cancel_feed_task", AsyncMock())
    monkeypatch.setattr(rss_commands, "ensure_task", AsyncMock())
    msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}

    await rss._rss_set_pause_state(bot, msg, store, url, room, None, paused=True)
    feed = store[rss.RSS_KEY][url]
    assert feed["rooms"] == [room, "other@conference.example.org"]
    assert feed["paused_rooms"] == [room]
    assert "Paused RSS feed for" in _reply_text(bot.replies[-1])
    rss_commands._cancel_feed_task.assert_awaited_with(bot, url)
    rss_commands.ensure_task.assert_awaited_with(bot, store, url, 300)
    rss_commands.ensure_task.reset_mock()

    await rss._rss_set_pause_state(bot, msg, store, url, room, None, paused=True)
    assert "already paused" in _reply_text(bot.replies[-1])

    await rss._rss_set_pause_state(bot, msg, store, url, room, None, paused=False)
    assert feed["paused_rooms"] == []
    rss_commands.ensure_task.assert_awaited_with(bot, store, url, 300)
    assert "Resumed RSS feed for" in _reply_text(bot.replies[-1])

    await rss._rss_set_pause_state(bot, msg, store, url, room, "all", paused=True)
    assert feed["paused"] is True
    assert "globally" in _reply_text(bot.replies[-1])
    rss_commands._cancel_feed_task.reset_mock()
    rss_commands.ensure_task.reset_mock()

    await rss._rss_set_pause_state(bot, msg, store, url, room, "all", paused=True)
    assert "already paused globally" in _reply_text(bot.replies[-1])
    rss_commands._cancel_feed_task.assert_not_awaited()
    rss_commands.ensure_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_rss_pause_state_not_found_and_unsubscribed_room(make_bot):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/feed.xml"
    store[rss.RSS_KEY] = {url: {"rooms": ["room@conference.example.org"]}}
    msg = {"from": SimpleNamespace(bare="room@conference.example.org"), "type": "groupchat"}

    await rss._rss_set_pause_state(bot, msg, store, "https://missing.example/feed", None, None, paused=True)
    assert _reply_text(bot.replies[-1]) == "Feed not found."

    await rss._rss_set_pause_state(bot, msg, store, url, None, None, paused=True)
    assert "needs a subscription context" in _reply_text(bot.replies[-1])

    await rss._rss_set_pause_state(
        bot,
        msg,
        store,
        url,
        "other@conference.example.org",
        None,
        paused=True,
    )
    assert "is not subscribed" in _reply_text(bot.replies[-1])


@pytest.mark.asyncio
async def test_rss_command_health_broken_pause_resume(monkeypatch, make_bot):
    bot = make_bot()
    room = "room@conference.example.org"
    url = "https://example.org/feed.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "feed_no": 7,
            "title": "Feed",
            "period": 300,
            "rooms": [room],
            "paused": False,
            "paused_rooms": [],
            "error_count": rss.RSS_BROKEN_ERROR_THRESHOLD,
            "last_error": "boom",
        }
    }
    monkeypatch.setattr(rss_commands, "_cancel_feed_task", AsyncMock())
    monkeypatch.setattr(rss_commands, "ensure_task", AsyncMock())
    msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}

    await rss.rss_command(bot, "jid1", "nick1", ["health"], msg, True)
    assert "RSS health:" in _reply_text(bot.replies[-1])
    assert "Feed" in _reply_text(bot.replies[-1])

    await rss.rss_command(bot, "jid1", "nick1", ["broken"], msg, True)
    assert "Feed" in _reply_text(bot.replies[-1])

    await rss.rss_command(bot, "jid1", "nick1", ["pause", "7"], msg, True)
    assert bot.plugin_store[rss.RSS_KEY][url]["paused_rooms"] == [room]
    assert url in _reply_text(bot.replies[-1])

    await rss.rss_command(bot, "jid1", "nick1", ["resume", url], msg, True)
    assert bot.plugin_store[rss.RSS_KEY][url]["paused_rooms"] == []

    await rss.rss_command(bot, "jid1", "nick1", ["pause", "99"], msg, True)
    assert _reply_text(bot.replies[-1]) == "Feed #99 not found."


@pytest.mark.asyncio
async def test_rss_pause_resume_own_direct_feed_in_private_chat(
    monkeypatch,
    make_bot,
):
    bot = make_bot()
    user = "trusted@example.org"
    url = "https://example.org/direct.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "feed_no": 25,
            "title": "Direct feed",
            "period": 300,
            "rooms": [],
            "users": {
                user: {
                    "owner": user,
                    "role": "trusted",
                    "paused": False,
                }
            },
            "paused": False,
            "paused_rooms": [],
        }
    }

    async def trusted_role(_jid, room=None):
        return Role.TRUSTED

    bot.get_user_role = trusted_role
    monkeypatch.setattr(rss_commands, "_cancel_feed_task", AsyncMock())
    monkeypatch.setattr(rss_commands, "ensure_task", AsyncMock())
    msg = {
        "from": SimpleNamespace(bare=user, resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(bot, user, "trusted", ["pause", "25"], msg, False)

    direct = bot.plugin_store[rss.RSS_KEY][url]["users"][user]
    assert direct["paused"] is True
    assert "Paused RSS feed for trusted@example.org (direct)" in _reply_text(
        bot.replies[-1]
    )
    assert rss._feed_status_label(bot.plugin_store[rss.RSS_KEY][url]) == (
        "paused for all destinations"
    )
    assert rss._rss_health_summary(bot.plugin_store[rss.RSS_KEY]) == (
        "RSS health: 1 feeds · 1 paused · 0 in backoff · 0 with errors"
    )
    own_lines = rss_support._compact_subscription_lines(
        bot.plugin_store[rss.RSS_KEY],
        "own",
        owner=user,
    )
    assert any("| paused |" in line for line in own_lines)

    await rss.rss_command(
        bot,
        user,
        "trusted",
        ["resume", "25", user],
        msg,
        False,
    )

    assert direct["paused"] is False
    assert "Resumed RSS feed for trusted@example.org (direct)" in _reply_text(
        bot.replies[-1]
    )
    assert rss._feed_status_label(bot.plugin_store[rss.RSS_KEY][url]) == "ok"
    assert rss._rss_health_summary(bot.plugin_store[rss.RSS_KEY]) == (
        "RSS health: 1 feeds · 0 paused · 0 in backoff · 0 with errors"
    )


@pytest.mark.asyncio
async def test_rss_pause_direct_feed_rejects_unsubscribed_private_sender(make_bot):
    bot = make_bot()
    user = "trusted@example.org"
    url = "https://example.org/direct.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "feed_no": 25,
            "title": "Direct feed",
            "period": 300,
            "rooms": [],
            "users": {"other@example.org": {"role": "trusted"}},
        }
    }

    async def trusted_role(_jid, room=None):
        return Role.TRUSTED

    bot.get_user_role = trusted_role
    msg = {
        "from": SimpleNamespace(bare=user, resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(bot, user, "trusted", ["pause", "25"], msg, False)

    assert _reply_text(bot.replies[-1]) == "ℹ️ You are not subscribed to this feed."


@pytest.mark.asyncio
async def test_admin_can_pause_another_direct_subscription(monkeypatch, make_bot):
    bot = make_bot()
    admin = "admin@example.org"
    user = "trusted@example.org"
    url = "https://example.org/direct.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "feed_no": 25,
            "title": "Direct feed",
            "period": 300,
            "rooms": [],
            "users": {user: {"role": "trusted"}},
        }
    }

    async def admin_role(_jid, room=None):
        return Role.ADMIN

    bot.get_user_role = admin_role
    monkeypatch.setattr(rss_commands, "_cancel_feed_task", AsyncMock())
    monkeypatch.setattr(rss_commands, "ensure_task", AsyncMock())
    msg = {
        "from": SimpleNamespace(bare=admin, resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(
        bot,
        admin,
        "admin",
        ["pause", "25", user],
        msg,
        False,
    )

    assert bot.plugin_store[rss.RSS_KEY][url]["users"][user]["paused"] is True


@pytest.mark.asyncio
async def test_trusted_user_can_add_and_remove_own_direct_feed(monkeypatch, make_bot):
    bot = make_bot()
    url = "https://example.org/direct.xml"
    msg = {"from": SimpleNamespace(bare="trusted@example.org", resource="phone"), "type": "chat"}

    async def trusted_role(_jid, room=None):
        return Role.TRUSTED

    class DummyFeed:
        feed = {"title": "Direct feed", "link": url}
        entries = []

    bot.get_user_role = trusted_role
    monkeypatch.setattr(rss_subscriptions, "fetch_feed", AsyncMock(return_value=DummyFeed()))
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())

    await rss.rss_command(bot, "trusted@example.org", "trusted", ["add", url], msg, False)
    assert bot.plugin_store[rss.RSS_KEY][url]["users"]["trusted@example.org"]["role"] == "trusted"

    await rss.rss_command(bot, "trusted@example.org", "trusted", ["remove", url], msg, False)
    assert url not in bot.plugin_store[rss.RSS_KEY]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "redundant_target",
    (
        "trusted@example.org",
        "TRUSTED@EXAMPLE.ORG/phone",
        "MEINE_JID",
    ),
)
async def test_direct_add_ignores_redundant_own_jid_or_placeholder(
    monkeypatch,
    make_bot,
    redundant_target,
):
    bot = make_bot()
    owner = "trusted@example.org"
    url = "https://example.org/direct.xml"
    msg = {
        "from": SimpleNamespace(bare=owner, resource="phone"),
        "type": "chat",
    }
    bot.get_user_role = AsyncMock(return_value=Role.TRUSTED)

    class DummyFeed:
        feed = {"title": "Direct feed", "link": url}
        entries = []

    monkeypatch.setattr(
        rss_subscriptions,
        "fetch_feed",
        AsyncMock(return_value=DummyFeed()),
    )
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())
    room_grant = AsyncMock(return_value=False)
    monkeypatch.setattr(
        rss_support,
        "user_has_room_plugin_grant",
        room_grant,
    )

    await rss.rss_command(
        bot,
        owner,
        "trusted",
        ["add", url, redundant_target],
        msg,
        False,
    )

    feed = bot.plugin_store[rss.RSS_KEY][url]
    assert feed["rooms"] == []
    assert set(feed["users"]) == {owner}
    assert "Added direct RSS feed" in bot.replies[-1][1]
    room_grant.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_direct_feed_initializes_cursor_from_add_snapshot(
    monkeypatch, make_bot
):
    bot = make_bot()
    url = "https://example.org/direct.xml"
    msg = {
        "from": SimpleNamespace(
            bare="trusted@example.org",
            resource="phone",
        ),
        "type": "chat",
    }

    class DummyFeed:
        feed = {"title": "Direct feed", "link": url}
        entries = [
            {
                "title": "Current entry",
                "link": "https://example.org/current",
                "id": "current-entry",
            }
        ]

    monkeypatch.setattr(
        rss_subscriptions,
        "fetch_feed",
        AsyncMock(return_value=DummyFeed()),
    )
    ensure_task = AsyncMock()
    monkeypatch.setattr(rss_subscriptions, "ensure_task", ensure_task)

    await rss_commands._add_direct_feed(
        bot,
        msg,
        url,
        bot.plugin_store,
        "trusted@example.org",
        Role.TRUSTED,
    )

    feed = bot.plugin_store[rss.RSS_KEY][url]
    assert feed["last_id"] == "https://example.org/current"
    assert feed["users"] == {
        "trusted@example.org": {
            "owner": "trusted@example.org",
            "role": "trusted",
            "paused": False,
        }
    }
    ensure_task.assert_awaited_once_with(
        bot,
        bot.plugin_store,
        url,
        feed["period"],
    )
    assert "New entries will be delivered in this chat." in bot.replies[-1][1]


@pytest.mark.asyncio
async def test_existing_feed_direct_subscription_keeps_existing_cursor(
    monkeypatch, make_bot
):
    bot = make_bot()
    url = "https://example.org/shared.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Shared feed",
            "link": url,
            "period": 300,
            "rooms": ["room@conference.example.org"],
            "users": {},
            "last_id": "already-seen",
        }
    }
    monkeypatch.setattr(rss_subscriptions, "fetch_feed", AsyncMock())
    monkeypatch.setattr(rss_subscriptions, "ensure_task", AsyncMock())

    await rss_commands._add_direct_feed(
        bot,
        {"type": "chat"},
        url,
        bot.plugin_store,
        "trusted@example.org",
        Role.TRUSTED,
    )

    feed = bot.plugin_store[rss.RSS_KEY][url]
    assert feed["last_id"] == "already-seen"
    rss_subscriptions.fetch_feed.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_direct_feed_rejects_invalid_subscriber_jid(make_bot):
    bot = make_bot()
    url = "https://example.org/direct.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Direct feed",
            "period": 300,
            "rooms": [],
            "users": {},
        }
    }
    msg = {"from": SimpleNamespace(bare="admin@example.org"), "type": "chat"}

    await rss_commands._add_direct_feed(
        bot,
        msg,
        url,
        bot.plugin_store,
        "not a jid",
        Role.ADMIN,
    )

    assert bot.replies[-1][1] == "🔴 Invalid direct subscriber JID: not a jid"
    assert bot.plugin_store[rss.RSS_KEY][url]["users"] == {}


@pytest.mark.asyncio
async def test_trusted_direct_feed_limit_is_enforced(monkeypatch, make_bot):
    bot = make_bot()
    owner = "trusted@example.org"
    bot.plugin_store[rss.RSS_KEY] = {
        f"https://example.org/{idx}.xml": {
            "title": str(idx), "rooms": [], "users": {owner: {"role": "trusted"}}
        }
        for idx in range(2)
    }
    msg = {"from": SimpleNamespace(bare=owner, resource="phone"), "type": "chat"}

    async def trusted_role(_jid, room=None):
        return Role.TRUSTED

    bot.get_user_role = trusted_role
    monkeypatch.setattr(rss_commands, "RSS_TRUSTED_MAX_FEEDS", 2)

    await rss.rss_command(bot, owner, "trusted", ["add", "https://example.org/new.xml"], msg, False)
    assert bot.replies[-1][1] == "🔴 Trusted RSS feed limit reached (2)."


@pytest.mark.asyncio
async def test_admin_can_remove_trusted_users_direct_feed(make_bot):
    bot = make_bot()
    url = "https://example.org/direct.xml"
    owner = "trusted@example.org"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {"title": "Direct", "rooms": [], "users": {owner: {"role": "trusted"}}}
    }
    msg = {"from": SimpleNamespace(bare="admin@example.org", resource="desktop"), "type": "chat"}

    async def admin_role(_jid, room=None):
        return Role.ADMIN

    bot.get_user_role = admin_role
    await rss.rss_command(bot, "admin@example.org", "admin", ["remove", url, owner], msg, False)
    assert url not in bot.plugin_store[rss.RSS_KEY]


@pytest.mark.asyncio
async def test_admin_can_remove_all_direct_feeds_for_one_user(
    monkeypatch,
    make_bot,
):
    bot = make_bot()
    owner = "trusted@example.org"
    other = "other@example.org"
    removed_url = "https://example.org/removed.xml"
    shared_url = "https://example.org/shared.xml"
    untouched_url = "https://example.org/untouched.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        removed_url: {
            "title": "Removed",
            "rooms": [],
            "users": {owner.upper(): {"role": "trusted"}},
        },
        shared_url: {
            "title": "Shared",
            "rooms": ["room@conference.example.org"],
            "users": {
                owner: {"role": "trusted"},
                other: {"role": "trusted"},
            },
        },
        untouched_url: {
            "title": "Untouched",
            "rooms": [],
            "users": {other: {"role": "trusted"}},
        },
    }
    bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY] = {
        owner: {
            removed_url: "OWNER REMOVED",
            shared_url: "OWNER SHARED",
        },
        other: {
            shared_url: "OTHER SHARED",
            untouched_url: "OTHER UNTOUCHED",
        },
    }
    bot.get_user_role = AsyncMock(return_value=Role.ADMIN)
    cancel_task = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(rss_subscriptions, "_cancel_feed_task", cancel_task)
    monkeypatch.setattr(rss_commands, "audit_event", audit)
    msg = {
        "from": SimpleNamespace(
            bare="admin@example.org",
            resource="desktop",
        ),
        "type": "chat",
    }

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["remove", "all", owner],
        msg,
        False,
    )

    feeds = bot.plugin_store[rss.RSS_KEY]
    assert removed_url not in feeds
    assert feeds[shared_url]["users"] == {
        other: {"role": "trusted"},
    }
    assert feeds[untouched_url]["users"] == {
        other: {"role": "trusted"},
    }
    assert bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY] == {
        other: {
            shared_url: "OTHER SHARED",
            untouched_url: "OTHER UNTOUCHED",
        }
    }
    cancel_task.assert_awaited_once_with(bot, removed_url)
    audit.assert_awaited_once_with(
        bot,
        "rss_direct_feeds_bulk_removed",
        actor="admin@example.org",
        target=owner,
        details={"removed": 2},
    )
    assert bot.replies[-1][1] == (
        f"🗑 Removed 2 direct RSS subscriptions for {owner}."
    )


@pytest.mark.asyncio
async def test_bulk_direct_feed_removal_requires_admin_and_direct_chat(
    monkeypatch,
    make_bot,
):
    owner = "trusted@example.org"
    url = "https://example.org/direct.xml"

    bot = make_bot()
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Direct",
            "rooms": [],
            "users": {owner: {"role": "trusted"}},
        }
    }
    bot.get_user_role = AsyncMock(return_value=Role.MODERATOR)
    audit = AsyncMock()
    monkeypatch.setattr(rss_commands, "audit_event", audit)
    direct_msg = {
        "from": SimpleNamespace(
            bare="moderator@example.org",
            resource="desktop",
        ),
        "type": "chat",
    }

    await rss.rss_command(
        bot,
        "moderator@example.org",
        "moderator",
        ["delete", "all", owner],
        direct_msg,
        False,
    )

    assert owner in bot.plugin_store[rss.RSS_KEY][url]["users"]
    assert "Only owner, superadmin, or admin" in bot.replies[-1][1]
    audit.assert_not_awaited()

    bot.get_user_role = AsyncMock(return_value=Role.ADMIN)
    room_msg = {
        "from": SimpleNamespace(bare="room@conference.example.org"),
        "type": "groupchat",
    }
    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["delete", "all", owner],
        room_msg,
        True,
    )

    assert owner in bot.plugin_store[rss.RSS_KEY][url]["users"]
    assert "only available in a normal 1:1 chat" in bot.replies[-1][1]
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_bulk_direct_feed_removal_handles_invalid_or_empty_target(
    monkeypatch,
    make_bot,
):
    bot = make_bot()
    bot.get_user_role = AsyncMock(return_value=Role.ADMIN)
    audit = AsyncMock()
    monkeypatch.setattr(rss_commands, "audit_event", audit)
    msg = {
        "from": SimpleNamespace(
            bare="admin@example.org",
            resource="desktop",
        ),
        "type": "chat",
    }

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["delete", "all", "not a jid"],
        msg,
        False,
    )
    assert bot.replies[-1][1] == (
        "🔴 Invalid direct subscriber JID: not a jid"
    )

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["delete", "all", "missing@example.org"],
        msg,
        False,
    )
    assert bot.replies[-1][1] == (
        "ℹ️ No direct RSS subscriptions found for missing@example.org."
    )
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_trusted_user_cannot_remove_another_direct_subscription(make_bot):
    bot = make_bot()
    url = "https://example.org/shared.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Shared", "rooms": [],
            "users": {
                "alice@example.org": {"role": "trusted"},
                "bob@example.org": {"role": "trusted"},
            },
        }
    }
    msg = {"from": SimpleNamespace(bare="alice@example.org", resource="phone"), "type": "chat"}

    async def trusted_role(_jid, room=None):
        return Role.TRUSTED

    bot.get_user_role = trusted_role
    await rss.rss_command(
        bot, "alice@example.org", "alice",
        ["remove", url, "bob@example.org"], msg, False,
    )
    assert "bob@example.org" in bot.plugin_store[rss.RSS_KEY][url]["users"]
    assert "Only owner, superadmin, or admin" in bot.replies[-1][1]


def test_compact_subscription_lines_groups_room_feeds_by_room():
    feeds = {
        "https://example.org/z.xml": {
            "title": "Zulu",
            "period": 1200,
            "rooms": ["z-room@conference.example.org", "a-room@conference.example.org"],
            "paused_rooms": ["A-ROOM@conference.example.org"],
        },
        "https://example.org/a.xml": {
            "title": "Alpha",
            "period": 600,
            "rooms": ["a-room@conference.example.org"],
        },
    }

    lines = rss_commands._compact_subscription_lines(feeds)

    assert lines[:6] == [
        "Room feeds (3):",
        "• a-room@conference.example.org",
        "  • #1 · Zulu | no articles yet | paused | 1200s | https://example.org/z.xml",
        "  • #2 · Alpha | no articles yet | ok | 600s | https://example.org/a.xml",
        "• z-room@conference.example.org",
        "  • #1 · Zulu | no articles yet | ok | 1200s | https://example.org/z.xml",
    ]
    assert lines.count("• a-room@conference.example.org") == 1


def test_compact_subscription_lines_keeps_direct_feed_sections():
    feeds = {
        "https://example.org/direct.xml": {
            "title": "Direct",
            "period": 300,
            "rooms": [],
            "users": {
                "trusted@example.org": {"role": "trusted"},
                "mod@example.org": {"role": "moderator"},
            },
        }
    }

    lines = rss_commands._compact_subscription_lines(feeds)

    assert lines[0:2] == ["Room feeds (0):", "• none"]
    assert "Moderator feeds (1):" in lines
    assert "• #1 · Direct | no articles yet | ok | 300s | mod@example.org | https://example.org/direct.xml" in lines
    assert "Trusted user feeds (1):" in lines
    assert "• #1 · Direct | no articles yet | ok | 300s | trusted@example.org | https://example.org/direct.xml" in lines


def test_compact_subscription_lines_can_select_one_section():
    feeds = {
        "https://example.org/shared.xml": {
            "title": "Shared",
            "period": 900,
            "rooms": ["room@conference.example.org"],
            "users": {
                "mod@example.org": {"role": "moderator"},
                "trusted@example.org": {"role": "trusted"},
            },
        }
    }

    assert rss_commands._compact_subscription_lines(feeds, "rooms") == [
        "Room feeds (1):",
        "• room@conference.example.org",
        "  • #1 · Shared | no articles yet | ok | 900s | https://example.org/shared.xml",
    ]
    assert rss_commands._compact_subscription_lines(feeds, "mods") == [
        "Moderator feeds (1):",
        "• #1 · Shared | no articles yet | ok | 900s | mod@example.org | https://example.org/shared.xml",
    ]
    assert rss_commands._compact_subscription_lines(feeds, "trusted") == [
        "Trusted user feeds (1):",
        "• #1 · Shared | no articles yet | ok | 900s | trusted@example.org | https://example.org/shared.xml",
    ]
    assert rss_commands._compact_subscription_lines(
        feeds,
        "own",
        owner="MOD@example.org/device",
    ) == [
        "Own direct feeds (1):",
        "• #1 · Shared | no articles yet | ok | 900s | mod@example.org | https://example.org/shared.xml",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selector", "expected_heading", "excluded_headings"),
    [
        ("rooms", "Room feeds (1):", {"Moderator feeds", "Trusted user feeds"}),
        ("mods", "Moderator feeds (1):", {"Room feeds", "Trusted user feeds"}),
        ("trusted", "Trusted user feeds (1):", {"Room feeds", "Moderator feeds"}),
    ],
)
async def test_global_moderator_can_filter_compact_rss_list(
    make_bot,
    selector,
    expected_heading,
    excluded_headings,
):
    bot = make_bot()
    bot.plugin_store[rss.RSS_KEY] = {
        "https://example.org/shared.xml": {
            "title": "Shared",
            "period": 900,
            "rooms": ["room@conference.example.org"],
            "users": {
                "mod@example.org": {"role": "moderator"},
                "trusted@example.org": {"role": "trusted"},
            },
        }
    }
    msg = {
        "from": SimpleNamespace(bare="moderator@example.org", resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(
        bot,
        "moderator@example.org",
        "moderator",
        ["list", selector],
        msg,
        False,
    )

    lines = bot.replies[-1][1]
    assert lines[0] == expected_heading
    assert all(
        not any(heading in line for heading in excluded_headings)
        for line in lines
    )


@pytest.mark.asyncio
async def test_trusted_user_compact_rss_list_shows_only_own_feeds(make_bot):
    bot = make_bot()
    bot.plugin_store[rss.RSS_KEY] = {
        "https://example.org/shared.xml": {
            "title": "Shared",
            "period": 900,
            "rooms": ["room@conference.example.org"],
            "users": {
                "alice@example.org": {"role": "trusted"},
                "bob@example.org": {"role": "trusted"},
                "mod@example.org": {"role": "moderator"},
            },
        }
    }
    msg = {
        "from": SimpleNamespace(bare="alice@example.org", resource="phone"),
        "type": "chat",
    }

    async def trusted_role(_jid, room=None):
        return Role.TRUSTED

    bot.get_user_role = trusted_role

    await rss.rss_command(
        bot,
        "alice@example.org",
        "alice",
        ["list"],
        msg,
        False,
    )

    lines = bot.replies[-1][1]
    assert lines == [
        "Trusted user feeds (1):",
        "• #1 · Shared | no articles yet | ok | 900s | alice@example.org | https://example.org/shared.xml",
    ]
    assert all("bob@example.org" not in line for line in lines)
    assert all("mod@example.org" not in line for line in lines)


@pytest.mark.asyncio
async def test_admin_can_list_only_own_direct_feeds(monkeypatch, make_bot):
    bot = make_bot()
    bot.plugin_store[rss.RSS_KEY] = {
        "https://example.org/alice.xml": {
            "title": "Alice feed",
            "period": 300,
            "rooms": ["room@conference.example.org"],
            "users": {
                "admin@example.org": {"role": "admin"},
                "other-admin@example.org": {"role": "admin"},
            },
        },
        "https://example.org/second.xml": {
            "title": "Second feed",
            "period": 600,
            "rooms": [],
            "users": {
                "ADMIN@example.org": {"role": "admin"},
                "trusted@example.org": {"role": "trusted"},
            },
        },
    }
    bot.get_user_role = AsyncMock(return_value=Role.ADMIN)
    msg = {
        "from": SimpleNamespace(
            bare="admin@example.org",
            resource="desktop",
        ),
        "type": "chat",
    }
    monkeypatch.setattr(
        rss_commands,
        "config",
        {"prefix": ",", "rss_list_page_size": 1},
    )

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["list", "own", "1"],
        msg,
        False,
    )

    lines = bot.replies[-1][1]
    assert lines == [
        "Own direct feeds (2 feeds, 0 articles) - Page 1/2:",
        "• #1 · Alice feed | no articles yet | ok | 300s | admin@example.org | https://example.org/alice.xml",
        "",
        "Use ,rss list own 2 for the next page.",
    ]
    assert all("other-admin@example.org" not in line for line in lines)
    assert all("trusted@example.org" not in line for line in lines)
    assert all("room@conference.example.org" not in line for line in lines)

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["list", "own", "2"],
        msg,
        False,
    )

    lines = bot.replies[-1][1]
    assert lines == [
        "Own direct feeds (2 feeds, 0 articles) - Page 2/2:",
        "• #2 · Second feed | no articles yet | ok | 600s | ADMIN@example.org | https://example.org/second.xml",
    ]

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["list", "own", "all"],
        msg,
        False,
    )

    lines = bot.replies[-1][1]
    assert lines[0] == "Own direct feeds (2 feeds, 0 articles) - all:"
    assert len(lines) == 3
    assert all("other-admin@example.org" not in line for line in lines)
    assert all("trusted@example.org" not in line for line in lines)


@pytest.mark.asyncio
async def test_rss_list_own_reports_total_articles_across_all_own_feeds(monkeypatch, make_bot):
    bot = make_bot()
    bot.plugin_store[rss.RSS_KEY] = {
        "https://example.org/one.xml": {
            "feed_no": 4,
            "title": "One",
            "period": 300,
            "posted_count": 12,
            "rooms": ["room@conference.example.org"],
            "users": {"admin@example.org": {"role": "admin"}},
        },
        "https://example.org/two.xml": {
            "feed_no": 9,
            "title": "Two",
            "period": 600,
            "posted_count": 23,
            "rooms": [],
            "users": {"ADMIN@example.org": {"role": "admin"}},
        },
        "https://example.org/not-mine.xml": {
            "feed_no": 10,
            "title": "Other",
            "period": 600,
            "posted_count": 1000,
            "rooms": [],
            "users": {"other@example.org": {"role": "trusted"}},
        },
    }
    bot.get_user_role = AsyncMock(return_value=Role.ADMIN)
    msg = {
        "from": SimpleNamespace(bare="admin@example.org", resource="desktop"),
        "type": "chat",
    }
    monkeypatch.setattr(
        rss_commands,
        "config",
        {"prefix": ",", "rss_list_page_size": 1},
    )

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["list", "own", "1"],
        msg,
        False,
    )

    lines = bot.replies[-1][1]
    assert lines[0] == "Own direct feeds (2 feeds, 35 articles) - Page 1/2:"


@pytest.mark.asyncio
async def test_bare_private_delete_by_number_only_removes_own_direct_subscription(make_bot):
    bot = make_bot()
    url = "https://example.org/shared.xml"
    room = "room@conference.example.org"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "feed_no": 9,
            "title": "Shared",
            "period": 300,
            "posted_count": 42,
            "rooms": [room],
            "users": {"moderator@example.org": {"role": "moderator"}},
        }
    }
    msg = {
        "from": SimpleNamespace(bare="moderator@example.org", resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(
        bot,
        "moderator@example.org",
        "moderator",
        ["delete", "9"],
        msg,
        False,
    )

    feed = bot.plugin_store[rss.RSS_KEY][url]
    assert feed["feed_no"] == 9
    assert feed["posted_count"] == 42
    assert feed["rooms"] == [room]
    assert feed.get("users") == {}
    assert bot.replies[-1][1] == (
        "🗑 Removed direct RSS subscription for moderator@example.org: " + url
    )


@pytest.mark.asyncio
async def test_bare_room_delete_by_number_keeps_direct_subscription(make_bot):
    bot = make_bot()
    url = "https://example.org/shared-room.xml"
    room = "room@conference.example.org"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "feed_no": 9,
            "title": "Shared room",
            "period": 300,
            "posted_count": 42,
            "rooms": [room],
            "users": {"trusted@example.org": {"role": "trusted"}},
        }
    }
    msg = {
        "from": SimpleNamespace(bare=room, resource="moderator"),
        "type": "groupchat",
    }

    await rss.rss_command(
        bot,
        "moderator@example.org",
        "moderator",
        ["delete", "9"],
        msg,
        True,
    )

    feed = bot.plugin_store[rss.RSS_KEY][url]
    assert feed["feed_no"] == 9
    assert feed["posted_count"] == 42
    assert feed["rooms"] == []
    assert feed["users"] == {"trusted@example.org": {"role": "trusted"}}


@pytest.mark.asyncio
async def test_explicit_all_delete_by_number_removes_shared_feed_everywhere(make_bot):
    bot = make_bot()
    url = "https://example.org/shared.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "feed_no": 9,
            "title": "Shared",
            "period": 300,
            "rooms": ["room@conference.example.org"],
            "users": {"moderator@example.org": {"role": "moderator"}},
        }
    }
    msg = {
        "from": SimpleNamespace(bare="moderator@example.org", resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(
        bot,
        "moderator@example.org",
        "moderator",
        ["delete", "9", "all"],
        msg,
        False,
    )

    assert bot.plugin_store[rss.RSS_KEY] == {}


@pytest.mark.asyncio
async def test_rss_list_own_requires_normal_direct_chat(make_bot):
    bot = make_bot()
    bot.plugin_store[rss.RSS_KEY] = {
        "https://example.org/feed.xml": {
            "title": "Feed",
            "period": 300,
            "rooms": ["room@conference.example.org"],
            "users": {"admin@example.org": {"role": "admin"}},
        }
    }
    bot.get_user_role = AsyncMock(return_value=Role.ADMIN)
    msg = {
        "from": SimpleNamespace(bare="room@conference.example.org"),
        "type": "groupchat",
    }

    await rss.rss_command(
        bot,
        "admin@example.org",
        "admin",
        ["list", "own"],
        msg,
        True,
    )

    assert bot.replies[-1][1] == (
        "🔴 Own direct RSS subscriptions can only be listed in a normal "
        "1:1 chat."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", ["rooms", "mods"])
async def test_trusted_user_cannot_select_global_compact_sections(
    make_bot,
    selector,
):
    bot = make_bot()
    bot.plugin_store[rss.RSS_KEY] = {
        "https://example.org/direct.xml": {
            "title": "Direct",
            "period": 300,
            "rooms": ["room@conference.example.org"],
            "users": {"alice@example.org": {"role": "trusted"}},
        }
    }
    msg = {
        "from": SimpleNamespace(bare="alice@example.org", resource="phone"),
        "type": "chat",
    }

    async def trusted_role(_jid, room=None):
        return Role.TRUSTED

    bot.get_user_role = trusted_role

    await rss.rss_command(
        bot,
        "alice@example.org",
        "alice",
        ["list", selector],
        msg,
        False,
    )

    assert bot.replies[-1][1] == (
        "🔴 Only global moderators can list room or moderator RSS subscriptions."
    )


@pytest.mark.asyncio
async def test_compact_rss_list_without_selector_keeps_all_sections(make_bot):
    bot = make_bot()
    bot.plugin_store[rss.RSS_KEY] = {
        "https://example.org/shared.xml": {
            "title": "Shared",
            "period": 900,
            "rooms": ["room@conference.example.org"],
            "users": {
                "mod@example.org": {"role": "moderator"},
                "trusted@example.org": {"role": "trusted"},
            },
        }
    }
    msg = {
        "from": SimpleNamespace(bare="moderator@example.org", resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(
        bot,
        "moderator@example.org",
        "moderator",
        ["list"],
        msg,
        False,
    )

    text = "\n".join(bot.replies[-1][1])
    assert "Room feeds (1):" in text
    assert "Moderator feeds (1):" in text
    assert "Trusted user feeds (1):" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("subcommand", ["delete", "del", "remove", "rm"])
async def test_rss_delete_subcommand_aliases_dispatch_identically(
    monkeypatch, make_bot, subcommand
):
    bot = make_bot()
    url = "https://example.org/direct-feed"
    owner = "trusted@example.org"
    bot.plugin_store[rss.RSS_KEY] = {
        url: {
            "title": "Direct feed",
            "link": url,
            "period": 1200,
            "rooms": [],
            "users": {owner: {"added_at": 1}},
        }
    }
    bot.get_user_role = AsyncMock(return_value=Role.TRUSTED)
    msg = {
        "from": SimpleNamespace(bare=owner, resource="desktop"),
        "type": "chat",
    }

    await rss.rss_command(
        bot, owner, "trusted", [subcommand, url], msg, False
    )

    assert bot.plugin_store[rss.RSS_KEY] == {}
    assert any(
        "Removed direct RSS subscription" in _reply_text(reply)
        for reply in bot.replies
    )
