"""Split module for plugins/rss.py: commands."""

import asyncio
import logging
import time
import html
import hashlib
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse
import aiohttp
from bs4 import BeautifulSoup
from utils.command import command, Role
from utils.config import config
from core_plugins._core import paginate_items
from utils.url_safety import (
    FetchURLTooLarge,
    UnsafeFetchURL,
    validate_fetch_url_async,
)
from core_plugins.rooms import JOINED_ROOMS
from core_plugins.users import user_has_room_plugin_grant
from utils.audit import audit_event
from utils.task_supervisor import create_plugin_task


def _command_prefix(bot=None) -> str:
    """Return the currently configured command prefix for usage replies."""
    return str(
        getattr(bot, "prefix", None)
        or config.get("prefix", ",")
        or ","
    )


def _room_for_feed_command(msg, is_room: bool, explicit_room=None) -> str | None:
    """Return the target room for RSS commands.

    Public MUCs and MUC PMs imply the room. Private chats may pass an
    explicit room JID, which is useful for room-scoped plugin grants and stale
    feed cleanup.
    """
    if explicit_room:
        return _normalize_room_jid(explicit_room)

    sender = msg["from"]
    room_jid = getattr(sender, "bare", None)

    if is_room and msg.get("type") == "groupchat" and room_jid:
        return str(room_jid)

    if (
        msg.get("type") in ("chat", "normal")
        and room_jid in JOINED_ROOMS
        and getattr(sender, "resource", None)
    ):
        return str(room_jid)

    return None


async def _sender_is_global_rss_manager(bot, sender_jid: str) -> bool:
    """Return True when sender has global RSS management rights."""
    get_role = getattr(bot, "get_user_role", None)
    if not callable(get_role):
        return False
    try:
        return await get_role(str(sender_jid)) <= Role.MODERATOR
    except Exception:
        log.debug("[RSS] Could not resolve global sender role", exc_info=True)
        return False


async def _sender_can_manage_rss_room(bot, sender_jid: str, room: str) -> bool:
    """Return True for global moderators or RSS grant plus room affiliation."""
    if await _sender_is_global_rss_manager(bot, sender_jid):
        return True
    return await user_has_room_plugin_grant(bot, sender_jid, "rss", room)


async def _sender_can_manage_rss_globally(bot, sender_jid: str) -> bool:
    """Return True when sender can manage RSS state across all rooms."""
    return await _sender_is_global_rss_manager(bot, sender_jid)


def _looks_like_room_arg(value) -> bool:
    """Best-effort test for explicit room JID arguments."""
    text = str(value or "").strip()
    return "@" in text and "://" not in text


def _normalize_room_jid(room: str) -> str:
    """Normalize a room JID used as an RSS subscription key."""
    return str(room or "").strip().lower()


def _now():
    return int(time.time())


async def _read_limited_response(resp) -> bytes:
    """Read an aiohttp response without exceeding RSS_MAX_READ_BYTES."""
    chunks = bytearray()
    async for chunk in resp.content.iter_chunked(8192):
        chunks.extend(chunk)
        if len(chunks) > RSS_MAX_READ_BYTES:
            raise FetchURLTooLarge(
                f"feed response exceeds {RSS_MAX_READ_BYTES} bytes"
            )
    return bytes(chunks)


def _mapping_value(mapping, key, default=None):
    """Return a value from feed metadata mapping or attribute objects."""
    if isinstance(mapping, dict):
        return mapping.get(key, default)
    return getattr(mapping, key, default)


def _set_mapping_value(mapping, key, value) -> None:
    """Set a value on feed metadata mapping or attribute objects."""
    if isinstance(mapping, dict):
        mapping[key] = value
    else:
        setattr(mapping, key, value)


async def _initialize_last_id(bot, store, url, latest_id):
    if not latest_id:
        return False
    return await _set_feed_field(bot, store, url, "last_id", latest_id)


async def _save_last_id(bot, store, url, entry_id):
    return await _set_feed_field(bot, store, url, "last_id", entry_id)


def _rss_list_usage(bot=None) -> str:
    """Return the usage string for paginated RSS list output."""
    return f"Usage: {_command_prefix(bot)}rss list [page|all|last]"


