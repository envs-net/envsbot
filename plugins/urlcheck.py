"""
URL Check plugin.

This plugin allows moderators to enable or disable automatic URL title
checking in a groupchat room. When enabled, the bot will watch for URLs
in messages and output the title and filetype for HTML pages, or YouTube
video info for YouTube links.

Command:
    {prefix}urlcheck on
    {prefix}urlcheck off

Requires:
    - aiohttp
    - Users plugin (for runtime store)
    - YouTube Data API key in config as "youtube_api_key"
"""

import re
import aiohttp
import logging

import isodate

from datetime import datetime
from functools import partial

from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "urlcheck",
    "version": "0.1.0",
    "description": "URL title and YouTube info fetcher for groupchats",
    "category": "info",
    "requires": ["users"],
}

URLCHECK_KEY = "URLCHECK"
URL_RE = re.compile(r"https?://[^\s<>\"]+", re.I)
YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]+)", re.I
)


async def get_urlcheck_store(bot):
    return bot.db.users.plugin("urlcheck")


@command("urlcheck", role=Role.MODERATOR)
async def urlcheck_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Enable or disable URL checking in this room (MUC direct message only).

    Usage:
        {prefix}urlcheck on
        {prefix}urlcheck off
    """
    # Only allow in MUC direct message (not groupchat, not direct to bot)
    if not (
        msg.get("type") in ("chat", "normal")
        and hasattr(msg["from"], "bare")
        and "@" in str(msg["from"].bare)
    ):
        bot.reply(
            msg,
            "This command can only be used in a MUC direct message "
            "(not in groupchat or direct to the bot)."
        )
        return

    room = msg["from"].bare

    # Check if the bot is actually joined to this room
    if room not in JOINED_ROOMS:
        bot.reply(
            msg,
            "This room is not a joined room. URL checking can only be "
            "enabled or disabled for joined rooms."
        )
        return

    if not args or args[0] not in ("on", "off"):
        bot.reply(msg, f"Usage: {bot.prefix}urlcheck <on|off>")
        return

    store = await get_urlcheck_store(bot)
    enabled_rooms = await store.get_global(URLCHECK_KEY, default={})

    if args[0] == "on":
        enabled_rooms[room] = True
        await store.set_global(URLCHECK_KEY, enabled_rooms)
        bot.reply(msg, "✅ URL checking enabled in this room.")
    else:
        if room in enabled_rooms:
            del enabled_rooms[room]
            await store.set_global(URLCHECK_KEY, enabled_rooms)
        bot.reply(msg, "🛑 URL checking disabled in this room.")


async def on_groupchat_message(bot, msg):
    room = msg["from"].bare
    nick = msg.get("mucnick") or msg["from"].resource
    if JOINED_ROOMS.get(room, {}).get("nick") == nick:
        return

    # Only process URLs if the room is a joined room
    if room not in JOINED_ROOMS:
        return

    store = await get_urlcheck_store(bot)
    enabled_rooms = await store.get_global(URLCHECK_KEY, default={})
    if room not in enabled_rooms:
        return

    text = msg.get("body", "")
    # Only match URLs in lines that do not start with ">"
    lines = [line for line in text.splitlines() if not line.lstrip().startswith(">")]
    urls = []
    for line in lines:
        urls.extend(URL_RE.findall(line))
    if not urls:
        return

    for url in urls:
        try:
            # handle up to 3 redirects manually
            final_url, status, ctype, title, content_size = await fetch_url_title(
                url, max_redirects=3
            )
            st = f"(Status: {status})" if status != 200 else ""
            if is_youtube_url(final_url):
                yt_info = await fetch_youtube_info(final_url)
                if yt_info:
                    bot.reply(
                        msg, yt_info, mention=False, thread=True,
                        ephemeral=False
                    )
                    continue
            if ctype and ctype.startswith("text/html") and title:
                bot.reply(
                    msg,
                    f'[URL] "{title}" {st} ({final_url})',
                    mention=False, thread=True, ephemeral=False
                )
            elif ctype:
                return
        except Exception as e:
            log.warning(f"[URLCHECK] Failed to fetch URL {url}: {e}")


def is_youtube_url(url):
    return "youtube.com/watch" in url or "youtu.be/" in url


async def fetch_url_title(url, max_redirects=3):
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
                    url = resp.headers["Location"]
                    continue
                if ctype.startswith("text/html"):
                    text = await resp.text(errors="replace")
                    title = extract_html_title(text)
                    return (
                        resp.url.human_repr(), status, ctype, title, None
                    )
                else:
                    return (
                        resp.url.human_repr(), status, ctype,
                        None, content_size
                    )
        raise Exception("Too many redirects")


def extract_html_title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        return m.group(1).strip()
    return None


async def fetch_youtube_info(url):
    api_key = config.get("youtube_api_key")
    if not api_key:
        return None
    m = YOUTUBE_RE.search(url)
    if not m:
        return None
    video_id = m.group(1)
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
                    upload_date = datetime.strptime(upload_date[:10], "%Y-%m-%d").strftime("%d %b %Y")
                except Exception:
                    pass
            return (
                f'[YOUTUBE] "{title}" uploaded by {uploader} '
                f'({length_str}) - Views: {views}'
                + (f' - {upload_date}' if upload_date else '')
            )


async def on_load(bot):
    bot.bot_plugins.register_event(
        "urlcheck",
        "groupchat_message",
        partial(on_groupchat_message, bot))
