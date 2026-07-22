from .helpers import (
    AsyncMock,
    Role,
    SimpleNamespace,
    _reply_text,
    logging,
    pytest,
    rss,
)
from plugins.rss import commands as rss_commands
from plugins.rss import fetch as rss_fetch
from plugins.rss import formatting as rss_formatting
import aiohttp


@pytest.mark.asyncio
async def test_rss_add_usage_uses_normal_prefix_lookup(monkeypatch, make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    monkeypatch.setattr(rss_commands, "config", {"prefix": "!"})

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

    monkeypatch.setattr(rss_commands, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss_commands, "ensure_task", AsyncMock())

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
    assert any(
        "already added" in _reply_text(reply)
        or "Added room" in _reply_text(reply)
        for reply in bot.replies
    )

    # List
    bot.replies.clear()
    await rss.rss_command(bot, "jid1", "nick1", ["list"], msg, True)
    assert any("Watched RSS feeds" in _reply_text(reply) for reply in bot.replies)

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

    monkeypatch.setitem(rss_commands.JOINED_ROOMS, room, {"nicks": {"alice": {}}})
    monkeypatch.setattr(rss_commands, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss_commands, "ensure_task", AsyncMock())

    try:
        await rss.rss_command(
            bot, "jid1", "nick1", ["add", fake_feed_link], msg, False
        )
    finally:
        rss_commands.JOINED_ROOMS.pop(room, None)

    assert fake_feed_link in bot.plugin_store.get(rss.RSS_KEY, {})


@pytest.mark.asyncio
async def test_rss_add_failures(monkeypatch, make_bot):
    bot = make_bot()

    monkeypatch.setattr(rss_fetch, "feedparser", type("Feedparser", (), {})())

    async def raise_exc(url):
        raise Exception("bad feed")

    monkeypatch.setattr(rss_commands, "fetch_feed", raise_exc)
    monkeypatch.setattr(rss_commands, "ensure_task", AsyncMock())

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

    monkeypatch.setattr(rss_commands, "fetch_feed", raise_exc)
    monkeypatch.setattr(rss_commands, "ensure_task", AsyncMock())

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
        "[rooms|mods|trusted|room_jid] [page|all|last]"
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

    assert bot.replies[-1][1] == "Usage: ,rss reset <feedurl>|all [room_jid]"


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

    monkeypatch.setattr(rss_commands, "fetch_feed", AsyncMock(return_value=DummyFeed()))
    monkeypatch.setattr(rss_commands, "ensure_task", AsyncMock())
    monkeypatch.setattr(
        rss_commands,
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
    rss_commands.user_has_room_plugin_grant.assert_awaited_once_with(
        bot, "alice@example.org", "rss", room
    )


@pytest.mark.asyncio
async def test_rss_plugin_grant_requires_target_room_affiliation(monkeypatch, make_bot):
    bot = make_bot()
    bot.get_user_role = AsyncMock(return_value=Role.USER)
    room = "room@conference.example.org"
    url = "https://example.org/feed.rss"
    monkeypatch.setattr(rss_commands, "fetch_feed", AsyncMock())
    monkeypatch.setattr(
        rss_commands,
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
    rss_commands.fetch_feed.assert_not_awaited()
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
        ["template", "show", url],
        msg,
        True,
    )
    assert "(room custom)" in bot.replies[-1][1]
    assert "ROOM $feed_title" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "set", url, "FEED", "$feed_title:", "$title"],
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
        ["template", "show", url],
        msg,
        True,
    )
    assert "(feed custom)" in bot.replies[-1][1]
    assert "FEED $feed_title" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "test", url],
        msg,
        True,
    )
    assert "RSS template preview" in bot.replies[-1][1]
    assert "FEED Feed Title: Example entry" in bot.replies[-1][1]

    await rss.rss_command(
        bot,
        "jid",
        "nick",
        ["template", "unset", url],
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
    monkeypatch.setattr(rss_commands, "ensure_task", AsyncMock())

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

    assert rss._split_template_scope_args(public_msg, True, [url, "$title"]) == (
        room,
        url,
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

    assert rss._sample_template_context_for_feed(None, url)["feed_url"] == url
    assert rss._sample_template_context_for_feed(
        {"title": "Real Feed", "link": "https://example.org/"},
        url,
    )["feed_title"] == "Real Feed"
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
        ["template", "set", "DIRECT", "$feed_title", "::", "$title"],
        msg,
        False,
    )
    assert f"Personal RSS template set for {user}" in bot.replies[-1][1]
    assert bot.plugin_store[rss.RSS_TEMPLATES_KEY][user] == (
        "DIRECT $feed_title :: $title"
    )

    await rss.rss_command(
        bot,
        user,
        "trusted",
        ["template", "test"],
        msg,
        False,
    )
    assert "DIRECT Example Feed :: Example entry" in bot.replies[-1][1]

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
    assert bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY][user][url] == (
        "DIRECT $title"
    )


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