def _rss_list_page(args, total: int, page_size: int):
    """Parse RSS list paging arguments.

    Returns ``(page, show_all)`` for valid input, or ``None`` for invalid
    arguments. The ``args`` list includes the ``list`` subcommand itself.
    """
    if len(args) > 2:
        return None

    if len(args) == 1:
        return 1, False

    value = str(args[1]).strip().lower()

    if value == "all":
        return 1, True

    total_pages = max(1, (total + page_size - 1) // page_size)

    if value == "last":
        return total_pages, False

    try:
        return max(1, int(value)), False
    except ValueError:
        return None


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


async def burst_recent_entries(bot, feed, room, burst_num):
    """
    Burst the last N entries of the given feed to the room.
    """
    title = feed.feed.get("title", "")
    feed_link = feed.feed.get("link", "")
    entries = feed.entries[:burst_num]
    entries = list(reversed(entries))
    last_id = None

    for entry in entries:
        entry_link = _extract_entry_link(entry)
        entry_id = _get_entry_id(entry)

        entry_title = html_to_text_with_links(
            entry_get(entry, "title", "No title"))
        entry_desc = html_to_text_with_links(
            entry_get(entry, "description", ""))

        # Resolve and normalize link
        entry_link = _resolve_relative_url(feed_link, entry_link)
        entry_link = _normalize_url(entry_link)

        if _should_include_description(entry_title, entry_desc):
            msg_text = f"[RSS] ({title}) {entry_title} - {entry_desc}\n"
        else:
            msg_text = f"[RSS] ({title}) {entry_title}\n"

        msg_text += f"{entry_link}"

        bot.reply(
            {
                "from": type("F", (), {"bare": room})(),
                "type": "groupchat",
            },
            msg_text,
            mention=False,
            thread=True,
            rate_limit=False,
            ephemeral=False,
        )

        # Track newest entry ID from the burst.
        last_id = entry_id

    return last_id


@command("rss", role=Role.USER)
async def rss_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Manage RSS feeds.

    Add/delete/list Feed URLs to your room. The feeds are checked every
    20 minutes globally (configurable).

    Usage:
    {prefix}rss add <feedurl> [room_jid]
    {prefix}rss delete|remove|del|rm <feedurl> [room_jid|all]
    {prefix}rss retry|reset <feedurl>|all [room_jid]
    {prefix}rss list [room_jid] [page|all|last]
    """
    store = bot.db.users.plugin("rss")

    if not args:
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}rss "
            "<add|delete|remove|del|rm|retry|reset|list> ...",
        )
        return

    sub = args[0].lower()
    room = _room_for_feed_command(msg, is_room)

    # Add feed to room
    if sub == "add":
        if len(args) not in (2, 3):
            bot.reply(
                msg,
                f"Usage: {_command_prefix(bot)}rss add <feedurl> [room_jid]",
            )
            return

        room = _room_for_feed_command(
            msg,
            is_room,
            explicit_room=args[2] if len(args) == 3 else None,
        )
        if not room:
            bot.reply(
                msg,
                "🔴 RSS add needs a room context or explicit room JID.",
            )
            return
        if not await _sender_can_manage_rss_room(bot, sender_jid, room):
            bot.reply(
                msg,
                "🔴 You need a global moderator role, or an RSS plugin grant "
                f"and owner/admin affiliation in {room}.",
            )
            return

        await _add_feed(bot, msg, args[1], store, room)
        await audit_event(
            bot,
            "rss_feed_add_requested",
            actor=sender_jid,
            target=room,
            details={"url": _normalize_url(args[1])},
        )
        return

    # Delete feed from a room, or remove it completely from direct/admin PMs.
    elif sub in {"delete", "remove", "del", "rm"}:
        if len(args) not in (2, 3):
            bot.reply(
                msg,
                f"Usage: {_command_prefix(bot)}rss delete <feedurl> [room|all]",
            )
            return

        delete_target = args[2] if len(args) == 3 else None
        target_room = None
        if delete_target and str(delete_target).strip().lower() != "all":
            target_room = _normalize_room_jid(delete_target)
        elif room:
            target_room = room

        if delete_target and str(delete_target).strip().lower() == "all":
            if not await _sender_can_manage_rss_globally(bot, sender_jid):
                bot.reply(msg, "🔴 Only global moderators can delete RSS feeds everywhere.")
                return
        elif target_room:
            if not await _sender_can_manage_rss_room(bot, sender_jid, target_room):
                bot.reply(
                    msg,
                    "🔴 You need a global moderator role, or an RSS plugin "
                    f"grant and owner/admin affiliation in {target_room}.",
                )
                return
        elif not await _sender_can_manage_rss_globally(bot, sender_jid):
            bot.reply(
                msg,
                "🔴 RSS delete from private chat needs an explicit room JID "
                "unless you are a global moderator.",
            )
            return

        await _del_feed(bot, msg, args[1], store, room, delete_target)
        await audit_event(
            bot,
            "rss_feed_delete_requested",
            actor=sender_jid,
            target=target_room or delete_target or room or "rss",
            details={"url": _normalize_url(args[1]), "target": delete_target},
        )
        return

    elif sub in {"retry", "reset"}:
        if len(args) not in (2, 3):
            bot.reply(
                msg,
                f"Usage: {_command_prefix(bot)}rss {sub} <feedurl>|all [room_jid]",
            )
            return

        retry_target = str(args[1]).strip()
        if retry_target.lower() == "all":
            if len(args) != 2:
                bot.reply(
                    msg,
                    f"Usage: {_command_prefix(bot)}rss {sub} <feedurl>|all [room_jid]",
                )
                return
            if not await _sender_can_manage_rss_globally(bot, sender_jid):
                bot.reply(msg, "🔴 Only global moderators can reset all RSS retries.")
                return
            await _reset_all_feed_retries(bot, msg, store)
            await audit_event(
                bot,
                "rss_retry_reset",
                actor=sender_jid,
                target="all",
            )
            return

        target_room = _room_for_feed_command(
            msg,
            is_room,
            explicit_room=args[2] if len(args) == 3 else None,
        )
        if target_room:
            if not await _sender_can_manage_rss_room(bot, sender_jid, target_room):
                bot.reply(
                    msg,
                    "🔴 You need a global moderator role, or an RSS plugin "
                    f"grant and owner/admin affiliation in {target_room}.",
                )
                return
        elif not await _sender_can_manage_rss_globally(bot, sender_jid):
            bot.reply(
                msg,
                f"🔴 RSS {sub} needs an explicit room JID unless you are a "
                "global moderator.",
            )
            return

        await _reset_feed_retry(bot, msg, retry_target, store)
        await audit_event(
            bot,
            "rss_retry_reset",
            actor=sender_jid,
            target=target_room or "rss",
            details={"url": _normalize_url(retry_target)},
        )
        return

    # List rooms or one explicitly targeted room.
    elif sub == "list":
        feeds = await get_feeds(store)

        if not feeds:
            bot.reply(msg, "No feeds configured.")
            return

        list_args = args
        target_room = room
        explicit_room = False
        if len(args) >= 2 and _looks_like_room_arg(args[1]):
            target_room = _normalize_room_jid(args[1])
            list_args = [args[0], *args[2:]]
            explicit_room = True

        is_global_manager = await _sender_can_manage_rss_globally(
            bot, sender_jid
        )
        if explicit_room or not is_global_manager:
            if not target_room:
                bot.reply(
                    msg,
                    "🔴 RSS list from private chat needs an explicit room JID "
                    "unless you are a global moderator.",
                )
                return
            if not await _sender_can_manage_rss_room(bot, sender_jid, target_room):
                bot.reply(
                    msg,
                    "🔴 You need a global moderator role, or an RSS plugin "
                    f"grant and owner/admin affiliation in {target_room}.",
                )
                return
            feeds = _filter_feeds_for_room(feeds, target_room)
            if not feeds:
                bot.reply(msg, f"No feeds configured for {target_room}.")
                return

        lines = _format_feed_list(feeds, list_args, bot=bot)

        if lines is None:
            bot.reply(msg, _rss_list_usage(bot))
            return

        bot.reply(msg, lines)

    else:
        bot.reply(
            msg,
            "Unknown subcommand. Use add, delete, remove, retry, reset, or list.",
        )


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
            last_id = await burst_recent_entries(bot, feed,
                                                 room, burst_num)

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
            }

            await save_feeds(store, feeds)
            # await _flush_user_store(bot)
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
        if room not in feeds[url]["rooms"]:
            feeds[url]["rooms"].append(room)
            await save_feeds(store, feeds)
            # await _flush_user_store(bot)

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
                await burst_recent_entries(bot, feed, room, burst_num)
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


async def _delete_feed_everywhere(bot, msg, url, feeds):
    """Remove a feed and its task regardless of subscribed rooms."""
    rooms = list(feeds[url].get("rooms", []))
    feeds.pop(url)
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

    if not rooms:
        feeds.pop(url)
        await _cancel_feed_task(bot, url)
        bot.reply(
            msg,
            f"🗑 Deleted feed: {url} (no rooms left, feed removed)",
        )
        return

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

    for url, feed in feeds.items():
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
        await _delete_feed_everywhere(bot, msg, url, feeds)
    elif target:
        await _delete_feed_room(
            bot, msg, url, store, feeds, _normalize_room_jid(target)
        )
    elif room:
        await _delete_feed_room(bot, msg, url, store, feeds, room)
    else:
        # Direct/private cleanup path: useful for stale feeds whose room no
        # longer exists and cannot be addressed via a room or MUC PM anymore.
        await _delete_feed_everywhere(bot, msg, url, feeds)

    await save_feeds(store, feeds)
    # await _flush_user_store(bot)
    return
