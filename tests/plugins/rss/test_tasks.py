from .helpers import (
    AsyncMock,
    Entry,
    Role,
    SimpleNamespace,
    TaskSupervisor,
    _RssDoneTask,
    _RssPendingTask,
    asyncio,
    core_plugins,
    pytest,
    rss,
)
from plugins.rss import store as rss_store
from plugins.rss import tasks as rss_tasks
from plugins.rss import commands as rss_commands
from plugins.rss import formatting as rss_formatting
from plugins.rss import lifecycle as rss_lifecycle


@pytest.mark.asyncio
async def test_rss_check_loop_limits_entries_per_poll_and_skips_backlog(
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
    monkeypatch.setattr(rss_tasks, "RSS_MAX_ENTRIES_PER_POLL", 2)

    entries = [
        Entry(
            title="ET4",
            link="http://f.com/a4",
            description="ED4",
            id="http://f.com/a4",
        ),
        Entry(
            title="ET3",
            link="http://f.com/a3",
            description="ED3",
            id="http://f.com/a3",
        ),
        Entry(
            title="ET2",
            link="http://f.com/a2",
            description="ED2",
            id="http://f.com/a2",
        ),
        Entry(
            title="ET1",
            link="http://f.com/a1",
            description="ED1",
            id="http://f.com/a1",
        ),
    ]

    class DummyFeed:
        def __init__(self):
            self.feed = {"title": "Feed", "link": url, "href": url, "id": url}
            self.entries = entries

        def __contains__(self, k):
            return k == "feed"

    async def fake_fetch_feed(_):
        return DummyFeed()

    monkeypatch.setattr(rss_tasks, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss_tasks, "_now", lambda: 1000)

    async def fake_sleep(_secs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await rss.rss_check_loop(bot, store, url, 1)

    assert len(bot.sent_messages) == 2
    assert "ET3" in bot.sent_messages[0]["mbody"]
    assert "ET4" in bot.sent_messages[1]["mbody"]
    assert all("ET2" not in message["mbody"] for message in bot.sent_messages)
    assert all(message["mto"] == room for message in bot.sent_messages)
    assert all(message["mtype"] == "groupchat" for message in bot.sent_messages)
    assert store[rss.RSS_KEY][url]["last_id"] == "http://f.com/a4"


@pytest.mark.asyncio
async def test_on_load_unload_calls(monkeypatch, make_bot):
    bot = make_bot()

    monkeypatch.setattr(rss_tasks, "feedparser", type("Feedparser", (), {})())

    restart = AsyncMock()
    monkeypatch.setattr(rss_tasks, "restart_all_tasks", restart)

    await rss.on_load(bot)
    restart.assert_awaited_once()

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

    monkeypatch.setattr(rss_tasks, "create_plugin_task", fake_create_plugin_task)
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


@pytest.mark.asyncio
async def test_restart_all_tasks_staggers_initial_fetches_per_host(
        monkeypatch, make_bot):
    bot = make_bot()
    store = bot.plugin_store
    await rss.save_feeds(store, {
        "https://git.example.org/one.rss": {"period": 100},
        "https://other.example.org/feed.rss": {"period": 200},
        "https://git.example.org/two.rss": {"period": 300},
        "https://git.example.org/three.rss": {"period": 400},
    })
    scheduled = []

    async def fake_ensure_task(
            bot_arg, store_arg, url_arg, period_arg, *, initial_delay=0.0):
        scheduled.append((url_arg, period_arg, initial_delay))

    monkeypatch.setattr(rss_tasks, "ensure_task", fake_ensure_task)
    monkeypatch.setattr(rss_tasks, "RSS_STARTUP_STAGGER_SECONDS", 2.0)

    await rss_tasks.restart_all_tasks(bot)

    assert scheduled == [
        ("https://git.example.org/one.rss", 100, 0.0),
        ("https://other.example.org/feed.rss", 200, 0.0),
        ("https://git.example.org/two.rss", 300, 2.0),
        ("https://git.example.org/three.rss", 400, 4.0),
    ]


@pytest.mark.asyncio
async def test_reset_feed_retry_prunes_cancelled_supervised_task(monkeypatch, make_bot):
    bot = make_bot()
    bot.tasks = TaskSupervisor()
    store = bot.plugin_store
    url = "https://example.org/feed.xml"
    await rss.save_feeds(
        store,
        {
            url: {
                "period": 30,
                "rooms": ["room@conf"],
                "error_count": 3,
                "next_retry": 999,
            }
        },
    )

    async def sleeper():
        while True:
            await asyncio.sleep(60)

    old_task = bot.tasks.create("rss", sleeper(), name=f"rss-check-{url}")
    rss.CHECK_TASKS[url] = old_task

    scheduled = []

    async def fake_ensure_task(bot_arg, store_arg, url_arg, period_arg):
        scheduled.append((bot_arg, store_arg, url_arg, period_arg))

    monkeypatch.setattr(rss_commands, "ensure_task", fake_ensure_task)

    await rss._reset_feed_retry(bot, {}, url, store)

    assert scheduled == [(bot, store, url, 30)]
    assert url not in rss.CHECK_TASKS
    assert bot.tasks.snapshot(include_done=True) == []
    assert store[rss.RSS_KEY][url]["error_count"] == 0
    assert store[rss.RSS_KEY][url]["next_retry"] == 0


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


def test_retry_delay_uses_exponential_failure_backoff(monkeypatch):
    monkeypatch.setattr(rss_store, "RSS_RETRY_INITIAL_DELAY", 300)
    monkeypatch.setattr(rss_store, "RSS_RETRY_BACKOFF_MULTIPLIER", 2.0)
    monkeypatch.setattr(rss_store, "MAX_BACKOFF_TIME", 3600)

    assert rss._retry_delay(1200, 1) == 300
    assert rss._retry_delay(1200, 2) == 600
    assert rss._retry_delay(1200, 3) == 1200
    assert rss._retry_delay(1200, 99) == 3600


@pytest.mark.asyncio
async def test_retry_wait_is_not_clipped_by_feed_period(monkeypatch):
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    assert await rss._sleep_for_retry(1, 1300, 1000) is True
    assert sleep_calls == [300]


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

    monkeypatch.setattr(rss_tasks, "_now", lambda: 1000)
    monkeypatch.setattr(rss_commands, "_now", lambda: 1000)
    monkeypatch.setattr(rss_formatting, "_now", lambda: 1000)

    await rss.rss_command(bot, "jid", "nick", ["list"], msg, True)

    text = "\n".join(bot.replies[-1][1])
    assert "⚠️ Last 1 fetch(es) failed" in text
    assert "Next retry in: 2m" in text


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
    monkeypatch.setattr(rss_commands, "ensure_task", ensure)

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
async def test_rss_reset_all_retry_states_restarts_all_tasks(monkeypatch, make_bot):
    bot = make_bot()
    feeds = {
        "https://example.org/a.xml": {
            "title": "A",
            "period": 42,
            "rooms": ["room@conference.example.org"],
            "error_count": 2,
            "next_retry": 1234,
        },
        "https://example.org/b.xml": {
            "title": "B",
            "period": 84,
            "rooms": ["room@conference.example.org"],
            "error_count": 3,
            "next_retry": 5678,
        },
    }
    bot.plugin_store[rss.RSS_KEY] = feeds
    msg = {"from": SimpleNamespace(bare="admin@example.org"), "type": "chat"}

    class RunningTask:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    old_tasks = {url: RunningTask() for url in feeds}
    rss.CHECK_TASKS.update(old_tasks)
    ensure = AsyncMock()
    monkeypatch.setattr(rss_commands, "ensure_task", ensure)

    await rss.rss_command(bot, "jid", "nick", ["retry", "all"], msg, False)

    for url, feed in bot.plugin_store[rss.RSS_KEY].items():
        assert feed["error_count"] == 0
        assert feed["next_retry"] == 0
        assert old_tasks[url].cancelled is True

    ensure.assert_any_await(bot, bot.plugin_store, "https://example.org/a.xml", 42)
    ensure.assert_any_await(bot, bot.plugin_store, "https://example.org/b.xml", 84)
    assert ensure.await_count == 2
    assert bot.replies[-1][1] == (
        "🔁 Retry state reset and RSS checks scheduled for all feeds (2)."
    )


@pytest.mark.asyncio
async def test_rss_reset_all_retry_states_requires_global_manager(make_bot):
    bot = make_bot()
    bot.get_user_role = AsyncMock(return_value=Role.USER)
    bot.plugin_store[rss.RSS_KEY] = {
        "https://example.org/a.xml": {
            "title": "A",
            "period": 42,
            "rooms": ["room@conference.example.org"],
            "error_count": 2,
            "next_retry": 1234,
        }
    }
    msg = {"from": SimpleNamespace(bare="user@example.org"), "type": "chat"}

    await rss.rss_command(bot, "jid", "nick", ["reset", "all"], msg, False)

    feed = bot.plugin_store[rss.RSS_KEY]["https://example.org/a.xml"]
    assert feed["error_count"] == 2
    assert feed["next_retry"] == 1234
    assert bot.replies[-1][1] == "🔴 Only global moderators can reset all RSS retries."


@pytest.mark.asyncio
async def test_rss_reset_retry_state_usage_and_missing_feed(make_bot):
    bot = make_bot()
    msg = {"from": SimpleNamespace(bare="admin@example.org"), "type": "chat"}

    await rss.rss_command(bot, "jid", "nick", ["reset"], msg, False)
    assert bot.replies[-1][1] == "Usage: ,rss reset <feedurl>|all [room_jid]"

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

    async def fake_fetch_feed(_):
        return EmptyFeed()

    async def fake_sleep(secs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(rss_tasks, "fetch_feed", fake_fetch_feed)
    monkeypatch.setattr(rss_tasks, "_now", lambda: 1001)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await rss.rss_check_loop(bot, store, url, 1)

    feed = store[rss.RSS_KEY][url]
    assert feed["error_count"] == 0
    assert feed["next_retry"] == 0


@pytest.mark.asyncio
async def test_cleanup_room_state_removes_room_subscriptions(monkeypatch, make_bot):
    bot = make_bot()
    keep_url = "https://example.org/keep.xml"
    drop_url = "https://example.org/drop.xml"
    direct_url = "https://example.org/direct.xml"
    other_url = "https://example.org/other.xml"
    ignored_url = "https://example.org/ignored.xml"
    bot.plugin_store[rss.RSS_KEY] = {
        keep_url: {"rooms": ["Room@Conference.Example.Org", "other@conf"]},
        drop_url: {"rooms": ["room@conference.example.org"]},
        direct_url: {
            "rooms": ["room@conference.example.org"],
            "users": {"alice@example.org": {"role": "trusted"}},
        },
        other_url: {"rooms": ["other@conf"]},
        ignored_url: {"title": "missing rooms"},
        "broken": "not a feed",
    }
    bot.plugin_store[rss.RSS_TEMPLATES_KEY] = {
        "room@conference.example.org": "$title",
        "other@conf": "$feed_title",
    }
    bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY] = {
        "room@conference.example.org": {
            keep_url: "KEEP $title",
            drop_url: "DROP $title",
        },
        "other@conf": {other_url: "OTHER $title"},
    }
    cancelled = []

    async def fake_cancel(bot_arg, url):
        assert bot_arg is bot
        cancelled.append(url)

    monkeypatch.setattr(rss_lifecycle, "_cancel_feed_task", fake_cancel)

    summary = await rss.cleanup_room_state(bot, "room@conference.example.org")

    assert summary == {"subscriptions": 3, "feeds": 1, "templates": 3}
    assert bot.plugin_store[rss.RSS_KEY][keep_url]["rooms"] == ["other@conf"]
    assert drop_url not in bot.plugin_store[rss.RSS_KEY]
    assert bot.plugin_store[rss.RSS_KEY][direct_url] == {
        "rooms": [],
        "users": {"alice@example.org": {"role": "trusted"}},
    }
    assert bot.plugin_store[rss.RSS_KEY][other_url]["rooms"] == ["other@conf"]
    assert cancelled == [drop_url]
    assert bot.plugin_store[rss.RSS_TEMPLATES_KEY] == {"other@conf": "$feed_title"}
    assert bot.plugin_store[rss.RSS_FEED_TEMPLATES_KEY] == {
        "other@conf": {other_url: "OTHER $title"}
    }


@pytest.mark.asyncio
async def test_rss_runtime_state_global_and_room(monkeypatch, make_bot):
    now = 1_000
    monkeypatch.setattr(rss_tasks, "_now", lambda: now)
    monkeypatch.setattr(rss_lifecycle, "_now", lambda: now)
    bot = make_bot()
    bot.plugin_store[rss.RSS_KEY] = {
        "https://one.example/feed": {"rooms": ["Room@Conf"], "next_retry": now + 60},
        "https://two.example/feed": {"rooms": ["room@conf", "other@conf"], "next_retry": 0},
        "https://bad.example/feed": "invalid",
    }
    rss.CHECK_TASKS["https://one.example/feed"] = _RssPendingTask()
    rss.CHECK_TASKS["https://two.example/feed"] = _RssDoneTask()

    assert await rss.get_runtime_state(bot, "room@conf") == {
        "feeds": 2,
        "active_tasks": 1,
        "retry_backoff": 1,
    }
    assert await rss.get_runtime_state(bot) == {
        "feeds": 3,
        "active_tasks": 1,
        "retry_backoff": 1,
    }


@pytest.mark.asyncio
async def test_rss_restart_tasks_restarts_plugin_lifecycle(monkeypatch, make_bot):
    bot = make_bot()
    calls = []

    async def fake_on_unload(bot_arg):
        assert bot_arg is bot
        calls.append("unload")

    async def fake_on_load(bot_arg):
        assert bot_arg is bot
        calls.append("load")

    monkeypatch.setattr(rss_tasks, "on_unload", fake_on_unload)
    monkeypatch.setattr(rss_tasks, "on_load", fake_on_load)

    await rss.restart_tasks(bot)

    assert calls == ["unload", "load"]


@pytest.mark.asyncio
async def test_post_error_records_backoff_without_killing_worker(
    monkeypatch, make_bot,
):
    bot = make_bot()
    store = bot.plugin_store
    url = "https://example.org/direct.xml"
    await rss.save_feeds(
        store,
        {
            url: {
                "rooms": [],
                "users": {"alice@example.org": {"role": "trusted"}},
                "error_count": 0,
                "next_retry": 0,
            }
        },
    )
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(rss_store, "RSS_RETRY_INITIAL_DELAY", 30)

    await rss_tasks._handle_post_error(
        bot,
        store,
        url,
        1200,
        1000,
        RuntimeError("direct render failed"),
    )

    feed = store[rss.RSS_KEY][url]
    assert feed["error_count"] == 1
    assert feed["next_retry"] == 1030
    assert feed["last_error"] == "post: direct render failed"
    assert sleeps == [30]
