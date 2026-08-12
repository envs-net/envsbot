"""RSS subscription mutation helpers."""

from __future__ import annotations

from utils.command import Role
from utils.config import config

from .command_support import (
    _direct_subscriptions,
    _rss_normalize_room_list,
    burst_recent_entries,
)
from .config import DEFAULT_POLL_INTERVAL, RSS_TRUSTED_MAX_FEEDS
from .fetch import (
    _format_feed_fetch_error,
    _get_latest_entry_id,
    _log_feed_fetch_error,
    _normalize_url,
    fetch_feed,
)
from .formatting import _normalize_direct_user_jid
from .store import (
    _apply_retry_state,
    _normalize_room_jid,
    _normalize_subscription_room,
    _now,
    get_feeds,
    log,
    save_feeds,
    unset_feed_template,
    unset_feed_templates_for_feed,
    unset_feed_templates_for_room,
)
from .tasks import _cancel_feed_task, ensure_task


async def _add_direct_feed(bot, msg, url, store, owner: str, role: Role):
    url = _normalize_url(url)
    feeds = await get_feeds(store)
    if url not in feeds:
        try:
            parsed = await fetch_feed(url)
            feeds[url] = {
                "title": parsed.feed.get("title", url),
                "link": parsed.feed.get("link", url),
                "period": config.get("rss_global_query_interval", DEFAULT_POLL_INTERVAL),
                "rooms": [],
                "users": {},
                # Establish the subscription cursor from the feed snapshot used
                # during add. Otherwise the first polling run initializes the
                # cursor from whatever is newest at that later time and can
                # silently skip an entry published between add and first poll.
                "last_id": _get_latest_entry_id(parsed),
                "error_count": 0,
                "next_retry": 0,
                "paused": False,
                "paused_rooms": [],
                "last_checked": _now(),
                "last_success": _now(),
                "last_error": "",
                "last_error_at": 0,
                "last_posted": 0,
                "posted_count": 0,
            }
        except Exception as exc:
            _log_feed_fetch_error("Failed to add direct RSS feed", url, exc)
            bot.reply(msg, f"Failed to fetch or parse feed: {_format_feed_fetch_error(url, exc)}")
            return
    users = _direct_subscriptions(feeds[url])
    key = _normalize_direct_user_jid(owner)
    if not key:
        bot.reply(msg, f"🔴 Invalid direct subscriber JID: {owner}")
        return
    if key in users:
        bot.reply(msg, f"ℹ️ Feed already added for you: {url}")
        return
    users[key] = {"owner": key, "role": str(role)}
    feeds[url]["users"] = users
    await save_feeds(store, feeds)
    await ensure_task(bot, store, url, feeds[url]["period"])
    bot.reply(
        msg,
        f"✅ Added direct RSS feed: {feeds[url]['title']} ({url})\n"
        "New entries will be delivered in this chat.",
    )

async def _delete_direct_feed_target(bot, msg, url, store, target: str):
    url = _normalize_url(url)
    feeds = await get_feeds(store)
    feed = feeds.get(url)
    if not feed:
        bot.reply(msg, "Feed not found.")
        return
    users = _direct_subscriptions(feed)
    target = _normalize_room_jid(target)
    if target not in users:
        bot.reply(msg, f"ℹ️ {target} was not subscribed to the feed.")
        return
    users.pop(target, None)
    if not feed.get("rooms") and not users:
        feeds.pop(url, None)
        await unset_feed_templates_for_feed(store, url)
        await _cancel_feed_task(bot, url)
    else:
        feed["users"] = users
        await unset_feed_template(store, target, url)
    await save_feeds(store, feeds)
    bot.reply(msg, f"🗑 Removed direct RSS subscription for {target}: {url}")

