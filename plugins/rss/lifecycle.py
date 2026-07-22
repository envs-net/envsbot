"""RSS room cleanup and diagnostic hooks."""

from __future__ import annotations

from .formatting import _filter_feeds_for_room
from .store import (
    _normalize_room_jid,
    _normalize_template_room_jid,
    _now,
    get_rss_store,
    get_feeds,
    get_room_templates,
    save_feeds,
    save_room_templates,
    unset_feed_templates_for_room,
)
from .tasks import CHECK_TASKS, _cancel_feed_task
async def cleanup_room_state(bot, room_jid: str) -> dict[str, int]:
    """Remove a deleted room from all RSS subscriptions."""
    target = _normalize_template_room_jid(room_jid)
    store = await get_rss_store(bot)
    feeds = await get_feeds(store)
    summary = {"subscriptions": 0, "feeds": 0, "templates": 0}
    changed = False
    removed_urls = []

    for url, feed in tuple(feeds.items()):
        if not isinstance(feed, dict):
            continue
        rooms = feed.get("rooms")
        if not isinstance(rooms, list):
            continue
        remaining = [
            room for room in rooms
            if _normalize_template_room_jid(room) != target
        ]
        removed = len(rooms) - len(remaining)
        if removed <= 0:
            continue
        summary["subscriptions"] += removed
        changed = True
        if remaining:
            feed["rooms"] = remaining
        elif isinstance(feed.get("users"), dict) and feed.get("users"):
            # The feed is still required by direct subscribers.  Removing a
            # room must not silently delete their subscriptions or stop the
            # polling task.
            feed["rooms"] = []
        else:
            feeds.pop(url, None)
            removed_urls.append(url)
            summary["feeds"] += 1

    if changed:
        await save_feeds(store, feeds)
        for url in removed_urls:
            await _cancel_feed_task(bot, url)

    templates = await get_room_templates(store)
    if templates.pop(target, None) is not None:
        summary["templates"] += 1
        await save_room_templates(store, templates)

    summary["templates"] += await unset_feed_templates_for_room(store, target)

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
async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return RSS feed health diagnostics."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    lines = [
        f"✅ RSS{scope}: feeds={state.get('feeds', 0)}, active_tasks={state.get('active_tasks', 0)}, retry_backoff={state.get('retry_backoff', 0)}"
    ]
    if int(state.get('retry_backoff', 0) or 0) > 0:
        lines.append("🟡️ RSS: one or more feeds are currently in retry/backoff")
    return lines
