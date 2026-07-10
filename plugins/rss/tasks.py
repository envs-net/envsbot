"""Split module for plugins/rss.py: tasks."""

import asyncio
from utils.task_supervisor import create_plugin_task
from .store import _feed_is_globally_paused


CHECK_TASKS = {}


async def rss_check_loop(bot, store, url, period):
    """Periodically check a feed for updates and post new items."""
    while True:
        _, feed = await _load_feed(store, url)

        if feed is None:
            break

        if _feed_is_globally_paused(feed):
            await asyncio.sleep(period)
            continue

        feed_title = feed["title"]
        feed_link = feed.get("link", url)
        last_id = feed.get("last_id")
        rooms = feed.get("rooms", [])
        error_count = feed.get("error_count", 0)
        next_retry = feed.get("next_retry", 0)

        now = _now()

        if await _sleep_for_retry(period, next_retry, now):
            continue

        try:
            parsed = await fetch_feed(url)
        except Exception as e:
            await _handle_fetch_error(
                bot, store, url, period, now, error_count, e
            )
            continue

        await _handle_feed_recovery(bot, store, url, error_count)

        if await _handle_empty_feed(url, period, parsed):
            continue

        feed_link = await _maybe_update_feed_link(
            bot, store, url, parsed, feed_link
        )

        if await _initialize_missing_last_id(bot, store, url, last_id, parsed):
            await asyncio.sleep(period)
            continue

        new_entries = _collect_new_entries(parsed, last_id)
        await _post_new_entries(
            bot, store, url, feed_title, feed_link, rooms, new_entries, feed=feed
        )

        await asyncio.sleep(period)


async def ensure_task(bot, store, url, period):
    """Ensure a check task is running for the given feed."""
    if url in CHECK_TASKS and not CHECK_TASKS[url].done():
        return

    CHECK_TASKS[url] = create_plugin_task(bot, 
        "rss",
        rss_check_loop(bot, store, url, period),
        name=f"rss-check-{url}",
    )


async def restart_all_tasks(bot):
    store = bot.db.users.plugin("rss")
    feeds = await get_feeds(store)

    for url, feed in feeds.items():
        period = feed.get("period", DEFAULT_POLL_INTERVAL)
        await ensure_task(bot, store, url, period)


async def on_load(bot):
    if feedparser is None:
        log.error(
            "[RSS] feedparser module not installed. RSS plugin will not work."
        )
        return

    await restart_all_tasks(bot)


async def restart_tasks(bot):
    """Restart all RSS feed checker tasks for diagnostics."""
    await on_unload(bot)
    await on_load(bot)


async def on_unload(bot):
    """
    Clean up all RSS tasks on unload.

    Prevents task orphaning and memory leaks.
    """
    log.info("[RSS] Cleaning up RSS feed tasks...")

    # Cancel all active tasks
    for url in list(CHECK_TASKS):
        try:
            await _cancel_feed_task(bot, url)
            log.debug("[RSS] Task for %s cancelled", url)
        except Exception as e:
            log.exception("[RSS] Error cancelling task for %s: %s", url, e)

    log.info("[RSS] ✅ All RSS tasks cleaned up")


try:
    import feedparser
except ImportError:
    feedparser = None
