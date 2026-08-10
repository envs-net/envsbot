"""RSS persistence and stored feed-state helpers."""

from __future__ import annotations

import logging
import time

from .config import (
    MAX_BACKOFF_TIME,
    RSS_DEFAULT_TEMPLATE_KEY,
    RSS_FEED_TEMPLATES_KEY,
    RSS_KEY,
    RSS_RETRY_BACKOFF_MULTIPLIER,
    RSS_RETRY_INITIAL_DELAY,
    RSS_TEMPLATES_KEY,
)

log = logging.getLogger(__name__)

def _now() -> int:
    return int(time.time())

def _normalize_room_jid(room: str) -> str:
    return str(room or "").strip().lower()
def _normalize_template_room_jid(room: str) -> str:
    """Normalize a room JID used for RSS template storage."""
    return str(room or "").strip().lower()
def _normalize_template_feed_url(url: str) -> str:
    """Normalize a feed URL used for RSS template storage."""
    return str(url or "").strip()
async def get_rss_store(bot):
    """Return the runtime store for RSS feed state."""
    return bot.db.users.plugin("rss")
async def get_default_template(store) -> str | None:
    """Return the custom global RSS template, if one is configured."""
    template = await store.get_global(RSS_DEFAULT_TEMPLATE_KEY, default=None)
    if not isinstance(template, str) or not template.strip():
        return None
    return template
async def set_default_template(store, template: str) -> None:
    """Persist the custom global RSS template used by all rooms."""
    await store.set_global(RSS_DEFAULT_TEMPLATE_KEY, template)
async def unset_default_template(store) -> bool:
    """Remove the custom global RSS template."""
    if await get_default_template(store) is None:
        return False
    await store.set_global(RSS_DEFAULT_TEMPLATE_KEY, None)
    return True
async def get_room_templates(store) -> dict[str, str]:
    """Return custom RSS templates keyed by normalized room JID."""
    templates = await store.get_global(RSS_TEMPLATES_KEY, default={})
    if not isinstance(templates, dict):
        return {}
    return {
        _normalize_template_room_jid(room): str(template)
        for room, template in templates.items()
        if _normalize_template_room_jid(room) and isinstance(template, str)
    }
async def save_room_templates(store, templates: dict[str, str]) -> None:
    """Persist custom RSS room templates."""
    normalized = {
        _normalize_template_room_jid(room): str(template)
        for room, template in templates.items()
        if _normalize_template_room_jid(room) and isinstance(template, str)
    }
    await store.set_global(RSS_TEMPLATES_KEY, normalized)
async def get_feed_templates(store) -> dict[str, dict[str, str]]:
    """Return custom RSS templates keyed by room JID and feed URL."""
    templates = await store.get_global(RSS_FEED_TEMPLATES_KEY, default={})
    if not isinstance(templates, dict):
        return {}

    normalized: dict[str, dict[str, str]] = {}
    for room, feed_templates in templates.items():
        room_key = _normalize_template_room_jid(room)
        if not room_key or not isinstance(feed_templates, dict):
            continue
        feeds = {
            _normalize_template_feed_url(url): str(template)
            for url, template in feed_templates.items()
            if _normalize_template_feed_url(url) and isinstance(template, str)
        }
        if feeds:
            normalized[room_key] = feeds
    return normalized
async def save_feed_templates(
    store, templates: dict[str, dict[str, str]]
) -> None:
    """Persist custom RSS feed templates."""
    normalized: dict[str, dict[str, str]] = {}
    for room, feed_templates in templates.items():
        room_key = _normalize_template_room_jid(room)
        if not room_key or not isinstance(feed_templates, dict):
            continue
        feeds = {
            _normalize_template_feed_url(url): str(template)
            for url, template in feed_templates.items()
            if _normalize_template_feed_url(url) and isinstance(template, str)
        }
        if feeds:
            normalized[room_key] = feeds
    await store.set_global(RSS_FEED_TEMPLATES_KEY, normalized)
async def get_feed_template(store, room: str, url: str) -> str | None:
    """Return a custom RSS template for one room/feed pair."""
    templates = await get_feed_templates(store)
    room_templates = templates.get(_normalize_template_room_jid(room), {})
    return room_templates.get(_normalize_template_feed_url(url))
async def set_feed_template(store, room: str, url: str, template: str) -> None:
    """Set a custom RSS template for one room/feed pair."""
    templates = await get_feed_templates(store)
    room_key = _normalize_template_room_jid(room)
    url_key = _normalize_template_feed_url(url)
    if not room_key or not url_key:
        return
    templates.setdefault(room_key, {})[url_key] = template
    await save_feed_templates(store, templates)
async def unset_feed_template(store, room: str, url: str) -> bool:
    """Remove a custom RSS template for one room/feed pair."""
    templates = await get_feed_templates(store)
    room_key = _normalize_template_room_jid(room)
    room_templates = templates.get(room_key)
    if not isinstance(room_templates, dict):
        return False
    removed = room_templates.pop(_normalize_template_feed_url(url), None) is not None
    if not room_templates:
        templates.pop(room_key, None)
    if removed:
        await save_feed_templates(store, templates)
    return removed
async def unset_feed_templates_for_feed(store, url: str) -> int:
    """Remove custom RSS templates for a feed URL across all rooms."""
    templates = await get_feed_templates(store)
    url_key = _normalize_template_feed_url(url)
    removed = 0
    for room in list(templates):
        room_templates = templates.get(room, {})
        if room_templates.pop(url_key, None) is not None:
            removed += 1
        if not room_templates:
            templates.pop(room, None)
    if removed:
        await save_feed_templates(store, templates)
    return removed
