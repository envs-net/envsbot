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
import aiohttp
import logging
import html

import isodate

from urllib.parse import urlparse, urlunparse, urljoin
from datetime import datetime
from functools import partial

from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS
from plugins._core import handle_room_toggle_command

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "urlcheck",
    "version": "0.2.4",
    "description": "URL title and YouTube info fetcher for groupchats",
    "category": "info",
    "reqires": ["rooms", "_core"],
}

URLCHECK_KEY = "URLCHECK"
URL_RE = re.compile(r"https?://[^\s<>\"]+", re.I)
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
# formant _url_timestamp[room][url] = timestamp
_url_timestamps = {}
# seconds to wait until next URL output
_wait_secs_url = 120


async def get_urlcheck_store(bot):
    return bot.db.users.plugin("urlcheck")


@command("urlcheck", role=Role.USER)
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

    store = await get_urlcheck_store(bot)
    enabled_rooms = await store.get_global(URLCHECK_KEY, default={})
    if room not in enabled_rooms:
        return


    text = msg.get("body", "")
    thread_id = msg.get("thread") or msg.get("id")

    # Only match URLs in lines that do not start with ">"
    # and ignore lines between the first ``` and the next ```,
    # matching anywhere in the line
    lines = []
    in_code_block = False
    codeblock_started = False
    for line in text.splitlines():
        if not codeblock_started and "```" in line:
            in_code_block = True
            codeblock_started = True
            continue  # skip the line with opening ```
        if in_code_block and "```" in line:
            in_code_block = False
            continue  # skip the line with closing ```
        if in_code_block:
            continue  # skip lines inside code block
        if not line.lstrip().startswith(">"):
            lines.append(line)

    urls = []
    for line in lines:
        urls.extend(URL_RE.findall(line))
    if not urls:
        return

    has_xep_0511 = msg.xml.find("{urn:xmpp:ssn}x") is not None

    for url in urls:
        # Check if room is in _url_timestamps, if not add it
        now = datetime.now().timestamp()
        if room not in _url_timestamps:
            _url_timestamps[room] = {}
        # delete all expired URLs
        for u in dict(_url_timestamps[room]):
            if _url_timestamps[room][u] < now - _wait_secs_url:
                del _url_timestamps[room][u]
        # if URL in _url_timestamps[room], skip it
        # else add it to _url_timestamps[room] with current timestamp
        if url in _url_timestamps[room]:
            log.info(f"[URLCHECK] 🟡 Fetching '{url}' temporary disabled")
            continue
        _url_timestamps[room][url] = now

        try:
            # handle up to 3 redirects manually
            final_url, status, ctype, title, content_size, mdesc = (
                await fetch_url_title(url, max_redirects=3)
            )

            st = f"(Status: {status})" if status in [200, 403] else ""
            if is_youtube_url(final_url):
                yt_info, title, uploader, length_str, views = (
                    await fetch_youtube_info(final_url)
                )
                if yt_info:
                    message = bot.make_message(
                        mto=msg["from"].bare,
                        mbody=html.unescape(yt_info),
                        mtype="groupchat"
                    )
                    if thread_id:
                        try:
                            message["thread"] = thread_id
                        except Exception:
                            pass
                    # Only attach XEP-0511 if not already present
                    # in the original message
                    if (not has_xep_0511 and
                            not has_xep_0392_link_metadata(msg)):
                        try:
                            if title is not None:
                                message["link_metadata"]["title"] = (
                                    html.unescape(title)
                                )
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
                                "[URLCHECK] Failed to set link metadata"
                                f" for YouTube info: {e}"
                            )
                    if (has_xep_0511 or
                            has_xep_0392_link_metadata(msg)):
                        # If original message has XEP-0511,
                        # don't include YouTube info in the reply text
                        for x in list(
                            message.xml.findall("{urn:xmpp:ssn}x")
                        ):
                            message.xml.remove(x)

                    message.send()
                    continue
            if ctype:
                is_ok = "text/html" in ctype
            if is_ok and title:
                _body = f"[URL] {html.unescape(title)} {st} - ({final_url})"
                if isinstance(mdesc, str):
                    _body += f"\nDesc: '{html.unescape(mdesc)}'"
                message = bot.make_message(
                    mto=msg["from"].bare,
                    mbody=_body.strip(),
                    mtype="groupchat"
                )
                if thread_id:
                    try:
                        message["thread"] = thread_id
                    except Exception:
                        pass
                    # Only attach XEP-0511 if not already present
                    # in the original message
                    if (not has_xep_0511 and
                            not has_xep_0392_link_metadata(msg)):
                        try:
                            if title is not None:
                                message["link_metadata"]["title"] = (
                                    html.unescape(title)
                                )
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
                    if (has_xep_0511 or
                            has_xep_0392_link_metadata(msg)):
                        # If original message has XEP-0511,
                        # don't include URL info in the reply text
                        for x in list(
                            message.xml.findall("{urn:xmpp:ssn}x")
                        ):
                            message.xml.remove(x)

                message.send()
            elif ctype:
                continue
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