@pytest.mark.asyncio
async def test_save_last_id(monkeypatch):
    set_field = AsyncMock(return_value=True)
    monkeypatch.setattr(rss_commands, "_set_feed_field", set_field)
    bot = object()
    store = object()
    assert await rss._save_last_id(bot, store, "https://feed.example/rss", "entry-1") is True
    set_field.assert_awaited_once_with(bot, store, "https://feed.example/rss", "last_id", "entry-1")


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

    monkeypatch.setattr(rss_commands, "_now", lambda: now)

    summary = rss._rss_health_summary(feeds)
    assert summary == "RSS health: 3 feeds · 1 paused · 1 in backoff · 1 with errors"

    lines = rss._rss_health_lines(feeds, now=now)
    joined = "\n".join(lines)
    assert "✅ ok: OK" in joined
    assert "⏸️ paused: Paused" in joined
    assert "🟡 backoff: Backoff" in joined
    assert "rooms: 1/2 active · paused: 1" in joined
    assert "direct users: 1" in joined
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
    assert "needs a room context" in _reply_text(bot.replies[-1])

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

    await rss.rss_command(bot, "jid1", "nick1", ["pause", url], msg, True)
    assert bot.plugin_store[rss.RSS_KEY][url]["paused_rooms"] == [room]

    await rss.rss_command(bot, "jid1", "nick1", ["resume", url], msg, True)
    assert bot.plugin_store[rss.RSS_KEY][url]["paused_rooms"] == []


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
    monkeypatch.setattr(rss_commands, "fetch_feed", AsyncMock(return_value=DummyFeed()))
    monkeypatch.setattr(rss_commands, "ensure_task", AsyncMock())

    await rss.rss_command(bot, "trusted@example.org", "trusted", ["add", url], msg, False)
    assert bot.plugin_store[rss.RSS_KEY][url]["users"]["trusted@example.org"]["role"] == "trusted"

    await rss.rss_command(bot, "trusted@example.org", "trusted", ["remove", url], msg, False)
    assert url not in bot.plugin_store[rss.RSS_KEY]


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
        "  • Alpha | ok | 600s | https://example.org/a.xml",
        "  • Zulu | ok | 1200s | https://example.org/z.xml",
        "• z-room@conference.example.org",
        "  • Zulu | ok | 1200s | https://example.org/z.xml",
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
    assert "• Direct | ok | 300s | mod@example.org | https://example.org/direct.xml" in lines
    assert "Trusted user feeds (1):" in lines
    assert "• Direct | ok | 300s | trusted@example.org | https://example.org/direct.xml" in lines


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
        "  • Shared | ok | 900s | https://example.org/shared.xml",
    ]
    assert rss_commands._compact_subscription_lines(feeds, "mods") == [
        "Moderator feeds (1):",
        "• Shared | ok | 900s | mod@example.org | https://example.org/shared.xml",
    ]
    assert rss_commands._compact_subscription_lines(feeds, "trusted") == [
        "Trusted user feeds (1):",
        "• Shared | ok | 900s | trusted@example.org | https://example.org/shared.xml",
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
