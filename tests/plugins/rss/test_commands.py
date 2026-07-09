from .helpers import (
    AsyncMock,
    Role,
    SimpleNamespace,
    _reply_text,
    logging,
    pytest,
    rss,
)


@pytest.mark.asyncio
async def test_rss_add_usage_uses_normal_prefix_lookup(monkeypatch, make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="room@conf"), "type": "groupchat"}

    monkeypatch.setattr(rss, "config", {"prefix": "!"})

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

    await rss.rss_command(
        bot, "jid1", "nick1", ["add", "example.org/feed"], msg, False
    )
    assert bot.replies[-1][1] == "🔴 RSS add needs a room context or explicit room JID."


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
async def test_rss_add_expected_failures_log_without_traceback(
        monkeypatch, make_bot, caplog):
    bot = make_bot()

    monkeypatch.setattr(rss, "feedparser", type("Feedparser", (), {})())

    async def raise_exc(url):
        raise rss.aiohttp.ClientResponseError(
            request_info=None,
            history=(),
            status=404,
            message="Not Found",
        )

    monkeypatch.setattr(rss, "fetch_feed", raise_exc)
    monkeypatch.setattr(rss, "ensure_task", AsyncMock())

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

    monkeypatch.setattr(rss, "fetch_feed", AsyncMock(return_value=DummyFeed()))
    monkeypatch.setattr(rss, "ensure_task", AsyncMock())
    monkeypatch.setattr(
        rss,
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
    rss.user_has_room_plugin_grant.assert_awaited_once_with(
        bot, "alice@example.org", "rss", room
    )


@pytest.mark.asyncio
async def test_rss_plugin_grant_requires_target_room_affiliation(monkeypatch, make_bot):
    bot = make_bot()
    bot.get_user_role = AsyncMock(return_value=Role.USER)
    room = "room@conference.example.org"
    url = "https://example.org/feed.rss"
    monkeypatch.setattr(rss, "fetch_feed", AsyncMock())
    monkeypatch.setattr(
        rss,
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
    rss.fetch_feed.assert_not_awaited()
    assert "RSS plugin grant" in bot.replies[-1][1]


@pytest.mark.asyncio
async def test_rss_template_show_set_test_unset(make_bot):
    bot = make_bot()
    room = "room@conference.example.org"
    msg = {"from": SimpleNamespace(bare=room), "type": "groupchat"}

    await rss.rss_command(bot, "jid", "nick", ["template"], msg, True)
    assert "RSS template for room@conference.example.org (default)" in bot.replies[-1][1]
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
    monkeypatch.setattr(rss, "ensure_task", AsyncMock())

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
    assert "Usage:" in bot.replies[-1][1]

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
    assert "(default)" in bot.replies[-1][1]
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
async def test_limited_response_reader_and_save_last_id(monkeypatch):
    class Content:
        def __init__(self, chunks):
            self.chunks = list(chunks)

        async def iter_chunked(self, size):
            assert size == 8192
            for chunk in self.chunks:
                yield chunk

    class Response:
        def __init__(self, chunks):
            self.content = Content(chunks)

    assert await rss._read_limited_response(Response([b"ab", b"cd"])) == b"abcd"

    monkeypatch.setattr(rss, "RSS_MAX_READ_BYTES", 3)
    with pytest.raises(rss.FetchURLTooLarge, match="exceeds 3 bytes"):
        await rss._read_limited_response(Response([b"ab", b"cd"]))

    set_field = AsyncMock(return_value=True)
    monkeypatch.setattr(rss, "_set_feed_field", set_field)
    bot = object()
    store = object()
    assert await rss._save_last_id(bot, store, "https://feed.example/rss", "entry-1") is True
    set_field.assert_awaited_once_with(bot, store, "https://feed.example/rss", "last_id", "entry-1")
