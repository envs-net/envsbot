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
    "version": "0.1.0",
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


async def rss_check_loop(bot, url, period, rooms):
    store = bot.db.users.plugin("rss")
    while True:
        try:
            feed = await fetch_feed(url)
            if feed.bozo:
                log.warning(f"[RSS] Failed to parse feed: {url}")
            else:
                title = feed.feed.get("title", url)
                entries = feed.entries
                feeds = await get_feeds(store)
                last_id = feeds.get(url, {}).get("last_id")
                new_items = []
                for entry in entries:
                    entry_id = entry.get("id") or entry.get("link")
                    if not entry_id:
                        continue
                    if last_id == entry_id:
                        break
                    new_items.append(entry)
                if new_items:
                    for entry in reversed(new_items):
                        entry_title = entry.get("title", "(no title)")
                        entry_link = entry.get("link", "")
                        msg = f"[RSS] {entry_title} - {entry_link}"
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
                                    thread=False,
                                    rate_limit=False,
                                    ephemeral=False,
                                )
                    feeds = await get_feeds(store)
                    feeds[url]["last_id"] = (
                        new_items[0].get("id") or new_items[0].get("link")
                    )
                    await save_feeds(store, feeds)
                elif entries:
                    feeds = await get_feeds(store)
                    if feeds[url].get("last_id") is None:
                        feeds[url]["last_id"] = (
                            entries[0].get("id") or entries[0].get("link")
                        )
                        await save_feeds(store, feeds)
        except Exception as e:
            log.exception(f"[RSS] Error checking feed {url}: {e}")
        await asyncio.sleep(period)


async def ensure_task(bot, url, period, rooms):
    if url in CHECK_TASKS and not CHECK_TASKS[url].done():
        return
    CHECK_TASKS[url] = asyncio.create_task(
        rss_check_loop(bot, url, period, rooms)
    )


async def restart_all_tasks(bot):
    for t in CHECK_TASKS.values():
        if not t.done():
            t.cancel()
    CHECK_TASKS.clear()
    store = bot.db.users.plugin("rss")
    feeds = await get_feeds(store)
    for url, data in feeds.items():
        await ensure_task(bot, url, data["period"], data["rooms"])


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
            await ensure_task(bot, url, 1200, [room])
            bot.reply(
                msg,
                f"✅ Added feed: {title} ({url}) every 1200s to {room}",
            )
        else:
            if room not in feeds[url]["rooms"]:
                feeds[url]["rooms"].append(room)
                await save_feeds(store, feeds)
                await ensure_task(
                    bot, url, feeds[url]["period"], feeds[url]["rooms"]
                )
                bot.reply(
                    msg,
                    f"✅ Added room {room} to feed: {feeds[url]['title']} ({url})",
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
                    bot, url, feeds[url]["period"], feeds[url]["rooms"]
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
