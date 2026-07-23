"""RSS message, template, list, and status formatting."""

from __future__ import annotations

import inspect
import logging
from string import Template

from slixmpp import JID

from utils.config import config
from utils.formatting import page_size_for, parse_page_args
from bot.room_state import JOINED_ROOMS
from core_plugins._core import paginate_items

from .config import DEFAULT_RSS_TEMPLATE, RSS_LIST_PAGE_SIZE, RSS_TEMPLATE_MAX_LENGTH, RSS_TEMPLATE_VARIABLES
from .fetch import (
    _extract_entry_link,
    _normalize_url,
    _resolve_relative_url,
    _should_include_description,
    entry_get,
    html_to_text_with_links,
)
from .store import (
    _feed_active_rooms,
    _feed_status_label,
    _format_rss_timestamp,
    _normalize_room_jid,
    _now,
    _record_feed_post,
    get_effective_template,
    get_feeds,
    save_feeds,
)

log = logging.getLogger(__name__)

_SAMPLE_TEMPLATE_CONTEXT = {
    "feed_title": "Example Feed",
    "title": "Example entry",
    "summary": "Short example summary",
    "summary_line": " - Short example summary",
    "link": "https://example.org/article",
    "feed_url": "https://example.org/feed.xml",
    "feed_link": "https://example.org/",
    "id": "https://example.org/article",
    "date": "2026-07-07 12:00",
}
def _template_command_prefix(bot=None) -> str:
    return str(getattr(bot, "prefix", None) or config.get("prefix", ",") or ",")
def _rss_template_usage(bot=None) -> str:
    """Return RSS template command usage for each supported destination."""
    prefix = _template_command_prefix(bot)
    return (
        "Usage: RSS templates (personal 1:1 chat)\n"
        f"  {prefix}rss template [show]\n"
        f"  {prefix}rss template set <template>\n"
        f"  {prefix}rss template set <feedurl> <template>\n"
        f"  {prefix}rss template unset [feedurl]\n"
        f"  {prefix}rss template test [feedurl] [template]\n"
        "Room or MUC PM (current room is inferred):\n"
        f"  {prefix}rss template [show|set|unset|test] [feedurl] [template]\n"
        "Private admin chat for a room:\n"
        f"  {prefix}rss template <show|set|unset|test> <room_jid> "
        "[feedurl] [template]\n"
        "Global default (moderator+):\n"
        f"  {prefix}rss template <show|set|unset|test> default [template]\n"
        "Optional: write 'direct' before or after feedurl in a 1:1 chat. "
        "Use \\n for line breaks in a template."
    )
def _rss_template_variables_text() -> str:
    """Return the supported template variables as a readable list."""
    names = ", ".join(f"${name}" for name in sorted(RSS_TEMPLATE_VARIABLES))
    return f"Variables: {names}. Use $$ for a literal dollar sign."
def _normalize_rss_template_input(template: str) -> str:
    """Normalize one-line command input into a stored template string."""
    return str(template or "").strip().replace("\\n", "\n")
def _validate_rss_template(template: str) -> str | None:
    """Return an error message for an invalid RSS template, otherwise None."""
    if not isinstance(template, str) or not template.strip():
        return "Template must not be empty."
    if len(template) > RSS_TEMPLATE_MAX_LENGTH:
        return f"Template is too long (max {RSS_TEMPLATE_MAX_LENGTH} characters)."

    try:
        Template(template).substitute(_SAMPLE_TEMPLATE_CONTEXT)
    except KeyError as exc:
        missing = str(exc).strip("'")
        return f"Unknown template variable: ${missing}."
    except ValueError as exc:
        return f"Invalid template syntax: {exc}."

    return None
def _entry_date(entry) -> str:
    """Return a readable date value from a feed entry, if one exists."""
    for key in ("published", "updated", "created", "date"):
        value = entry_get(entry, key, "")
        if value:
            return str(value)
    return ""
