"""
Info plugin.

This plugin provides various information commands:
- Acronym lookup from Acromine
- Thesaurus (synonyms) for English and German (OpenThesaurus)
- Fetch latest toot from a Fediverse user
- Urban Dictionary term search

Commands:
    {prefix}acronym <word>
    {prefix}thesaurus <lang>:<word>
    {prefix}thesaurus langs
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
    "version": "0.1.0",
    "description": "Acronym, thesaurus, fediverse, and Urban Dictionary lookup.",
    "category": "info",
}

# ---------------- Acronym Lookup ----------------

ACRO_API_URL = (
    "http://www.nactem.ac.uk/software/acromine/dictionary.py?sf={}"
)


@command("acronym", role=Role.USER, aliases=["acronyms"])
async def acronym_lookup(bot, sender_jid, nick, args, msg, is_room):
    """
    Look up the meaning of an acronym.

    Usage:
        {prefix}acronym <word>
        {prefix}acronyms <word>

    Example:
        {prefix}acronym NASA
    """
    if not args:
        bot.reply(
            msg,
            f"🟡️ Usage: {config.get('prefix', ',')}acronym <word>"
        )
        return

    term = args[0].strip()
    url = ACRO_API_URL.format(term)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    log.warning("[ACRONYM] 🔴  Failed to fetch acronym definition.")
                    bot.reply(
                        msg,
                        "🔴  Failed to fetch acronym definition."
                    )
                    return
                data = await resp.json()
    except Exception:
        log.exception("[ACRONYM] 🚨 Error fetching acronym definition.")
        bot.reply(
            msg,
            "🔴  Error fetching acronym definition."
        )
        return

    if not data or not data[0] or not data[0].get("lfs"):
        bot.reply(
            msg,
            f"ℹ️ No definitions found for '{term}'."
        )
        return

    lfs = data[0]["lfs"]
    lines = [f"📚 Definitions for '{term}':"]
    for entry in lfs[:5]:
        lines.append(f"- {entry['lf']}")

    bot.reply(msg, lines)

# ---------------- Thesaurus (English/German) ----------------

LANGUAGES = {
    "en": "English",
    "de": "Deutsch",
}

THES_API_ENDPOINTS = {
    "en": "https://www.openthesaurus.de/synonyme/search?q={}&format=application/json",
    "de": "https://www.openthesaurus.de/synonyme/search?q={}&format=application/json",
}


@command("thesaurus", role=Role.USER, aliases=["thes"])
async def thesaurus_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Look up synonyms for a word in English or German.

    Usage:
        {prefix}thesaurus <lang>:<word>
        {prefix}thes <lang>:<word>
        {prefix}thesaurus langs

    Examples:
        {prefix}thesaurus en:happy
        {prefix}thes de:haus
        {prefix}thesaurus langs
    """
    if not args:
        bot.reply(
            msg,
            f"🟡️ Usage: {config.get('prefix', ',')}thesaurus <lang>:<word>"
        )
        return

    if args[0] == "langs":
        log.info("[THESAURUS] 🌐 Listing available languages.")
        lines = [
            "🌐 Available languages:",
            "",
            f"{'Code':<6} {'Language':<15}",
            f"{'-'*6} {'-'*15}",
        ]
        for code, name in LANGUAGES.items():
            lines.append(f"{code:<6} {name:<15}")
        lines.append("")
        lines.append(
            "Format: <lang>:<word>  (e.g. en:happy, de:haus)"
        )
        bot.reply(msg, lines)
        return

    if ":" not in args[0]:
        bot.reply(
            msg,
            "🟡️ Please specify language and word as <lang>:<word>."
        )
        return

    lang, word = args[0].split(":", 1)
    lang = lang.lower().strip()
    word = word.strip()

    if lang not in LANGUAGES:
        log.warning(f"[THESAURUS] 🟡️ Language '{lang}' not supported.")
        bot.reply(
            msg,
            f"🟡️ Language '{lang}' not supported. "
            f"Use {config.get('prefix', ',')}thesaurus langs"
        )
        return

    url = THES_API_ENDPOINTS[lang].format(word)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    log.warning("[THESAURUS] 🔴  Failed to fetch synonyms.")
                    bot.reply(
                        msg,
                        "🔴  Failed to fetch synonyms."
                    )
                    return
                data = await resp.json()
    except Exception:
        log.exception("[THESAURUS] 🚨 Error fetching synonyms.")
        bot.reply(
            msg,
            "🔴  Error fetching synonyms."
        )
        return

    synonyms = []
    for synset in data.get("synsets", []):
        synonyms.extend(synset.get("terms", []))
    synonyms = [term["term"] for term in synonyms][:10]

    if not synonyms:
        bot.reply(
            msg,
            f"ℹ️ No synonyms found for '{word}' in {LANGUAGES[lang]}."
        )
        return

    lines = [
        f"📚 Synonyms for '{word}' ({LANGUAGES[lang]}):",
        ", ".join(synonyms)
    ]
    bot.reply(msg, lines)

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