async def _delete_direct_feed(bot, msg, url, store, actor: str, allow_other: bool):
    url = _normalize_url(url)
    feeds = await get_feeds(store)
    feed = feeds.get(url)
    if not feed:
        bot.reply(msg, "Feed not found.")
        return
    users = _direct_subscriptions(feed)
    actor_key = _normalize_room_jid(actor)
    target = actor_key if actor_key in users else None
    if target is None and allow_other:
        trusted = [jid for jid, meta in users.items() if str((meta or {}).get("role", "trusted")).lower() == "trusted"]
        if len(trusted) == 1:
            target = trusted[0]
    if target is None:
        bot.reply(msg, "🔴 You may only remove your own direct RSS feeds.")
        return
    await _delete_direct_feed_target(bot, msg, url, store, target)

async def _delete_all_direct_feeds_for_user(
    bot,
    msg,
    store,
    target: str,
) -> int:
    """Remove every direct RSS subscription belonging to one user."""
    target_key = _normalize_direct_user_jid(target)
    if not target_key:
        bot.reply(msg, f"🔴 Invalid direct subscriber JID: {target}")
        return 0

    feeds = await get_feeds(store)
    removed = 0
    removed_feeds: list[str] = []

    for url, feed in list(feeds.items()):
        if not isinstance(feed, dict):
            continue

        users = _direct_subscriptions(feed)
        matching_keys = [
            jid
            for jid in users
            if _normalize_direct_user_jid(jid) == target_key
        ]
        if not matching_keys:
            continue

        for jid in matching_keys:
            users.pop(jid, None)
        removed += 1

        if not feed.get("rooms") and not users:
            feeds.pop(url, None)
            removed_feeds.append(url)
        else:
            feed["users"] = users

    if not removed:
        bot.reply(
            msg,
            f"ℹ️ No direct RSS subscriptions found for {target_key}.",
        )
        return 0

    await unset_feed_templates_for_room(store, target_key)
    for url in removed_feeds:
        await unset_feed_templates_for_feed(store, url)
        await _cancel_feed_task(bot, url)
    await save_feeds(store, feeds)

    bot.reply(
        msg,
        f"🗑 Removed {removed} direct RSS subscription"
        f"{'s' if removed != 1 else ''} for {target_key}.",
    )
    return removed

async def _add_feed(bot, msg, url, store, room):
    url = _normalize_url(url)
    feeds = await get_feeds(store)

    if url not in feeds:
        try:
            feed = await fetch_feed(url)
            title = feed.feed.get("title", url)
            feed_link = feed.feed.get("link", url)

            # Burst last N (default 5) items to this room
            burst_num = config.get("max_new_feed_entries", 5)
            last_id = await burst_recent_entries(
                bot, feed, room, burst_num, store=store, feed_url=url
            )

            # After burst, remember last_id so next poll ignores
            # already-shown history.
            feeds[url] = {
                "title": title,
                "link": feed_link,
                "period": config.get("rss_global_query_interval",
                                     DEFAULT_POLL_INTERVAL),
                "rooms": [room],
                "last_id": last_id,
                "error_count": 0,
                "next_retry": 0,
                "paused": False,
                "paused_rooms": [],
                "last_checked": _now(),
                "last_success": _now(),
                "last_error": "",
                "last_error_at": 0,
                "last_posted": _now() if last_id else 0,
                "posted_count": 0,
            }

            await save_feeds(store, feeds)
            await ensure_task(bot, store, url, feeds[url]["period"])

            log.debug("[RSS] Added new feed url=%s", url)
            period = feeds[url]["period"]
            bot.reply(
                msg,
                f"✅ Added feed: {title} ({url}) every {period}s to {room}",
            )
        except Exception as e:
            _log_feed_fetch_error("Failed to add RSS feed", url, e)
            bot.reply(
                msg,
                f"Failed to fetch or parse feed: {_format_feed_fetch_error(url, e)}",
            )
            return
    else:
        rooms = _rss_normalize_room_list(feeds[url])
        if not any(_normalize_subscription_room(item) == _normalize_subscription_room(room) for item in rooms):
            rooms.append(room)
            feeds[url]["rooms"] = rooms
            await save_feeds(store, feeds)

            log.debug("[RSS] Added room to feed url=%s", url)
            await ensure_task(
                bot,
                store,
                url,
                feeds[url]["period"],
            )

            # Burst most recent N entries to this newly added room.
            try:
                feed = await fetch_feed(url)
                burst_num = config.get("max_new_feed_entries", 5)
                await burst_recent_entries(
                    bot, feed, room, burst_num, store=store, feed_url=url
                )
            except Exception as e:
                _log_feed_fetch_error(
                    "Failed to fetch or parse feed during burst to new room",
                    url,
                    e,
                )

            bot.reply(
                msg,
                f"✅ Added room {room} to feed: {
                    feeds[url]['title']} ({url})",
            )
        else:
            bot.reply(
                msg,
                f"ℹ️ Feed already added for this room: {url}",
            )

    return

