"""Split module for plugins/rss.py: store."""

import asyncio
import logging


log = logging.getLogger(__name__)


async def _flush_user_store(bot):
    """
    Flush the user store when supported.

    The RSS plugin depends on last_id being durable before shutdown/restart.
    Some stores buffer writes, so set_global() alone is not always enough.
    """
    users = getattr(getattr(bot, "db", None), "users", None)
    flush_all = getattr(users, "flush_all", None)

    if callable(flush_all):
        await flush_all()


async def get_rss_store(bot):
    """Return the runtime store for RSS feed state."""
    return bot.db.users.plugin("rss")


async def _set_retry_state(bot, store, url, error_count, next_retry):
    return await _update_feed(
        bot,
        store,
        url,
        lambda feed: _apply_retry_state(feed, error_count, next_retry),
    )


def _apply_retry_state(feed, error_count, next_retry):
    changed = False
    if feed.get("error_count", 0) != error_count:
        feed["error_count"] = error_count
        changed = True
    if feed.get("next_retry", 0) != next_retry:
        feed["next_retry"] = next_retry
        changed = True
    return changed


async def _reset_retry_state(bot, store, url):
    return await _set_retry_state(bot, store, url, 0, 0)


def _retry_delay(_period, error_count):
    """Return the retry delay for a failed feed fetch."""
    failure_count = max(1, int(error_count or 1))
    delay = RSS_RETRY_INITIAL_DELAY * (
        RSS_RETRY_BACKOFF_MULTIPLIER ** (failure_count - 1)
    )
    return min(int(delay), MAX_BACKOFF_TIME)


async def _sleep_for_retry(_period, next_retry, now):
    if next_retry > now:
        await asyncio.sleep(next_retry - now)
        return True
    return False


def _format_retry_status(feed, now=None) -> str:
    """Return RSS list status lines for failed fetches and retry timing."""
    error_count = int(feed.get("error_count", 0) or 0)
    if error_count <= 0:
        return ""

    now = _now() if now is None else int(now)
    next_retry = int(feed.get("next_retry", 0) or 0)
    lines = [f"⚠️ Last {error_count} fetch(es) failed"]

    if next_retry > now:
        lines.append(f"Next retry in: {_format_duration(next_retry - now)}")
    elif next_retry:
        lines.append("Next retry: now")

    return "\n".join(lines) + "\n"


async def _reset_feed_retry(bot, msg, url, store):
    """Clear a feed's retry state and restart its checker immediately."""
    url = _normalize_url(url)
    feeds = await get_feeds(store)

    if url not in feeds:
        bot.reply(msg, "Feed not found.")
        return

    feed = feeds[url]
    _apply_retry_state(feed, 0, 0)
    await save_feeds(store, feeds)

    await _cancel_feed_task(bot, url)
    await ensure_task(
        bot,
        store,
        url,
        feed.get("period", DEFAULT_POLL_INTERVAL),
    )

    bot.reply(msg, f"🔁 Retry state reset and RSS check scheduled: {url}")


async def cleanup_room_state(bot, room_jid: str) -> dict[str, int]:
    """Remove a deleted room from all RSS subscriptions."""
    target = _normalize_room_jid(room_jid)
    store = await get_rss_store(bot)
    feeds = await get_feeds(store)
    summary = {"subscriptions": 0, "feeds": 0}
    changed = False
    removed_urls = []

    for url, feed in tuple(feeds.items()):
        if not isinstance(feed, dict):
            continue
        rooms = feed.get("rooms")
        if not isinstance(rooms, list):
            continue
        remaining = [room for room in rooms if _normalize_room_jid(room) != target]
        removed = len(rooms) - len(remaining)
        if removed <= 0:
            continue
        summary["subscriptions"] += removed
        changed = True
        if remaining:
            feed["rooms"] = remaining
        else:
            feeds.pop(url, None)
            removed_urls.append(url)
            summary["feeds"] += 1

    if changed:
        await save_feeds(store, feeds)
        for url in removed_urls:
            await _cancel_feed_task(bot, url)

    return summary


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int]:
    """Return small RSS runtime counters for diagnostics."""
    store = await get_rss_store(bot)
    feeds = await get_feeds(store)
    room_target = _normalize_room_jid(room_jid) if room_jid else None
    retrying = sum(
        1 for feed in feeds.values()
        if isinstance(feed, dict) and int(feed.get("next_retry") or 0) > _now()
    )
    if room_target:
        room_feeds = _filter_feeds_for_room(feeds, room_target)
        return {
            "feeds": len(room_feeds),
            "active_tasks": sum(
                1
                for url in room_feeds
                if url in CHECK_TASKS and not CHECK_TASKS[url].done()
            ),
            "retry_backoff": sum(
                1 for feed in room_feeds.values()
                if isinstance(feed, dict)
                and int(feed.get("next_retry") or 0) > _now()
            ),
        }
    return {
        "feeds": len(feeds),
        "active_tasks": sum(1 for task in CHECK_TASKS.values() if not task.done()),
        "retry_backoff": retrying,
    }
