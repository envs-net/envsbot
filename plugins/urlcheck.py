"""
URL Check plugin.

This plugin allows moderators to enable or disable automatic URL title
checking in a groupchat room. When enabled, the bot will watch for URLs
in messages and output the title and filetype for HTML pages, or YouTube
video info for YouTube links.

It will also add an XEP-0511 metadata attachment, if the message sending
the URL does not already provide Link metadata. If the sending message
does provide additional Link information, the XEP-0511 attachment will be
omitted to avoid redundancy, but the bot will still reply with the URL or
YouTube info in the message text.

Output of the same URL is temporary disabled for 2 minutes, after first
fetch, to avoid spam if the same URL is posted multiple times in a short
period.

Use the following commands to turn "urlcheck" on/off or show its status in
a room (use MUC PM):
    {prefix}urlcheck on
    {prefix}urlcheck off
    {prefix}urlcheck status

"""
import re
import inspect
import logging
import html

import isodate

from urllib.parse import urlparse, urlunparse
from datetime import datetime
from functools import partial

from utils.command import command, Role
from utils.config import config
from utils.http_fetch import fetch_preview, fetch_json, passthrough_validator
from utils.urlcheck_extraction import extract_urls_from_message_text
from utils.url_safety import UnsafeFetchURL
from bot.room_state import JOINED_ROOMS
from core_plugins._core import (
    _get_enabled_rooms,
    _is_enabled_for_room,
    handle_room_toggle_command,
)

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "urlcheck",
    "version": "0.4.0",
    "description": "URL title and YouTube info fetcher for groupchats",
    "category": "info",
    "requires": ["rooms", "_core"],
}

URLCHECK_KEY = "URLCHECK"
# Robust YouTube video ID extraction: supports many URL forms
#  youtu.be/VIDEO_ID
# /watch?...v=VIDEOID, /embed/VIDEOID, /v/VIDEOID, /shorts/VIDEOID
YOUTUBE_RE = re.compile(
    r"""(?x)
    (?: # Match any of the following forms:
        (?:https?://)?(?:www\.)?youtu\.be/([A-Za-z0-9_-]{11})
      | (?:https?://)?(?:www\.)?youtube\.com/
        (?:
            (?:watch\?(?:.*&)?v=|embed/|v/|shorts/))
        ([A-Za-z0-9_-]{11})
    )
    """,
    re.I,
)
# Dict of URLs which have been requested with timestamp to avoid fetching
# the same URL multiple times in a short period
# format: _url_timestamp[room][url] = timestamp
_url_timestamps = {}
# Operator-tunable fetch and suppression settings.
URLCHECK_WAIT_SECONDS = int(config.get("urlcheck_wait_seconds", 120) or 120)
URLCHECK_FETCH_TIMEOUT_SECONDS = float(
    config.get("urlcheck_fetch_timeout_seconds", config.get("http_timeout_seconds", 8)) or 8
)
URLCHECK_MAX_REDIRECTS = max(1, int(config.get("urlcheck_max_redirects", 5) or 5))
URLCHECK_MAX_READ_BYTES = max(
    1024,
    int(config.get("urlcheck_max_read_bytes", 65536) or 65536),
)
URLCHECK_USER_AGENT = str(
    config.get("urlcheck_user_agent")
    or config.get("http_user_agent")
    or "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)"
)
ALLOW_PRIVATE_FETCH_URLS = bool(config.get("allow_private_fetch_urls", False))

# seconds to wait until next URL output
_wait_secs_url = URLCHECK_WAIT_SECONDS


async def get_urlcheck_store(bot):
    return bot.db.users.plugin("urlcheck")


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int]:
    """Return URLCheck counters for diagnostics."""
    enabled = await _get_enabled_rooms(
        bot, URLCHECK_KEY, "urlcheck", [room_jid] if room_jid else ()
    )
    if room_jid:
        target = str(room_jid or "").split("/", 1)[0].strip().lower()
        room_enabled = any(str(room).split("/", 1)[0].strip().lower() == target for room in enabled)
        return {
            "enabled_rooms": int(room_enabled),
            "cached_urls": len(_url_timestamps.get(room_jid, {})),
        }
    return {
        "enabled_rooms": len(enabled),
        "cached_urls": sum(len(urls) for urls in _url_timestamps.values()),
    }


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return URLCheck diagnostics."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    return [
        f"✅ URLCheck{scope}: enabled_rooms={state.get('enabled_rooms', 0)}, cached_urls={state.get('cached_urls', 0)}, max_redirects={URLCHECK_MAX_REDIRECTS}"
    ]