async def _delete_feed_everywhere(bot, msg, url, store, feeds):
    """Remove a feed and its task regardless of subscribed rooms."""
    rooms = list(feeds[url].get("rooms", []))
    feeds.pop(url)
    await unset_feed_templates_for_feed(store, url)
    await _cancel_feed_task(bot, url)

    room_text = ", ".join(rooms) if rooms else "no rooms"
    bot.reply(msg, f"🗑 Deleted feed: {url} ({room_text})")

async def _delete_feed_room(bot, msg, url, store, feeds, room):
    """Remove one room subscription from an existing feed."""
    rooms = feeds[url].setdefault("rooms", [])
    normalized_room = _normalize_room_jid(room)
    stored_room = next(
        (item for item in rooms if _normalize_room_jid(item) == normalized_room),
        None,
    )

    if stored_room is None:
        bot.reply(
            msg,
            f"ℹ️ Room {room} was not subscribed to the feed.",
        )
        return

    rooms.remove(stored_room)

    if not rooms and not _direct_subscriptions(feeds[url]):
        feeds.pop(url)
        await unset_feed_templates_for_feed(store, url)
        await _cancel_feed_task(bot, url)
        bot.reply(
            msg,
            f"🗑 Deleted feed: {url} (no rooms left, feed removed)",
        )
        return

    await unset_feed_template(store, stored_room, url)

    await ensure_task(
        bot,
        store,
        url,
        feeds[url]["period"],
    )

    bot.reply(
        msg,
        f"🗑 Removed room {stored_room} from feed: {url}",
    )

async def _reset_all_feed_retries(bot, msg, store):
    """Clear retry state for every configured RSS feed and restart checks."""
    feeds = await get_feeds(store)

    if not feeds:
        bot.reply(msg, "No feeds configured.")
        return

    for _url, feed in feeds.items():
        _apply_retry_state(feed, 0, 0)

    await save_feeds(store, feeds)

    for url, feed in feeds.items():
        await _cancel_feed_task(bot, url)
        await ensure_task(
            bot,
            store,
            url,
            feed.get("period", DEFAULT_POLL_INTERVAL),
        )

    bot.reply(
        msg,
        f"🔁 Retry state reset and RSS checks scheduled for all feeds ({len(feeds)}).",
    )

async def _del_feed(bot, msg, url, store, room=None, delete_target=None):
    url = _normalize_url(url)
    feeds = await get_feeds(store)
    log.debug("[RSS] Delete feed request url=%s", url)

    if url not in feeds:
        bot.reply(msg, "Feed not found.")
        return

    target = str(delete_target).strip() if delete_target else ""

    if target.lower() == "all":
        await _delete_feed_everywhere(bot, msg, url, store, feeds)
    elif target:
        await _delete_feed_room(
            bot, msg, url, store, feeds, _normalize_room_jid(target)
        )
    elif room:
        await _delete_feed_room(bot, msg, url, store, feeds, room)
    else:
        # Direct/private cleanup path: useful for stale feeds whose room no
        # longer exists and cannot be addressed via a room or MUC PM anymore.
        await _delete_feed_everywhere(bot, msg, url, store, feeds)

    await save_feeds(store, feeds)
    return

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