async def unset_feed_templates_for_room(store, room: str) -> int:
    """Remove all feed-specific RSS templates for a room."""
    templates = await get_feed_templates(store)
    room_key = _normalize_template_room_jid(room)
    removed = len(templates.get(room_key, {}))
    if templates.pop(room_key, None) is not None:
        await save_feed_templates(store, templates)
    return removed
async def get_effective_template(store, room: str, url: str) -> str | None:
    """Return the feed, room, or global RSS template override."""
    feed_template = await get_feed_template(store, room, url)
    if feed_template:
        return feed_template
    room_template = await get_room_template(store, room)
    if room_template:
        return room_template
    return await get_default_template(store)
async def get_room_template(store, room: str) -> str | None:
    """Return the custom RSS template for a room, if one is configured."""
    templates = await get_room_templates(store)
    return templates.get(_normalize_template_room_jid(room))
async def set_room_template(store, room: str, template: str) -> None:
    """Set a custom RSS template for one room."""
    templates = await get_room_templates(store)
    templates[_normalize_template_room_jid(room)] = template
    await save_room_templates(store, templates)
async def unset_room_template(store, room: str) -> bool:
    """Remove a custom RSS template for one room."""
    templates = await get_room_templates(store)
    removed = templates.pop(_normalize_template_room_jid(room), None) is not None
    if removed:
        await save_room_templates(store, templates)
    return removed
def _apply_retry_state(feed, error_count, next_retry):
    changed = False
    if feed.get("error_count", 0) != error_count:
        feed["error_count"] = error_count
        changed = True
    if feed.get("next_retry", 0) != next_retry:
        feed["next_retry"] = next_retry
        changed = True
    return changed
def _normalize_subscription_room(room: str) -> str:
    return _normalize_template_room_jid(room)
def _feed_paused_rooms(feed: dict) -> set[str]:
    rooms = feed.get("paused_rooms")
    if not isinstance(rooms, list):
        return set()
    return {
        _normalize_subscription_room(room)
        for room in rooms
        if _normalize_subscription_room(room)
    }
def _feed_active_rooms(feed: dict) -> list[str]:
    """Return subscribed rooms that are not paused for this feed."""
    rooms = feed.get("rooms")
    if not isinstance(rooms, list):
        return []
    paused = _feed_paused_rooms(feed)
    active = []
    seen = set()
    for room in rooms:
        key = _normalize_subscription_room(room)
        if not key or key in seen or key in paused:
            continue
        active.append(str(room))
        seen.add(key)
    return active
def _feed_is_globally_paused(feed: dict) -> bool:
    return bool(feed.get("paused", False))
def _format_rss_timestamp(ts) -> str:
    try:
        value = int(ts or 0)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return "never"
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))
def _feed_status_label(feed: dict, now: int | None = None) -> str:
    if _feed_is_globally_paused(feed):
        return "paused"
    users = feed.get("users") if isinstance(feed, dict) else None
    if not _feed_active_rooms(feed) and not (isinstance(users, dict) and users):
        return "paused for all destinations"
    try:
        next_retry = int(feed.get("next_retry", 0) or 0)
    except (TypeError, ValueError):
        next_retry = 0
    now = _now() if now is None else int(now)
    if next_retry > now:
        return "backoff"
    if int(feed.get("error_count", 0) or 0) > 0:
        return "degraded"
    return "ok"
def _record_feed_check(feed: dict, *, now: int, success: bool, error: str | None = None) -> bool:
    changed = False
    for key, value in {"last_checked": now}.items():
        if feed.get(key) != value:
            feed[key] = value
            changed = True
    if success:
        updates = {
            "last_success": now,
            "last_error": "",
            "last_error_at": 0,
        }
    else:
        updates = {
            "last_error": str(error or "unknown")[:240],
            "last_error_at": now,
        }
    for key, value in updates.items():
        if feed.get(key) != value:
            feed[key] = value
            changed = True
    return changed
def _record_feed_post(feed: dict, *, now: int, posted: int = 1) -> bool:
    changed = False
    try:
        current = int(feed.get("posted_count", 0) or 0)
    except (TypeError, ValueError):
        current = 0
    updates = {
        "last_posted": now,
        "posted_count": current + max(0, int(posted or 0)),
    }
    for key, value in updates.items():
        if feed.get(key) != value:
            feed[key] = value
            changed = True
    return changed
def _retry_delay(_period, error_count):
    """Return the retry delay for a failed feed fetch."""
    failure_count = max(1, int(error_count or 1))
    delay = RSS_RETRY_INITIAL_DELAY * (
        RSS_RETRY_BACKOFF_MULTIPLIER ** (failure_count - 1)
    )
    return min(int(delay), MAX_BACKOFF_TIME)
async def get_feeds(store):
    feeds = await store.get_global(RSS_KEY, default={})
    return feeds if isinstance(feeds, dict) else {}
async def save_feeds(store, feeds):
    await store.set_global(RSS_KEY, feeds)
async def _load_feed(store, url):
    feeds = await get_feeds(store)
    return feeds, feeds.get(url)
async def _update_feed(store, url, mutator):
    """
    Load feeds, mutate the feed at `url` in-place if it exists, then persist.
    `mutator(feed)` should return True if it made a meaningful change.
    """
    feeds = await get_feeds(store)
    feed = feeds.get(url)
    if feed is None:
        return False

    changed = mutator(feed)
    if changed:
        await save_feeds(store, feeds)

    return changed
async def _set_feed_field(store, url, field, value):
    def mutator(feed):
        if feed.get(field) == value:
            return False
        feed[field] = value
        return True

    return await _update_feed(store, url, mutator)
async def _update_feed_link(store, url, feed_link):
    return await _set_feed_field(store, url, "link", feed_link)
