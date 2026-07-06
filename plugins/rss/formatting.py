"""Split module for plugins/rss.py: formatting."""

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


def _build_rss_message(feed_title, entry_title, entry_desc, entry_link):
    if _should_include_description(entry_title, entry_desc):
        out = f"[RSS] ({feed_title}) {entry_title} - {entry_desc}\n"
        out += f"{entry_link}"
        return out
    return f"[RSS] ({feed_title}) {entry_title}\n{entry_link}"


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
