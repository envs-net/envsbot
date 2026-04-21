"""
Info plugin.

This plugin provides various information commands:
- Fetch latest toot from a Fediverse user
- Urban Dictionary term search

Commands:
    {prefix}fediverse <@user@instance>
    {prefix}udict <term>
"""

import aiohttp
import html
import logging
import re

from bs4 import BeautifulSoup

from utils.command import command, Role
from utils.config import config

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "information",
    "version": "0.2.0",
    "description": "Fediverse and Urban Dictionary lookup.",
    "category": "info",
}


# ---------------- Fediverse ----------------

FEDIVERSE_USER_RE = re.compile(r"^@?([^@]+)@([^@]+)$")


def html_to_text_with_links(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    for a in soup.find_all("a"):
        href = a.get("href")
        if href:
            a.replace_with(f"{a.get_text()} ({href})")
    text = soup.get_text(separator=" ", strip=True)
    return html.unescape(text)


@command("fediverse", role=Role.USER, aliases=["fedi"])
async def fediverse_latest(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the latest public toot from a Fediverse user.

    Usage:
        {prefix}fediverse <@user@instance>
        {prefix}fedi <@user@instance>

    Example:
        {prefix}fediverse @Gargron@mastodon.social
    """
    if not args:
        bot.reply(
            msg,
            f"🟡️ Usage: {config.get('prefix', ',')}fediverse <@user@instance>"
        )
        return

    match = FEDIVERSE_USER_RE.match(args[0])
    if not match:
        log.warning("[FEDIVERSE] 🟡️ Invalid user format.")
        bot.reply(
            msg,
            "🟡️ Please specify the user as @user@instance"
        )
        return

    username, instance = match.groups()
    url = f"https://{instance}/api/v1/accounts/lookup?acct={username}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    log.warning("[FEDIVERSE] 🔴  User not found on instance.")
                    bot.reply(msg, "🔴  User not found on this instance.")
                    return
                user = await resp.json()
            user_id = user.get("id")
            if not user_id:
                log.warning("[FEDIVERSE] 🔴  Could not resolve user ID.")
                bot.reply(msg, "🔴  Could not resolve user.")
                return
            timeline_url = (
                f"https://{instance}/api/v1/accounts/{user_id}/statuses"
                "?limit=1&exclude_replies=false&exclude_reblogs=false"
            )
            async with session.get(timeline_url, timeout=8) as resp:
                if resp.status != 200:
                    log.warning("[FEDIVERSE] 🔴  Could not fetch user timeline.")
                    bot.reply(msg, "🔴  Could not fetch user timeline.")
                    return
                statuses = await resp.json()
    except Exception:
        log.exception("[FEDIVERSE] 🚨 Error fetching from Fediverse.")
        bot.reply(msg, "🔴  Error fetching from Fediverse.")
        return

    if not statuses:
        bot.reply(msg, "ℹ️ No public toots found for this user.")
        return

    status = statuses[0]
    content = html_to_text_with_links(status.get("content", ""))
    url = status.get("url", "")
    boosts = status.get("reblogs_count", 0)
    replies = status.get("replies_count", 0)
    likes = status.get("favourites_count", 0)

    lines = [
        f"🐘 Latest toot from @{username}@{instance}:",
        f"{content}",
        f"{url}",
        f"🔁 {boosts}   💬 {replies}   ❤️ {likes}"
    ]
    bot.reply(msg, lines, ephemeral=False)

# ---------------- Urban Dictionary ----------------

UDICT_API_URL = "https://api.urbandictionary.com/v0/define?term={}"


@command("udict", role=Role.USER, aliases=["ud"])
async def udict_search(bot, sender_jid, nick, args, msg, is_room):
    """
    Search Urban Dictionary for a term.

    Usage:
        {prefix}udict <term>
        {prefix}ud <term>

    Example:
        {prefix}udict yeet
    """
    if not args:
        bot.reply(
            msg,
            f"🟡️ Usage: {config.get('prefix', ',')}udict <term>"
        )
        return

    term = " ".join(args).strip()
    url = UDICT_API_URL.format(term)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    log.warning("[UDICT] 🔴  Failed to fetch definition.")
                    bot.reply(msg, "🔴  Failed to fetch definition.")
                    return
                data = await resp.json()
    except Exception:
        log.exception("[UDICT] 🚨 Error fetching from Urban Dictionary.")
        bot.reply(msg, "🔴  Error fetching from Urban Dictionary.")
        return

    defs = data.get("list", [])
    if not defs:
        bot.reply(msg, f"ℹ️ No definitions found for '{term}'.")
        return

    entry = defs[0]
    definition = entry.get("definition", "").replace("\r", "").replace("\n", " ")
    example = entry.get("example", "").replace("\r", "").replace("\n", " ")
    thumbs_up = entry.get("thumbs_up", 0)
    thumbs_down = entry.get("thumbs_down", 0)
    permalink = entry.get("permalink", "")

    lines = [
        f"📚 Urban Dictionary: {term}",
        f"Definition: {definition}",
    ]
    if example:
        lines.append(f"Example: {example}")
    lines.append(f"👍 {thumbs_up}   👎 {thumbs_down}")
    if permalink:
        lines.append(permalink)

    bot.reply(msg, lines)
