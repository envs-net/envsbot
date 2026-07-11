"""Split module for plugins/rss.py: fetch."""

import asyncio
import html
import hashlib
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse
import aiohttp
from bs4 import BeautifulSoup
from utils.config import config
from core_plugins._core import paginate_items
from utils.http_fetch import fetch_bytes
from utils.url_safety import (
    FetchURLTooLarge,
    UnsafeFetchURL,
    validate_fetch_url_async,
)
from core_plugins.rooms import JOINED_ROOMS
from .store import (
    _apply_retry_state,
    _feed_status_label,
    _format_rss_timestamp,
    _record_feed_check,
)


SIMILARITY_THRESHOLD = float(config.get("rss_similarity_threshold", 0.8) or 0.8)


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


async def get_feeds(store):
    feeds = await store.get_global(RSS_KEY, default={})
    return feeds if isinstance(feeds, dict) else {}


async def save_feeds(store, feeds):
    await store.set_global(RSS_KEY, feeds)


async def _fetch_feed_bytes(url: str) -> tuple[bytes, str, str]:
    """Fetch feed bytes with explicit timeout and redirect safety checks."""
    result = await fetch_bytes(
        url,
        headers=_get_feed_headers(),
        timeout_seconds=RSS_FETCH_TIMEOUT_SECONDS,
        max_redirects=RSS_MAX_REDIRECTS,
        max_bytes=RSS_MAX_READ_BYTES,
        allow_private=ALLOW_PRIVATE_FETCH_URLS,
        validator=validate_fetch_url_async,
        session_factory=aiohttp.ClientSession,
    )
    return result.body, result.url, result.content_type


def _github_feed_hint(url: str) -> str:
    """Return a short GitHub feed hint for common non-feed URLs."""
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return ""

    path_parts = [part for part in parsed.path.split("/") if part]
    if "commits" not in path_parts:
        return ""

    if len(path_parts) >= 2:
        owner = path_parts[0]
        repo = path_parts[1]
        if repo != "commits":
            return (
                " For GitHub commit feeds, try "
                f"https://github.com/{owner}/{repo}/commits/<branch>.atom "
                f"or https://github.com/{owner}/{repo}/commits.atom."
            )

    return (
        " For GitHub commit feeds, use "
        "https://github.com/<owner>/<repo>/commits/<branch>.atom. "
        "The repository name must be part of the URL."
    )


def _format_feed_fetch_error(url: str, exc: Exception) -> str:
    """Format feed fetch/parse errors without exposing tracebacks to users."""
    hint = _github_feed_hint(url)

    if isinstance(exc, aiohttp.ClientResponseError):
        status = exc.status
        message = exc.message or "HTTP error"
        return f"HTTP {status} {message} while fetching feed.{hint}"

    if isinstance(exc, (FetchURLTooLarge, UnsafeFetchURL, ValueError)):
        return f"{exc}{hint}"

    if isinstance(exc, asyncio.TimeoutError):
        return f"Timed out while fetching feed.{hint}"

    if isinstance(exc, aiohttp.ClientError):
        return f"Network error while fetching feed: {exc}.{hint}"

    return f"{exc}{hint}"


def _is_expected_feed_fetch_error(exc: Exception) -> bool:
    """Return True for normal user/input/network feed-add failures."""
    return isinstance(
        exc,
        (
            aiohttp.ClientResponseError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
            FetchURLTooLarge,
            UnsafeFetchURL,
            ValueError,
        ),
    )


def _log_feed_fetch_error(context: str, url: str, exc: Exception) -> None:
    """Log expected feed errors without traceback and unexpected ones with it."""
    if _is_expected_feed_fetch_error(exc):
        log.warning(
            "%s url=%s: %s",
            context,
            url,
            _format_feed_fetch_error(url, exc),
        )
    else:
        log.exception("%s url=%s", context, url)


def _parsed_value(parsed, key, default=None):
    """Return a feedparser result value from mapping or attribute objects."""
    if isinstance(parsed, dict):
        return parsed.get(key, default)
    return getattr(parsed, key, default)


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


async def _update_feed_link(bot, store, url, feed_link):
    return await _set_feed_field(bot, store, url, "link", feed_link)


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


def _format_feed_list_item(feed_url: str, data: dict, now=None) -> str:
    """Format one RSS feed entry for ``rss list`` output."""
    status = _format_retry_status(data, now=now)
    paused_rooms = data.get("paused_rooms") if isinstance(data, dict) else []
    paused_text = f"\n Paused rooms: {', '.join(paused_rooms)}" if paused_rooms else ""
    return (
        f"- {feed_url}\n Title: {data.get('title', feed_url)}\n"
        f" Status: {_feed_status_label(data, now=now)}\n"
        f" Period: {data.get('period', '?')}s\n"
        f" Rooms: {', '.join(data.get('rooms', []))}\n"
        f" Last success: {_format_rss_timestamp(data.get('last_success'))}\n"
        f" Last error: {data.get('last_error') or 'none'}{paused_text}\n"
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

    page, show_all, page_size = parsed
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