def _build_rss_template_context(
    *,
    feed_title: str,
    entry_title: str,
    entry_desc: str,
    entry_link: str,
    feed_url: str = "",
    feed_link: str = "",
    entry_id: str = "",
    entry_date: str = "",
) -> dict[str, str]:
    """Build the variables available to RSS room templates."""
    include_summary = _should_include_description(entry_title, entry_desc)
    summary = entry_desc if include_summary else ""
    summary_line = f" - {entry_desc}" if include_summary else ""
    return {
        "feed_title": str(feed_title or feed_url or "RSS"),
        "title": str(entry_title or "No title"),
        "summary": str(summary),
        "summary_line": str(summary_line),
        "link": str(entry_link or ""),
        "feed_url": str(feed_url or ""),
        "feed_link": str(feed_link or ""),
        "id": str(entry_id or ""),
        "date": str(entry_date or ""),
    }
def _render_rss_template(template: str, context: dict[str, str]) -> str:
    """Render a validated RSS template while preserving useful spacing.

    Leading and ordinary trailing whitespace is still normalized, but an
    explicitly configured trailing line break is retained. More than two
    trailing line breaks are capped at two so a template can create one blank
    separator line without producing an excessive vertical gap.
    """
    rendered = Template(template).substitute(context)
    trailing = rendered[len(rendered.rstrip("\r\n")) :]
    body = rendered.strip()
    if not body or not trailing:
        return body

    line_breaks = trailing.count("\n") + trailing.count("\r")
    if "\r\n" in trailing:
        line_breaks -= trailing.count("\r\n")
    return body + "\n" * min(2, max(1, line_breaks))
def _build_rss_message_from_context(
    context: dict[str, str],
    template: str | None = None,
) -> str:
    """Build an RSS post body from a context and optional room template."""
    chosen = template or DEFAULT_RSS_TEMPLATE
    try:
        return _render_rss_template(chosen, context)
    except (KeyError, ValueError):
        log.warning(
            "[RSS] Invalid stored template; falling back to default",
            exc_info=True,
        )
        return _render_rss_template(DEFAULT_RSS_TEMPLATE, context)
def _build_rss_message(feed_title, entry_title, entry_desc, entry_link):
    context = _build_rss_template_context(
        feed_title=feed_title,
        entry_title=entry_title,
        entry_desc=entry_desc,
        entry_link=entry_link,
    )
    return _build_rss_message_from_context(context)
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
async def _post_rss_entry_to_rooms(bot, store, rooms, url, context):
    """Post one RSS entry to room and direct subscribers."""
    posted = False
    for room in rooms:
        template = await get_effective_template(store, room, url)
        msg = _build_rss_message_from_context(context, template)
        if await _post_entry_to_rooms(bot, [room], msg):
            posted = True
    return posted
async def _post_new_entries(bot, store, url, feed_title,
                            feed_link, rooms, new_entries, feed: dict | None = None):
    """Post entries using the freshest persisted destination state.

    RSS workers keep a local feed snapshot while fetching. Direct subscriptions
    and room destinations may change during that network request, so reloading
    before every entry avoids skipping a newly added 1:1 subscriber for an
    entire polling interval.
    """
    for entry, entry_id in reversed(new_entries):
        current_feeds = await get_feeds(store)
        current_feed = current_feeds.get(url)
        if not isinstance(current_feed, dict):
            log.warning("Feed %s was deleted before posting", url)
            break
        active_rooms = _feed_active_rooms(current_feed)
        entry_link = _normalize_url(
            _resolve_relative_url(feed_link, _extract_entry_link(entry))
        )
        entry_title = html_to_text_with_links(
            entry_get(entry, "title", "No title")
        )
        entry_desc = html_to_text_with_links(
            entry_get(entry, "description", "")
        )
        context = _build_rss_template_context(
            feed_title=feed_title,
            entry_title=entry_title,
            entry_desc=entry_desc,
            entry_link=entry_link,
            feed_url=url,
            feed_link=feed_link,
            entry_id=entry_id,
            entry_date=_entry_date(entry),
        )

        posted = await _post_rss_entry_to_rooms(
            bot, store, active_rooms, url, context
        )
        direct_users = sorted(
            current_feed.get("users", {})
            if isinstance(current_feed.get("users"), dict)
            else {}
        )
        direct_delivered = 0
        direct_attempted = 0
        for direct_user in direct_users:
            normalized_user = _normalize_direct_user_jid(direct_user)
            if not normalized_user:
                log.error(
                    "[RSS] Ignoring invalid stored direct subscriber JID: %r",
                    direct_user,
                )
                continue
            try:
                template = await get_effective_template(
                    store,
                    normalized_user,
                    url,
                )
            except Exception:
                log.exception(
                    "[RSS] Failed to load direct template for %s; using default",
                    normalized_user,
                )
                template = None
            direct_msg = _build_rss_message_from_context(context, template)
            delivered, attempted = await _post_entry_to_users(
                bot,
                [normalized_user],
                direct_msg,
            )
            direct_delivered += delivered
            direct_attempted += attempted
        posted = direct_delivered > 0 or posted

        if direct_attempted and direct_delivered < direct_attempted:
            log.warning(
                "[RSS] Direct delivery incomplete for %s entry=%s "
                "delivered=%s/%s; retaining last_id for retry",
                url,
                entry_id,
                direct_delivered,
                direct_attempted,
            )
            break

        def mutator(feed_data):
            changed = _set_last_id_in_feed(feed_data, entry_id)
            if posted:
                changed = _record_feed_post(feed_data, now=_feed_now(), posted=1) or changed
            return changed

        if not await _update_feed_for_post(bot, store, url, mutator):
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
def _set_last_id_in_feed(feed_data: dict, entry_id: str) -> bool:
    if feed_data.get("last_id") == entry_id:
        return False
    feed_data["last_id"] = entry_id
    return True
