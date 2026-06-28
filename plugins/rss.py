""" RSS Feed watcher plugin.

Periodically checks configured RSS/Atom feeds every 20 minutes.
You can add/delete specified feeds to your room.

Commands:
• {prefix}rss add <feedurl>
• {prefix}rss delete <feedurl> [room|all]
• {prefix}rss remove <feedurl> [room|all]
• {prefix}rss list

Feed configuration is stored in the plugin runtime store under the key "RSS".
"""

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
from utils.url_safety import (
    FetchURLTooLarge,
    UnsafeFetchURL,
    validate_fetch_url_async,
)
from core_plugins.rooms import JOINED_ROOMS

try:
    import feedparser
except ImportError:
    feedparser = None


PLUGIN_META = {
    "name": "rss",
    "version": "0.2.2",
    "description": "RSS/Atom feed watcher and poster",
    "category": "info",
    "requires": ["rooms"],
}

from utils.task_supervisor import create_plugin_task
log = logging.getLogger(__name__)

RSS_KEY = "RSS"
CHECK_TASKS = {}

# Operator-tunable configuration constants.
DEFAULT_POLL_INTERVAL = int(config.get("rss_global_query_interval", 1200) or 1200)
BACKOFF_INCREMENT_MULTIPLIER = int(
    config.get("rss_backoff_increment_multiplier", 60) or 60
)
MAX_BACKOFF_TIME = int(config.get("rss_max_backoff_time", 86400) or 86400)
SIMILARITY_THRESHOLD = float(config.get("rss_similarity_threshold", 0.8) or 0.8)
RSS_USER_AGENT = str(
    config.get("rss_user_agent")
    or config.get("http_user_agent")
    or "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)"
)
RSS_FETCH_TIMEOUT_SECONDS = float(
    config.get(
        "rss_fetch_timeout_seconds",
        config.get("http_timeout_seconds", 8),
    )
    or 8
)
RSS_MAX_REDIRECTS = max(1, int(config.get("rss_max_redirects", 5) or 5))
RSS_MAX_READ_BYTES = max(
    4096,
    int(config.get("rss_max_read_bytes", 1048576) or 1048576),
)
ALLOW_PRIVATE_FETCH_URLS = bool(config.get("allow_private_fetch_urls", False))


def _command_prefix(bot=None) -> str:
    """Return the currently configured command prefix for usage replies."""
    return str(
        getattr(bot, "prefix", None)
        or config.get("prefix", ",")
        or ","
    )


def _room_for_feed_command(msg, is_room: bool) -> str | None:
    """Return the target room for RSS add/delete in public MUCs or MUC PMs."""
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


