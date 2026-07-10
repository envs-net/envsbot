"""Split module for plugins/rss.py: formatting."""

from string import Template
import logging

from utils.config import config

from .config import (
    DEFAULT_RSS_TEMPLATE,
    RSS_TEMPLATE_MAX_LENGTH,
    RSS_TEMPLATE_VARIABLES,
)
from .fetch import (
    _extract_entry_link,
    _normalize_url,
    _post_entry_to_rooms,
    _resolve_relative_url,
    _set_feed_field,
    get_feeds,
    save_feeds,
    _should_include_description,
    entry_get,
    html_to_text_with_links,
)
from .store import get_effective_template, _feed_active_rooms, _record_feed_post


log = logging.getLogger(__name__)


def _template_command_prefix(bot=None) -> str:
    return str(getattr(bot, "prefix", None) or config.get("prefix", ",") or ",")



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


def _rss_template_usage(bot=None) -> str:
    """Return RSS template command usage."""
    prefix = _template_command_prefix(bot)
    return (
        f"Usage: {prefix}rss template [show] [room_jid] [feedurl]\n"
        f"       {prefix}rss template set [room_jid] [feedurl] <template>\n"
        f"       {prefix}rss template unset [room_jid] [feedurl]\n"
        f"       {prefix}rss template test [room_jid] [feedurl] [template]"
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
    """Render a validated RSS template with entry context."""
    return Template(template).substitute(context).strip()


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


async def _save_last_id_for_template_post(bot, store, url, entry_id):
    return await _set_feed_field(bot, store, url, "last_id", entry_id)


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
    """Post one RSS entry using feed, room, or default templates."""
    posted = False
    for room in rooms:
        template = await get_effective_template(store, room, url)
        msg = _build_rss_message_from_context(context, template)
        if await _post_entry_to_rooms(bot, [room], msg):
            posted = True
    return posted


async def _post_new_entries(bot, store, url, feed_title,
                            feed_link, rooms, new_entries, feed: dict | None = None):
    active_rooms = _feed_active_rooms(feed or {"rooms": rooms})
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

        posted = await _post_rss_entry_to_rooms(bot, store, active_rooms, url, context)

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
