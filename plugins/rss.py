""" RSS Feed watcher plugin.

Periodically checks configured RSS/Atom feeds every 20 minutes.
You can add/delete specified feeds to your room.

Commands:
• {prefix}rss add <feedurl>
• {prefix}rss delete <feedurl> [room|all]
• {prefix}rss remove <feedurl> [room|all]
• {prefix}rss retry <feedurl>|all
• {prefix}rss reset <feedurl>|all
• {prefix}rss list [page|all|last]

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
from core_plugins._core import paginate_items
from utils.url_safety import (
    FetchURLTooLarge,
    UnsafeFetchURL,
    validate_fetch_url_async,
)
from core_plugins.rooms import JOINED_ROOMS
from core_plugins.users import user_has_room_plugin_grant
from utils.audit import audit_event

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
RSS_RETRY_INITIAL_DELAY = max(
    1,
    int(config.get("rss_retry_initial_delay", 300) or 300),
)
RSS_RETRY_BACKOFF_MULTIPLIER = max(
    1.0,
    float(config.get("rss_retry_backoff_multiplier", 2.0) or 2.0),
)
MAX_BACKOFF_TIME = max(
    1,
    int(config.get("rss_max_backoff_time", 3600) or 3600),
)
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
RSS_LIST_PAGE_SIZE = max(1, int(config.get("rss_list_page_size", 10) or 10))


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
        log.warning(
            "Failed to resolve relative URL %s against %s: %s",
            relative_url,
            base_url,
            e,
        )
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


async def get_rss_store(bot):
    """Return the runtime store for RSS feed state."""
    return bot.db.users.plugin("rss")


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


def _parsed_value(parsed, key, default=None):
    """Return a feedparser result value from mapping or attribute objects."""
    if isinstance(parsed, dict):
        return parsed.get(key, default)
    return getattr(parsed, key, default)


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


def _has_feed_metadata(feed) -> bool:
    """Return True when parsed feed metadata looks like RSS/Atom data."""
    if not feed:
        return False

    metadata_keys = (
        "title",
        "link",
        "description",
        "subtitle",
        "id",
        "href",
        "updated",
    )
    for key in metadata_keys:
        value = _mapping_value(feed, key)
        if isinstance(value, str):
            if value.strip():
                return True
        elif value:
            return True
    return False


def _validate_parsed_feed(parsed, url: str):
    """Reject fetched content that does not look like an RSS/Atom feed.

    Empty but otherwise valid feeds are accepted: some new feeds have metadata
    but no entries yet. Plain HTML/error pages and unreadable feed bodies are
    rejected before they can be stored via ``,rss add``.
    """
    feed = _parsed_value(parsed, "feed", {}) or {}
    entries = _parsed_value(parsed, "entries", []) or []
    has_entries = bool(entries)
    has_metadata = _has_feed_metadata(feed)
    is_bozo = bool(_parsed_value(parsed, "bozo", False))

    if is_bozo and not has_entries and not has_metadata:
        exc = _parsed_value(parsed, "bozo_exception", None)
        detail = str(exc) if exc else "parse failed"
        raise ValueError(f"Invalid RSS/Atom feed at {url}: {detail}")

    if not has_entries and not has_metadata:
        raise ValueError(f"URL does not look like an RSS/Atom feed: {url}")

    return parsed


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
    result = _validate_parsed_feed(result, url)

    # Force the feed URL to be the original URL we requested.  This keeps
    # storage stable even when the server redirects the fetch request.
    feed = _parsed_value(result, "feed", None)
    if feed is not None:
        _set_mapping_value(feed, "href", url)
        _set_mapping_value(feed, "id", url)

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


def _retry_delay(_period, error_count):
    """Return the retry delay for a failed feed fetch."""
    failure_count = max(1, int(error_count or 1))
    delay = RSS_RETRY_INITIAL_DELAY * (
        RSS_RETRY_BACKOFF_MULTIPLIER ** (failure_count - 1)
    )
    return min(int(delay), MAX_BACKOFF_TIME)


async def _handle_fetch_error(bot, store, url, period, now, error_count, exc):
    log.warning("Failed to fetch RSS feed %s: %s", url, exc)

    error_count += 1
    retry_delay = _retry_delay(period, error_count)
    next_retry = now + retry_delay

    await _set_retry_state(bot, store, url, error_count, next_retry)
    log.debug(
        "Feed %s backoff set to %s errors, retry at %s",
        url,
        error_count,
        next_retry,
    )
    await asyncio.sleep(retry_delay)


async def _sleep_for_retry(_period, next_retry, now):
    if next_retry > now:
        await asyncio.sleep(next_retry - now)
        return True
    return False


async def _handle_empty_feed(url, period, parsed):
    if not parsed.entries:
        log.debug("Feed %s has no entries", url)
        await asyncio.sleep(period)
        return True
    return False


def _format_duration(seconds: int) -> str:
    """Format a small duration for human-readable RSS status output."""
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts[:3])


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


def _format_feed_list_item(feed_url: str, data: dict, now=None) -> str:
    """Format one RSS feed entry for ``rss list`` output."""
    status = _format_retry_status(data, now=now)
    return (
        f"- {feed_url}\n Title: {data.get('title', feed_url)}\n"
        f" Period: {data.get('period', '?')}s\n"
        f" Rooms: {', '.join(data.get('rooms', []))}\n"
        f"{status}"
    )


def _filter_feeds_for_room(feeds: dict, room: str) -> dict:
    """Return only feeds subscribed to the given room JID."""
    normalized_room = _normalize_room_jid(room)
    return {
        url: data
        for url, data in feeds.items()
        if isinstance(data, dict)
        and any(_normalize_room_jid(item) == normalized_room
                for item in data.get("rooms", []))
    }


def _format_feed_list(feeds: dict, args, bot=None, now=None) -> list[str] | None:
    """Return paginated ``rss list`` output lines, or ``None`` on bad args."""
    items = list(feeds.items())
    page_size = RSS_LIST_PAGE_SIZE
    parsed = _rss_list_page(args, len(items), page_size)

    if parsed is None:
        return None

    page, show_all = parsed
    now = _now() if now is None else int(now)

    if show_all:
        page_items = items
        total = len(items)
        lines = [f" Watched RSS feeds ({total}) - all:"]
    else:
        page_items, page, total_pages, total = paginate_items(
            items,
            page,
            page_size,
        )
        lines = [
            f" Watched RSS feeds ({total}) - Page {page}/{total_pages}:",
        ]

    lines.extend(
        _format_feed_list_item(feed_url, data, now=now)
        for feed_url, data in page_items
    )

    if not show_all and page < total_pages:
        lines.append("")
        lines.append(
            f"Use {_command_prefix(bot)}rss list {page + 1} for the next page."
        )

    return lines


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

            log.debug("[RSS] Added new feed url=%s", url)
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
            "active_tasks": sum(1 for url in room_feeds if url in CHECK_TASKS),
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