async def fetch_url_title(url, max_redirects=3):
    parsed_orig = urlparse(url)
    orig_fragment = parsed_orig.fragment

    async with aiohttp.ClientSession() as session:
        for _ in range(max_redirects):
            async with session.get(
                url, allow_redirects=False, timeout=8
            ) as resp:
                status = resp.status
                ctype = resp.headers.get("Content-Type", "")
                content_size = None
                if "Content-Length" in resp.headers:
                    try:
                        content_size = int(resp.headers["Content-Length"])
                    except Exception:
                        content_size = None
                if (
                    status in (301, 302, 303, 307, 308)
                    and "Location" in resp.headers
                ):
                    url = urljoin(str(resp.url), resp.headers["Location"])
                    continue
                if "text/html" in ctype:
                    log.info(f"[URLCHECK] Fetching: {url}")
                    window = b""
                    max_window = 16384  # 16 KB window
                    text = ""
                    found_title = False
                    found_desc = False
                    chunk_count = 0
                    async for chunk in resp.content.iter_chunked(8192):
                        window += chunk
                        if len(window) > max_window:
                            window = window[-max_window:]
                        try:
                            text = window.decode(resp.charset or "utf-8", errors="replace")
                        except Exception:
                            text = window.decode("utf-8", errors="replace")
                        title, mdesc = extract_html_title_desc(text)
                        found_title = bool(title)
                        found_desc = bool(mdesc)
                        chunk_count += 1
                        if found_title and found_desc:
                            break
                    # After reading, extract whatever is available
                    title, mdesc = extract_html_title_desc(text)
                    final_url = resp.url.human_repr()
                    if orig_fragment:
                        parsed_final = urlparse(final_url)
                        final_url = urlunparse(parsed_final._replace(fragment=orig_fragment))
                    log.info(f"[URLCHECK] URL: {final_url}, Chunks read: {chunk_count}")
                    return (
                        final_url, status,
                        ctype, title, None, mdesc
                    )
                else:
                    final_url = resp.url.human_repr()
                    if orig_fragment:
                        parsed_final = urlparse(final_url)
                        final_url = urlunparse(parsed_final._replace(fragment=orig_fragment))
                    log.info(f"[URLCHECK] URL: {final_url}, Chunks read: {chunk_count}")
                    return (
                        final_url, status, ctype,
                        None, content_size, None
                    )
        raise Exception("Too many redirects")


def extract_html_title_desc(html, is_wikipedia=False):
    title = None
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if m:
            title = m.group(1).strip()
    desc = None
    mdesc = re.search(
        r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']',
        html, re.I | re.S)
    if mdesc:
        desc = mdesc.group(1).strip()
    return title, desc


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
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url, timeout=8) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            items = data.get("items", [])
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