@command(
    "urlcheck",
    role=Role.USER,
    short="Enable, disable or show automatic URL checks in a room.",
    usage="{prefix}urlcheck <on|off|status>",
    examples=[
        "{prefix}urlcheck status",
        "{prefix}rooms enable urlcheck",
    ],
    category="utility",
    context="room or MUC PM",
)
async def urlcheck_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Enable, disable or show URL checking status for this room.

    Permission handling is delegated to utils.plugin_helper so on/off/status
    behaves consistently across all room-scoped plugins.

    Usage:
        {prefix}urlcheck on - Enable URL checking in this room
        {prefix}urlcheck off - Disable URL checking in this room
        {prefix}urlcheck status - Show if URL checking is enabled in this room

    """
    handled = await handle_room_toggle_command(
        bot,
        msg,
        is_room,
        args,
        store_getter=get_urlcheck_store,
        key=URLCHECK_KEY,
        label="URL checking",
        plugin="urlcheck",
        storage="dict",
        log_prefix="[URLCHECK]",
    )
    if handled:
        return

    bot.reply(msg, f"Usage: {bot.prefix}urlcheck <on|off|status>")


async def on_groupchat_message(bot, msg):
    room = msg["from"].bare
    nick = msg.get("mucnick")
    body = msg.get("body", "").strip()

    # ==== Prevent processing own messages ====
    try:
        bot_nick = JOINED_ROOMS[room]["nick"]
        if bot_nick == nick or bot_nick == msg["from"].resource:
            return
    except KeyError:
        return

    # But process URLs from the bot (e.g., xkcd) anyway!
    if body.startswith("[URL]") or body.startswith("[YOUTUBE]"):
        return

    # Only process URLs if the room is a joined room
    if room not in JOINED_ROOMS:
        return

    if not await _is_enabled_for_room(bot, URLCHECK_KEY, "urlcheck", room):
        return

    text = msg.get("body", "")
    thread_id = msg.get("thread") or msg.get("id")
    has_xep_0511 = msg.xml.find("{urn:xmpp:sn:0}x") is not None

    urls = _extract_urls_from_message_text(text)
    if not urls:
        return

    for url in urls:
        await _handle_urlcheck_url(
            bot=bot,
            msg=msg,
            room=room,
            url=url,
            thread_id=thread_id,
            has_xep_0511=has_xep_0511,
        )


def _extract_urls_from_message_text(text):
    """Backward-compatible wrapper around split extraction helpers."""
    return extract_urls_from_message_text(text)


async def _handle_urlcheck_url(bot, msg, room, url, thread_id, has_xep_0511):
    now = datetime.now().timestamp()

    if room not in _url_timestamps:
        _url_timestamps[room] = {}

    for u in dict(_url_timestamps[room]):
        if _url_timestamps[room][u] < now - _wait_secs_url:
            del _url_timestamps[room][u]

    if url in _url_timestamps[room]:
        log.info(f"[URLCHECK] 🟡 Fetching '{url}' temporary disabled")
        _url_timestamps[room][url] = now
        return

    _url_timestamps[room][url] = now

    try:
        fetch_result = fetch_url_title(url, 5)
        if inspect.isawaitable(fetch_result):
            fetch_result = await fetch_result
        final_url, status, ctype, title, content_size, mdesc = fetch_result

        st = f"(Status: {status})" if status in [200, 403] else ""

        if is_youtube_url(final_url):
            await _send_youtube_urlcheck_reply(
                bot=bot,
                msg=msg,
                final_url=final_url,
                title=title,
                thread_id=thread_id,
                has_xep_0511=has_xep_0511,
            )
            return

        if ctype:
            is_ok = "text/html" in ctype
        else:
            is_ok = False

        if is_ok and title:
            await _send_html_urlcheck_reply(
                bot=bot,
                msg=msg,
                final_url=final_url,
                status=status,
                ctype=ctype,
                title=title,
                content_size=content_size,
                mdesc=mdesc,
                st=st,
                thread_id=thread_id,
                has_xep_0511=has_xep_0511,
            )
        elif ctype:
            return

    except UnsafeFetchURL as e:
        log.info("[URLCHECK] Blocked unsafe URL %s: %s", url, e)
    except Exception as e:
        if str(e) == "Too many redirects":
            bot.reply(
                msg,
                f"🟡️ URL not fetched: too many redirects for {url}",
                mention=False, thread=True, ephemeral=False
            )
            log.info(f"[URLCHECK] Too many redirects for URL {url}")
        else:
            log.warning(f"[URLCHECK] Failed to fetch URL {url}: {e}")


async def _send_youtube_urlcheck_reply(
    bot, msg, final_url, title, thread_id, has_xep_0511
):
    yt_info, title, uploader, length_str, views = (
            await fetch_youtube_info(final_url)
    )

    if not yt_info:
        return

    message = bot.make_message(
        mto=msg["from"].bare,
        mbody=html.unescape(yt_info),
        mtype="groupchat"
    )

    if thread_id:
        try:
            message["thread"] = thread_id
        except Exception as exc:
            log.debug("[URLCHECK] Could not attach thread id to reply: %s", exc)

    if not has_xep_0511 and not has_xep_0392_link_metadata(msg):
        try:
            if title is not None:
                message["link_metadata"]["title"] = html.unescape(title)
            message["link_metadata"]["about"] = (
                f"Uploader: {uploader} - Length: {length_str}"
                f" - Views: {views}"
            )
            if yt_info is not None:
                message["link_metadata"]["description"] = (
                        html.unescape(yt_info)
                )
            message["link_metadata"]["url"] = final_url
        except Exception as e:
            log.warning(
                "[URLCHECK] Failed to set link metadata for YouTube info: "
                f"{e}"
            )

    if has_xep_0511 or has_xep_0392_link_metadata(msg):
        for x in list(message.xml.findall("{urn:xmpp:sn:0}x")):
            message.xml.remove(x)

    message.send()


async def _send_html_urlcheck_reply(
    bot,
    msg,
    final_url,
    status,
    ctype,
    title,
    content_size,
    mdesc,
    st,
    thread_id,
    has_xep_0511,
):
    _body = f"[URL] {html.unescape(title)} {st} - ({final_url})"

    if mdesc and isinstance(mdesc, str):
        desc_lines = [line.strip() for line in mdesc.splitlines()
                      if line.strip()]
        short_desc = "\n".join(desc_lines[:2])
        _body += f"\nDesc: '{html.unescape(short_desc)}'"

    message = bot.make_message(
        mto=msg["from"].bare,
        mbody=_body.strip(),
        mtype="groupchat"
    )

    if thread_id:
        try:
            message["thread"] = thread_id
        except Exception as exc:
            log.debug("[URLCHECK] Could not attach thread id to HTML reply: %s", exc)

    if not has_xep_0511 and not has_xep_0392_link_metadata(msg):
        try:
            if title is not None:
                message["link_metadata"]["title"] = html.unescape(title)
            message["link_metadata"]["url"] = final_url
            message["link_metadata"]["about"] = (
                f"Status: {status} - Content-Type: {ctype}"
                f" - Size: {content_size}"
            )
            if mdesc is not None:
                message["link_metadata"]["description"] = (
                    html.unescape(mdesc) or ""
                )
        except Exception as e:
            log.warning(
                "[URLCHECK] Failed to set link metadata for "
                f"URL '{final_url}': {e}"
            )

    if has_xep_0511 or has_xep_0392_link_metadata(msg):
        for x in list(message.xml.findall("{urn:xmpp:sn:0}x")):
            message.xml.remove(x)

    message.send()


def strip_html_tags(text):
    return re.sub(r"<[^>]+>", "", text or "")


def is_youtube_url(url):
    return "youtube.com/watch" in url or "youtu.be/" in url


def has_xep_0392_link_metadata(msg):
    # Checks for <Descriptionx#
    # mlns="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    # or <rdf:Description ...>
    return (
        msg.xml.find(
            './/{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description'
        ) is not None
    )


def _html_metadata_preview_complete(body: bytes) -> bool:
    """Return True once a partial HTML body contains enough metadata."""
    lower = body.lower()
    if b"</head" in lower:
        return True
    if b"</title" not in lower:
        return False
    has_description_hint = (
        b"name=\"description\"" in lower
        or b"name='description'" in lower
        or b"property=\"og:description\"" in lower
        or b"property='og:description'" in lower
    )
    return has_description_hint


async def fetch_url_title(url, max_redirects=None):
    """
    Fetch URL metadata without reading the complete response body.

    Many modern pages, especially GitHub release pages, are far larger than
    the URLCheck title limit while still placing the title in the first few
    kilobytes.  Use a streaming preview fetch so large HTML pages can still be
    summarized without raising ``FetchURLTooLarge``.
    """
    parsed_orig = urlparse(url)
    orig_fragment = parsed_orig.fragment
    if max_redirects is None:
        max_redirects = URLCHECK_MAX_REDIRECTS

    result = await fetch_preview(
        url,
        headers={
            "User-Agent": URLCHECK_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
        timeout_seconds=URLCHECK_FETCH_TIMEOUT_SECONDS,
        max_redirects=max_redirects,
        max_bytes=URLCHECK_MAX_READ_BYTES,
        allow_private=ALLOW_PRIVATE_FETCH_URLS,
        raise_for_status=False,
        stop_when=_html_metadata_preview_complete,
    )

    final_url = result.url
    if orig_fragment:
        parsed_final = urlparse(final_url)
        final_url = urlunparse(parsed_final._replace(fragment=orig_fragment))

    ctype = result.content_type
    content_size = result.content_length if result.content_length is not None else len(result.body)
    if "text/html" in ctype:
        buffer = result.body.decode("utf-8", errors="replace")
        title_found, desc_found = extract_html_title_desc(buffer)
        return (
            final_url, result.status,
            ctype, title_found, content_size, desc_found
        )

    return (
        final_url, result.status, ctype,
        None, content_size, None
    )


def extract_html_title_desc(html, is_wikipedia=False):
    title = None
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        title = m.group(1).strip()
    desc = None

    # Strictly only match a single <meta ...> tag PER LINE:
    meta_tag_re = re.compile(r'<meta\b([^>]*)>', re.I)
    for match in meta_tag_re.finditer(html):
        attrs = match.group(1)
        # Extract attributes as key-value pairs
        name = re.search(r'name=["\']description["\']', attrs, re.I)
        content = re.search(r'content=["\']([^"\']*)["\']', attrs, re.I)
        if name and content:
            desc = content.group(1).strip()
            break

    return title, desc


async def _create_length_str(duration):
    try:
        td = isodate.parse_duration(duration)
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            length_str = f"{hours}h"
            if minutes:
                length_str += f"{minutes}m"
            if seconds:
                length_str += f"{seconds}s"
        elif minutes:
            length_str = f"{minutes}m"
            if seconds:
                length_str += f"{seconds}s"
        else:
            length_str = f"{seconds}s"
    except Exception:
        length_str = duration
    return length_str


async def fetch_youtube_info(url):
    api_key = config.get("youtube_api_key")
    if not api_key:
        return None
    m = YOUTUBE_RE.search(url)
    if not m:
        return None
    # Extract video_id from the first non-None group
    video_id = m.group(1) or m.group(2)
    api_url = (
        f"https://www.googleapis.com/youtube/v3/videos"
        f"?id={video_id}&part=snippet,statistics,"
        f"contentDetails&key={api_key}"
    )
    result = await fetch_json(
        api_url,
        timeout_seconds=URLCHECK_FETCH_TIMEOUT_SECONDS,
        max_bytes=262144,
        validator=passthrough_validator,
        raise_for_status=False,
    )
    if result.status != 200 or not isinstance(result.data, dict):
        return None
    items = result.data.get("items", [])
    if not items:
        return None
    info = items[0]
    snippet = info["snippet"]
    stats = info["statistics"]
    content_details = info.get("contentDetails", {})
    title = snippet.get("title", "")
    uploader = snippet.get("channelTitle", "")
    views = stats.get("viewCount", "0")
    duration = content_details.get("duration", "")
    upload_date = snippet.get("publishedAt", "")
    # Format duration as 1h23m46s, 23m46s, or 46s
    length_str = ""
    if duration:
        length_str = await _create_length_str(duration)
    # Format upload date as "DD Mon YYYY" if possible
    if upload_date:
        try:
            upload_date = datetime.strptime(
                upload_date[:10], "%Y-%m-%d"
            ).strftime("%d %b %Y")
        except Exception:
            upload_date = ""
    return (
        f'[YOUTUBE] "{title}" uploaded by {uploader} '
        f'({length_str}) - Views: {views}'
        + (f' - {upload_date}' if upload_date else ''),
        title, uploader, length_str, views
    )


async def on_load(bot):
    bot.bot_plugins.register_event(
        "urlcheck",
        "groupchat_message",
        partial(on_groupchat_message, bot))
