"""
RSS Feed watcher plugin.

Periodically checks configured RSS/Atom feeds every 20 minutes. You can
add/delete specified feeds to your room.

Commands:
    {prefix}rss add <url>
    {prefix}rss delete <url>
    {prefix}rss list

Feed configuration is stored in the plugin runtime store under the key "RSS".
"""

import asyncio
import logging
import time
from utils.command import command, Role
from plugins.rooms import JOINED_ROOMS

try:
    import feedparser
except ImportError:
    feedparser = None

PLUGIN_META = {
    "name": "rss",
    "version": "0.1.1",
    "description": "RSS/Atom feed watcher and poster",
    "category": "info",
    "requires": ["rooms"],
}

log = logging.getLogger(__name__)

RSS_KEY = "RSS"
CHECK_TASKS = {}


def _now():
    return int(time.time())


async def get_feeds(store):
    feeds = await store.get_global(RSS_KEY, default={})
    return feeds if isinstance(feeds, dict) else {}


async def save_feeds(store, feeds):
    await store.set_global(RSS_KEY, feeds)


async def fetch_feed(url):
    if not feedparser:
        raise RuntimeError("feedparser module not installed")
    return await asyncio.to_thread(feedparser.parse, url)


async def rss_check_loop(bot, store, url, period):
    """Periodically check a feed for updates and post new items."""
    while True:
        feeds = await get_feeds(store)
        # Exit loop if feed has been deleted
        if url not in feeds:
            break

        feed = feeds[url]
        feed_title = feed["title"]
        last_id = feed.get("last_id")
        rooms = feed.get("rooms", [])

        try:
            parsed = await asyncio.to_thread(feedparser.parse, url)
        except Exception as e:
            log.warning(f"Failed to fetch RSS feed {url}: {e}")
            await asyncio.sleep(period)
            continue

        if not parsed.entries:
            await asyncio.sleep(period)
            continue

        # Find new entries
        new_entries = []
        for entry in parsed.entries:
            entry_id = entry.get("id") or entry.get("link")
            if not entry_id:
                continue
            if last_id == entry_id:
                break
            new_entries.append(entry)

        # Post new entries in reverse order (oldest first)
        for entry in reversed(new_entries):
            entry_id = entry.get("id") or entry.get("link")
            entry_title = entry.get("title", "No title")
            entry_link = entry.get("link", "")
            msg = f"[RSS] ({feed_title}) {entry_title} - {entry_link}"
            for room in rooms:
                if room in JOINED_ROOMS:
                    bot.reply(
                        {
                            "from": type(
                                "F", (), {"bare": room}
                            )(),
                            "type": "groupchat",
                        },
                        msg,
                        mention=False,
                        thread=True,
                        rate_limit=False,
                        ephemeral=False,
                    )
            # Update last_id after posting
            feeds = await get_feeds(store)
            if url not in feeds:
                break  # Feed was deleted during posting
            feeds[url]["last_id"] = entry_id
            await save_feeds(store, feeds)

        await asyncio.sleep(period)


async def ensure_task(bot, store, url, period):
    """Ensure a check task is running for the given feed."""
    if url in CHECK_TASKS and not CHECK_TASKS[url].done():
        return
    CHECK_TASKS[url] = asyncio.create_task(
        rss_check_loop(bot, store, url, period)
    )


async def restart_all_tasks(bot):
    store = bot.db.users.plugin("rss")
    feeds = await get_feeds(store)
    for url, feed in feeds.items():
        period = feed.get("period", 1200)
        await ensure_task(bot, store, url, period)


@command("rss", role=Role.MODERATOR)
async def rss_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Manage RSS feeds. Add/delete/list Feed URLs to your room. The feeds are
    checked every 20 minutes globally.

    Usage:
        {prefix}rss add <url>
        {prefix}rss delete <url>
        {prefix}rss list
    """
    store = bot.db.users.plugin("rss")
    if not args:
        bot.reply(msg, "Usage: rss <add|delete|list> ...")
        return
    sub = args[0].lower()
    room = None
    if is_room or (
        msg.get("type") in ("chat", "normal")
        and hasattr(msg["from"], "bare")
        and "@" in str(msg["from"].bare)
    ):
        room = msg["from"].bare

    if sub == "add":
        if len(args) != 2:
            bot.reply(
                msg,
                "Usage: rss add <url> (in a room or MUC DM only)",
            )
            return
        if not room:
            bot.reply(
                msg,
                "❌ RSS add can only be used in a room or MUC DM.",
            )
            return
        url = args[1]
        feeds = await get_feeds(store)
        if url not in feeds:
            try:
                feed = await fetch_feed(url)
                title = feed.feed.get("title", url)
            except Exception:
                bot.reply(msg, f"Failed to fetch or parse feed: {url}")
                return
            feeds[url] = {
                "title": title,
                "period": 1200,
                "rooms": [room],
                "last_id": None,
            }
            await save_feeds(store, feeds)
            await ensure_task(bot, store, url, feeds[url]["period"])
            bot.reply(
                msg,
                f"✅ Added feed: {title} ({url}) every 1200s to {room}",
            )
        else:
            if room not in feeds[url]["rooms"]:
                feeds[url]["rooms"].append(room)
                await save_feeds(store, feeds)
                await ensure_task(
                    bot, store, url, feeds[url]["period"]
                )
                bot.reply(
                    msg,
                    f"✅ Added room {room} to feed:" +
                    f" {feeds[url]['title']} ({url})",
                )
            else:
                bot.reply(
                    msg,
                    f"ℹ️ Feed already added for this room: {url}",
                )
        return

    elif sub == "delete":
        if len(args) != 2:
            bot.reply(msg, "Usage: rss delete <url>")
            return
        if not room:
            bot.reply(
                msg,
                "❌ RSS delete can only be used in a room or MUC DM.",
            )
            return
        url = args[1]
        feeds = await get_feeds(store)
        if url not in feeds:
            bot.reply(msg, "Feed not found.")
            return
        if room in feeds[url]["rooms"]:
            feeds[url]["rooms"].remove(room)
            if not feeds[url]["rooms"]:
                # No rooms left, remove feed
                feeds.pop(url)
                if url in CHECK_TASKS:
                    CHECK_TASKS[url].cancel()
                    del CHECK_TASKS[url]
                bot.reply(
                    msg,
                    f"🗑️ Deleted feed: {url} (no rooms left, feed removed)",
                )
            else:
                await save_feeds(store, feeds)
                await ensure_task(
                    bot, store, url, feeds[url]["period"]
                )
                bot.reply(
                    msg,
                    f"🗑️ Removed this room from feed: {url}",
                )
        else:
            bot.reply(
                msg,
                "ℹ️ This room was not subscribed to the feed.",
            )
        await save_feeds(store, feeds)
        return

    elif sub == "list":
        feeds = await get_feeds(store)
        if not feeds:
            bot.reply(msg, "No feeds configured.")
            return
        lines = ["📋 Watched RSS feeds:"]
        for url, data in feeds.items():
            lines.append(
                f"- {url}\n  Title: {data.get('title', url)}\n"
                f"  Period: {data.get('period', '?')}s\n"
                f"  Rooms: {', '.join(data.get('rooms', []))}"
            )
        bot.reply(msg, lines)
    else:
        bot.reply(msg, "Unknown subcommand. Use add, delete, or list.")


async def on_load(bot):
    if feedparser is None:
        log.error(
            "[RSS] feedparser module not installed. RSS plugin will not work."
        )
        return
    await restart_all_tasks(bot)
