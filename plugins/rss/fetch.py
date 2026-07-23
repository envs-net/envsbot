"""HTTP retrieval and parsing helpers for RSS/Atom feeds."""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import aiohttp
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from utils.config import config
from utils.http_fetch import fetch_bytes
from utils.url_safety import FetchURLTooLarge, UnsafeFetchURL, validate_fetch_url_async

from .config import (
    ALLOW_PRIVATE_FETCH_URLS,
    RSS_FETCH_TIMEOUT_SECONDS,
    RSS_MAX_READ_BYTES,
    RSS_MAX_REDIRECTS,
    RSS_USER_AGENT,
)

try:
    import feedparser
except ImportError:
    feedparser = None

log = logging.getLogger(__name__)
SIMILARITY_THRESHOLD = float(config.get("rss_similarity_threshold", 0.8) or 0.8)

def _mapping_value(mapping, key, default=None):
    if isinstance(mapping, dict):
        return mapping.get(key, default)
    return getattr(mapping, key, default)

def _set_mapping_value(mapping, key, value) -> None:
    if isinstance(mapping, dict):
        mapping[key] = value
    else:
        setattr(mapping, key, value)
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
_VOLATILE_FEED_LINK_QUERY_KEYS = frozenset({
    "after",
    "before",
    "cursor",
    "max_id",
    "min_id",
    "newer_than",
    "older_than",
    "since_id",
    "until_id",
})

_HTML_FEED_LINK_MEDIA_TYPES = frozenset({
    "",
    "application/xhtml+xml",
    "text/html",
})

def _clean_feed_display_link(candidate: str, feed_url: str) -> str:
    """Return a stable HTTP(S) feed homepage/display link.

    Some feed generators expose pagination URLs such as ``?max_id=...`` as
    their current feed link. Those cursors are volatile and must not leak into
    ``$feed_link`` or the persisted feed metadata. Permanent query parameters
    are kept because they may identify a filtered feed or public page.
    """
    value = str(candidate or "").strip()
    if not value:
        return ""

    try:
        absolute = urljoin(str(feed_url or ""), value)
        parsed = urlparse(absolute)
    except (TypeError, ValueError):
        return ""

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""

    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in _VOLATILE_FEED_LINK_QUERY_KEYS
        ],
        doseq=True,
    )
    return urlunparse(parsed._replace(query=query))

def _extract_feed_link(feed, feed_url: str) -> str:
    """Choose a stable public page link from parsed feed metadata.

    HTML ``rel=alternate`` links are preferred over self/next RSS links.  This
    matters for ActivityPub feeds where feedparser may otherwise expose a
    cursor-bearing ``rel=next`` URL as ``feed.link``.
    """
    links = _mapping_value(feed, "links", []) or []
    preferred = []

    if isinstance(links, (list, tuple)):
        for link in links:
            href = _mapping_value(link, "href", "")
            rel = str(_mapping_value(link, "rel", "") or "").strip().lower()
            media_type = str(
                _mapping_value(link, "type", "") or ""
            ).split(";", 1)[0].strip().lower()

            if not href or rel not in {"", "alternate"}:
                continue
            if media_type not in _HTML_FEED_LINK_MEDIA_TYPES:
                continue

            priority = 0 if rel == "alternate" else 1
            preferred.append((priority, href))

    preferred.sort(key=lambda item: item[0])
    candidates = [href for _, href in preferred]
    candidates.extend([_mapping_value(feed, "link", ""), feed_url])

    for candidate in candidates:
        cleaned = _clean_feed_display_link(candidate, feed_url)
        if cleaned:
            return cleaned
    return ""

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
        feed_link = _extract_feed_link(feed, url)
        if feed_link:
            _set_mapping_value(feed, "link", feed_link)

    return result
def _entry_is_new(last_id, entry):
    entry_id = _get_entry_id(entry)
    if not entry_id:
        return False, None
    if entry_id == last_id:
        return False, entry_id
    return True, entry_id