def entry_get(entry, key, default=None):
    # Works for both dicts and SimpleNamespace/objects
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def html_to_text_with_links(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    for a in soup.find_all("a"):
        href = a.get("href")
        if href:
            a.replace_with(f"{a.get_text()} ({href})")
    text = soup.get_text(separator=" ", strip=True)
    return html.unescape(text)


def _should_include_description(
    title: str,
    description: str,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> bool:
    """
    Intelligently check if description should be included.

    Returns False if:
    - Description is empty
    - Description equals title (exact match)
    - Description starts with title (truncated title case)
    - Similarity is above threshold (fuzzy match)
    - Title starts with description (inverse case)

    Args:
        title: Entry title
        description: Entry description
        similarity_threshold: Similarity score (0-1) above which they're
                              considered duplicates

    Returns:
        True if description is meaningfully different, False otherwise
    """
    if not description:
        return False

    # Exact match
    if description == title:
        return False

    # Normalize both for comparison (lowercase, strip whitespace)
    title_norm = title.lower().strip()
    desc_norm = description.lower().strip()

    # One is substring of the other (handles truncation cases)
    if title_norm in desc_norm or desc_norm in title_norm:
        return False

    # Fuzzy similarity check
    similarity = SequenceMatcher(None, title_norm, desc_norm).ratio()
    if similarity >= similarity_threshold:
        return False

    return True


def _extract_entry_link(entry) -> str:
    """
    Extract the best link from an entry following feed standards.

    Supports dict-style (feedparser) and object-style (SimpleNamespace)
    entries.

    For Atom feeds: Check entry.links with rel="alternate"
    For JSON Feed: Check entry.url
    Fallback: entry.id (if it's a URL)

    Args:
        entry: Parsed feed entry (can be dict or object)

    Returns:
        Best available link URL or empty string
    """

    def _get(e, key, default=None):
        if isinstance(e, dict):
            return e.get(key, default)
        return getattr(e, key, default)

    # Atom standard: entry.links with rel="alternate"
    links = _get(entry, "links")
    if links and isinstance(links, list):
        for link_obj in links:
            if isinstance(link_obj, dict):
                if link_obj.get("rel") in (None, "alternate"):
                    href = link_obj.get("href")
                    if (href and isinstance(href, str)
                            and href.startswith(("http://", "https://"))):
                        return href.strip()

    # Standard entry.link
    entry_link = _get(entry, "link")
    if (entry_link and isinstance(entry_link, str)
            and entry_link.startswith(("http://", "https://"))):
        return entry_link.strip()

    # JSON Feed standard: entry.url
    entry_url = _get(entry, "url")
    if (entry_url and isinstance(entry_url, str)
            and entry_url.startswith(("http://", "https://"))):
        return entry_url.strip()

    # Fallback: entry.id (if it's a URL)
    entry_id = _get(entry, "id")
    if (entry_id and isinstance(entry_id, str)
            and entry_id.startswith(("http://", "https://"))):
        return entry_id.strip()

    return ""


def _generate_entry_id(title: str, description: str, link: str) -> str:
    """
    Generate stable entry ID with multiple fallbacks.

    Priority:
    1. Use link if available (most reliable)
    2. Hash title+description if no link

    Args:
        title: Entry title
        description: Entry description
        link: Entry link/URL

    Returns:
        Stable entry ID string
    """
    if link and link.strip():
        return link

    # Hash title+description for unique IDs when no link available
    combined = f"{title}|{description}".encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def _get_entry_id(entry) -> str:
    """Return the stable ID used for RSS duplicate detection."""
    entry_link = _extract_entry_link(entry)
    return _generate_entry_id(
        entry_get(entry, "title", ""),
        entry_get(entry, "description", ""),
        entry_link,
    )


def _get_latest_entry_id(parsed) -> str | None:
    """Return the newest entry ID from a parsed feed, if available."""
    if not parsed.entries:
        return None

    entry_id = _get_entry_id(parsed.entries[0])
    return entry_id or None


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


def _normalize_url(url: str) -> str:
    """
    Normalize URL for consistent storage and comparison.

    Args:
        url: URL to normalize

    Returns:
        Normalized URL
    """
    if not url:
        return url

    # Remove trailing slashes and normalize scheme
    url = url.rstrip("/")

    # Ensure scheme exists.  Preserve unsupported explicit schemes so the
    # shared fetch safety validator can reject them cleanly.
    if not urlparse(url).scheme:
        url = "https://" + url

    return url



def _normalize_room_jid(room: str) -> str:
    """Normalize a room JID used as an RSS subscription key."""
    return str(room or "").strip().lower()


def _resolve_relative_url(base_url: str, relative_url: str) -> str:
    """
    Resolve relative URLs against base URL.

    Args:
        base_url: Base URL (feed URL or feed link)
        relative_url: URL that may be relative

    Returns:
        Absolute URL
    """
    if not relative_url:
        return relative_url

    # Already absolute?
    if relative_url.startswith(("http://", "https://", "ftp://", "mailto:")):
        return relative_url

    if not base_url:
        return relative_url

    try:
        return urljoin(base_url, relative_url)
    except Exception as e:
        log.warning(f"Failed to resolve relative URL {
                    relative_url} against {base_url}: {e}")
        return relative_url


def _get_feed_headers() -> dict[str, str]:
    """Get HTTP headers for feed requests."""
    accept = "application/rss+xml, application/atom+xml, application/json, */*"
    return {
        "User-Agent": RSS_USER_AGENT,
        "Accept": accept,
    }


def _now():
    return int(time.time())


async def get_feeds(store):
    feeds = await store.get_global(RSS_KEY, default={})
    return feeds if isinstance(feeds, dict) else {}


async def save_feeds(store, feeds):
    await store.set_global(RSS_KEY, feeds)


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


async def _fetch_feed_bytes(url: str) -> tuple[bytes, str, str]:
    """Fetch feed bytes with explicit timeout and redirect safety checks."""
    headers = _get_feed_headers()
    timeout = aiohttp.ClientTimeout(total=RSS_FETCH_TIMEOUT_SECONDS)
    current_url = url

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
    ) as session:
        for _ in range(RSS_MAX_REDIRECTS + 1):
            current_url = await validate_fetch_url_async(
                current_url,
                allow_private=ALLOW_PRIVATE_FETCH_URLS,
            )
            async with session.get(current_url, allow_redirects=False) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if not location:
                        raise UnsafeFetchURL(
                            "redirect response without Location header"
                        )
                    current_url = urljoin(str(resp.url), location)
                    continue

                resp.raise_for_status()
                body = await _read_limited_response(resp)
                content_type = resp.headers.get("Content-Type", "")
                return body, str(resp.url), content_type

    raise UnsafeFetchURL("too many redirects")


async def fetch_feed(url):
    """
    Fetch and parse RSS feed with proper URL handling.

    Fetching is done with aiohttp so timeouts, redirects and private-network
    safety checks are enforced before feedparser parses the response bytes.

    Args:
        url: Feed URL to fetch

    Returns:
        Parsed feed result
    """
    if not feedparser:
        raise RuntimeError("feedparser module not installed")

    body, _final_url, content_type = await _fetch_feed_bytes(url)

    result = await asyncio.to_thread(
        feedparser.parse,
        body,
        response_headers=(
            {"content-type": content_type} if content_type else None
        ),
    )

    # Force the feed URL to be the original URL we requested.  This keeps
    # storage stable even when the server redirects the fetch request.
    if "feed" in result:
        result.feed["href"] = url
        result.feed["id"] = url

    return result


async def _load_feed(store, url):
    feeds = await get_feeds(store)
    return feeds, feeds.get(url)


async def _update_feed(bot, store, url, mutator):
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
        # await _flush_user_store(bot)

    return changed


async def _set_feed_field(bot, store, url, field, value):
    def mutator(feed):
        if feed.get(field) == value:
            return False
        feed[field] = value
        return True

    return await _update_feed(bot, store, url, mutator)


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


async def _update_feed_link(bot, store, url, feed_link):
    return await _set_feed_field(bot, store, url, "link", feed_link)


async def _initialize_last_id(bot, store, url, latest_id):
    if not latest_id:
        return False
    return await _set_feed_field(bot, store, url, "last_id", latest_id)


def _build_rss_message(feed_title, entry_title, entry_desc, entry_link):
    if _should_include_description(entry_title, entry_desc):
        out = f"[RSS] ({feed_title}) {entry_title} - {entry_desc}\n"
        out += f"{entry_link}"
        return out
    return f"[RSS] ({feed_title}) {entry_title}\n{entry_link}"


def _entry_is_new(last_id, entry):
    entry_id = _get_entry_id(entry)
    if not entry_id:
        return False, None
    if entry_id == last_id:
        return False, entry_id
    return True, entry_id


async def _post_entry_to_rooms(bot, rooms, msg):
    posted = False
    for room in rooms:
        if room in JOINED_ROOMS:
            bot.reply(
                {
                    "from": type("F", (), {"bare": room})(),
                    "type": "groupchat",
                },
                msg,
                mention=False,
                thread=True,
                rate_limit=False,
                ephemeral=False,
            )
            posted = True
    return posted


async def _save_last_id(bot, store, url, entry_id):
    return await _set_feed_field(bot, store, url, "last_id", entry_id)


async def _handle_fetch_error(bot, store, url, period, now, error_count, exc):
    log.warning("Failed to fetch RSS feed %s: %s", url, exc)

    error_count += 1
    backoff_delay = (DEFAULT_POLL_INTERVAL *
                     BACKOFF_INCREMENT_MULTIPLIER * error_count)
    backoff_delay = min(backoff_delay, MAX_BACKOFF_TIME)
    next_retry = now + backoff_delay

    await _set_retry_state(bot, store, url, error_count, next_retry)
    log.debug(
        "Feed %s backoff set to %s errors, retry at %s",
        url,
        error_count,
        next_retry,
    )
    await asyncio.sleep(period)


async def _sleep_for_retry(period, next_retry, now):
    if next_retry > now:
        await asyncio.sleep(min(period, next_retry - now))
        return True
    return False


async def _handle_empty_feed(url, period, parsed):
    if not parsed.entries:
        log.debug("Feed %s has no entries", url)
        await asyncio.sleep(period)
        return True
    return False


async def _handle_feed_recovery(bot, store, url, error_count):
    if error_count > 0:
        log.debug("Feed %s recovered, resetting error count", url)
        await _reset_retry_state(bot, store, url)


async def _maybe_update_feed_link(bot, store, url, parsed, feed_link):
    if "feed" in parsed and "link" in parsed.feed:
        feed_link = parsed.feed["link"]
        await _update_feed_link(bot, store, url, feed_link)
    return feed_link


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


def _collect_new_entries(parsed, last_id):
    new_entries = []
    for entry in parsed.entries:
        is_new, entry_id = _entry_is_new(last_id, entry)
        if not entry_id:
            continue
        if not is_new:
            break
        new_entries.append((entry, entry_id))
    return new_entries


async def _post_new_entries(bot, store, url, feed_title,
                            feed_link, rooms, new_entries):
    for entry, entry_id in reversed(new_entries):
        entry_link = _normalize_url(
            _resolve_relative_url(feed_link, _extract_entry_link(entry))
        )
        entry_title = html_to_text_with_links(
            entry_get(entry, "title", "No title")
        )
        entry_desc = html_to_text_with_links(
            entry_get(entry, "description", "")
        )

        msg = _build_rss_message(
            feed_title,
            entry_title,
            entry_desc,
            entry_link,
        )

        posted = await _post_entry_to_rooms(bot, rooms, msg)

        if not await _save_last_id(bot, store, url, entry_id):
            log.warning("Feed %s was deleted during posting!", url)
            break

        if posted:
            log.debug(
                "[RSS] Posted and saved last_id for %s: %s",
                url,
                entry_id,
            )
        else:
            log.debug(
                "[RSS] Saved last_id for %s without posting; no joined rooms",
                url,
            )


async def rss_check_loop(bot, store, url, period):
    """Periodically check a feed for updates and post new items."""
    while True:
        _, feed = await _load_feed(store, url)

        if feed is None:
            break

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

        if await _handle_empty_feed(url, period, parsed):
            continue

        await _handle_feed_recovery(bot, store, url, error_count)

        feed_link = await _maybe_update_feed_link(
            bot, store, url, parsed, feed_link
        )

        if await _initialize_missing_last_id(bot, store, url, last_id, parsed):
            await asyncio.sleep(period)
            continue

        new_entries = _collect_new_entries(parsed, last_id)
        await _post_new_entries(
            bot, store, url, feed_title, feed_link, rooms, new_entries
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


@command("rss", role=Role.MODERATOR)
async def rss_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Manage RSS feeds.

    Add/delete/list Feed URLs to your room. The feeds are checked every
    20 minutes globally (configurable).

    Usage:
    {prefix}rss add <feedurl>
    {prefix}rss delete <feedurl> [room|all]
    {prefix}rss remove <feedurl> [room|all]
    {prefix}rss list
    """
    store = bot.db.users.plugin("rss")

    if not args:
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}rss <add|delete|remove|list> ...",
        )
        return

    sub = args[0].lower()
    room = None

    room = _room_for_feed_command(msg, is_room)

    # Add feed to room
    if sub == "add":
        if len(args) != 2:
            bot.reply(
                msg,
                f"Usage: {_command_prefix(bot)}rss add <feedurl> "
                "(in a room or MUC DM only)",
            )
            return

        if not room:
            bot.reply(msg, "🔴 RSS add can only be used in a room or MUC DM.")
            return

        await _add_feed(bot, msg, args[1], store, room)
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
        await _del_feed(bot, msg, args[1], store, room, delete_target)
        return

    # List all rooms
    elif sub == "list":
        feeds = await get_feeds(store)

        if not feeds:
            bot.reply(msg, "No feeds configured.")
            return

        lines = [" Watched RSS feeds:"]
        for feed_url, data in feeds.items():
            error_count = data.get("error_count", 0)
            status = ""

            if error_count > 0:
                status = f" ⚠️ Last {error_count} fetch(es) failed\n"

            lines.append(
                f"- {feed_url}\n Title: {data.get('title', feed_url)}\n"
                f" Period: {data.get('period', '?')}s\n"
                f" Rooms: {', '.join(data.get('rooms', []))}\n"
                f"{status}"
            )

        bot.reply(msg, lines)

    else:
        bot.reply(msg, "Unknown subcommand. Use add, delete, remove, or list.")


# ----------------
# ADD FEED TO ROOM
# ----------------
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

            log.info(f"[RSS] Added new feed {store}\n\n{feeds}")
            period = feeds[url]["period"]
            bot.reply(
                msg,
                f"✅ Added feed: {title} ({url}) every {period}s to {room}",
            )
        except Exception as e:
            log.exception(f"Failed to fetch or parse feed {url}")
            bot.reply(msg, f"Failed to fetch or parse feed: {e}")
            return
    else:
        if room not in feeds[url]["rooms"]:
            feeds[url]["rooms"].append(room)
            await save_feeds(store, feeds)
            # await _flush_user_store(bot)

            log.info(f"[RSS] ADD: {store}\n\n{feeds}")
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
                log.exception(
                    "Failed to fetch or parse feed during burst"
                    f" to new room: {url}: {e}")

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


# -------------------------
# DELETE RSS FEED FROM ROOM
# -------------------------
def _cancel_feed_task(url: str) -> None:
    """Cancel the background check task for a feed URL when it exists."""
    task = CHECK_TASKS.pop(url, None)
    if task is not None:
        task.cancel()


def _delete_feed_everywhere(bot, msg, url, feeds):
    """Remove a feed and its task regardless of subscribed rooms."""
    rooms = list(feeds[url].get("rooms", []))
    feeds.pop(url)
    _cancel_feed_task(url)

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
        _cancel_feed_task(url)
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


async def _del_feed(bot, msg, url, store, room=None, delete_target=None):
    url = _normalize_url(url)
    feeds = await get_feeds(store)
    log.info(f"[RSS] DELETE: {store}\n\n{feeds}")

    if url not in feeds:
        bot.reply(msg, "Feed not found.")
        return

    target = str(delete_target).strip() if delete_target else ""

    if target.lower() == "all":
        _delete_feed_everywhere(bot, msg, url, feeds)
    elif target:
        await _delete_feed_room(
            bot, msg, url, store, feeds, _normalize_room_jid(target)
        )
    elif room:
        await _delete_feed_room(bot, msg, url, store, feeds, room)
    else:
        # Direct/private cleanup path: useful for stale feeds whose room no
        # longer exists and cannot be addressed via a room or MUC PM anymore.
        _delete_feed_everywhere(bot, msg, url, feeds)

    await save_feeds(store, feeds)
    # await _flush_user_store(bot)
    return


async def on_load(bot):
    if feedparser is None:
        log.error(
            "[RSS] feedparser module not installed. RSS plugin will not work."
        )
        return

    await restart_all_tasks(bot)


async def on_unload(bot):
    """
    Clean up all RSS tasks on unload.

    Prevents task orphaning and memory leaks.
    """
    log.info("[RSS] Cleaning up RSS feed tasks...")

    # Cancel all active tasks
    for url, task in list(CHECK_TASKS.items()):
        try:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                log.debug(f"[RSS] Task for {url} cancelled")

            CHECK_TASKS.pop(url, None)
        except Exception as e:
            log.exception(f"[RSS] Error cancelling task for {url}: {e}")

    log.info("[RSS] ✅ All RSS tasks cleaned up")