def _feed_now() -> int:
    import time
    return int(time.time())
async def _update_feed_for_post(bot, store, url: str, mutator):
    feeds = await get_feeds(store)
    feed = feeds.get(url)
    if feed is None:
        return False
    changed = mutator(feed)
    if changed:
        await save_feeds(store, feeds)
    return True
def _rss_list_page(args, total: int, page_size: int):
    """Parse RSS list paging arguments.

    Returns ``(page, show_all, page_size)`` for valid input, or ``None`` for
    invalid arguments. The ``args`` list includes the ``list``/``health``
    subcommand itself.
    """
    if len(args) > 2:
        return None

    if len(args) == 1:
        request = parse_page_args([])
    else:
        value = str(args[1]).strip().lower()
        if value not in {"all", "last"}:
            try:
                if int(value) <= 0:
                    return None
            except ValueError:
                return None
        request = parse_page_args([args[1]])

    effective_page_size = page_size_for(page_size, request)
    if request.all:
        return 1, True, effective_page_size

    total_pages = max(1, (total + effective_page_size - 1) // effective_page_size)
    page = total_pages if request.page == -1 else max(1, request.page)
    return page, False, effective_page_size
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

def _normalize_direct_user_jid(value) -> str | None:
    """Return a valid bare user JID for a direct RSS subscriber."""
    try:
        jid = JID(str(value or "").strip())
    except Exception:
        return None
    if not jid.user or not jid.domain:
        return None
    return str(jid.bare).lower()


async def _send_direct_rss_message(bot, user_jid: str, body: str) -> bool:
    """Send one direct RSS message and report whether sending succeeded."""
    try:
        message = bot.make_message(
            mto=user_jid,
            mbody=body,
            mtype="chat",
        )
        safe_send = getattr(bot, "_safe_send_message", None)
        if callable(safe_send):
            result = safe_send(message)
            if inspect.isawaitable(result):
                result = await result
            return result is not False

        result = message.send()
        if inspect.isawaitable(result):
            await result
        return True
    except Exception:
        log.exception("[RSS] Failed direct delivery to %s", user_jid)
        return False


async def _post_entry_to_users(bot, users, msg) -> tuple[int, int]:
    """Post one RSS entry to bare-JID direct subscribers.

    Return ``(delivered, attempted)`` so the polling loop can retain the
    previous entry cursor when at least one subscriber did not receive the
    stanza.  This provides at-least-once retry semantics instead of silently
    losing an entry after a transport failure.
    """
    delivered = 0
    attempted = 0
    for raw_user_jid in users:
        user_jid = _normalize_direct_user_jid(raw_user_jid)
        if not user_jid:
            log.error(
                "[RSS] Skipping invalid direct subscriber JID: %r",
                raw_user_jid,
            )
            continue
        attempted += 1
        if await _send_direct_rss_message(bot, user_jid, msg):
            delivered += 1
            log.debug("[RSS] Direct delivery accepted for %s", user_jid)
    return delivered, attempted

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
            f"Use {_template_command_prefix(bot)}rss list {page + 1} for the next page."
        )

    return lines


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
