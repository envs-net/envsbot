"""RSS polling tasks and feed-processing workflow."""

from __future__ import annotations

import asyncio

from utils.task_supervisor import create_plugin_task

from .config import DEFAULT_POLL_INTERVAL, RSS_MAX_ENTRIES_PER_POLL
from .fetch import _entry_is_new, _get_latest_entry_id, feedparser, fetch_feed
from .formatting import _post_new_entries
from .store import (
    _apply_retry_state,
    _feed_is_globally_paused,
    _load_feed,
    _now,
    _record_feed_check,
    _retry_delay,
    _set_feed_field,
    _sleep_for_retry,
    _update_feed_link,
    _update_feed,
    get_feeds,
    log,
)

CHECK_TASKS = {}


async def _initialize_last_id(bot, store, url, latest_id):
    if not latest_id:
        return False
    return await _set_feed_field(bot, store, url, "last_id", latest_id)
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
async def _handle_fetch_error(bot, store, url, period, now, error_count, exc):
    log.warning("Failed to fetch RSS feed %s: %s", url, exc)

    error_count += 1
    retry_delay = _retry_delay(period, error_count)
    next_retry = now + retry_delay

    def mutator(feed):
        changed = _apply_retry_state(feed, error_count, next_retry)
        changed = _record_feed_check(feed, now=now, success=False, error=str(exc)) or changed
        return changed

    await _update_feed(bot, store, url, mutator)
    log.debug(
        "Feed %s backoff set to %s errors, retry at %s",
        url,
        error_count,
        next_retry,
    )
    await asyncio.sleep(retry_delay)
async def _handle_empty_feed(url, period, parsed):
    if not parsed.entries:
        log.debug("Feed %s has no entries", url)
        await asyncio.sleep(period)
        return True
    return False
async def _handle_feed_recovery(bot, store, url, error_count):
    now = _now()

    def mutator(feed):
        changed = _record_feed_check(feed, now=now, success=True)
        if error_count > 0:
            changed = _apply_retry_state(feed, 0, 0) or changed
        return changed

    if error_count > 0:
        log.debug("Feed %s recovered, resetting error count", url)
    await _update_feed(bot, store, url, mutator)
async def _maybe_update_feed_link(bot, store, url, parsed, feed_link):
    if "feed" in parsed and "link" in parsed.feed:
        feed_link = parsed.feed["link"]
        await _update_feed_link(bot, store, url, feed_link)
    return feed_link
async def _cancel_feed_task(bot, url: str) -> bool:
    """Cancel the background check task for a feed URL when it exists.

    RSS retry/delete operations restart individual feed workers.  When tasks are
    supervised, cancel through the supervisor as well so deliberate restarts do
    not leave stale ``cancelled`` entries in ``,tasks all`` output.
    """
    task = CHECK_TASKS.pop(url, None)
    if task is None:
        return False

    supervisor = getattr(bot, "tasks", None)
    cancel_task = getattr(supervisor, "cancel_task", None)
    if callable(cancel_task):
        await cancel_task(task)
        return True

    cancel = getattr(task, "cancel", None)
    if callable(cancel):
        cancel()

    if hasattr(task, "__await__"):
        try:
            await task
        except asyncio.CancelledError:
            # Expected when replacing or deleting an RSS feed worker.
            pass

    return True
async def _initialize_missing_last_id(bot, store, url, last_id, parsed):
    if not last_id:
        latest_id = _get_latest_entry_id(parsed)
        if latest_id:
            await _initialize_last_id(bot, store, url, latest_id)
            log.info(
                "[RSS] Initialized last_id for %s without posting old entries",
                url,
            )
        return True
    return False
def _collect_new_entries(parsed, last_id, max_entries=None):
    """Return newest unseen entries, capped to avoid feed burst floods."""
    limit = RSS_MAX_ENTRIES_PER_POLL if max_entries is None else max_entries
    limit = max(1, int(limit or RSS_MAX_ENTRIES_PER_POLL))
    new_entries = []
    for entry in parsed.entries:
        is_new, entry_id = _entry_is_new(last_id, entry)
        if not entry_id:
            continue
        if not is_new:
            break
        new_entries.append((entry, entry_id))
        if len(new_entries) >= limit:
            break
    return new_entries
