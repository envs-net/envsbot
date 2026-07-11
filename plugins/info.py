"""
Info plugin.

This plugin provides various information commands:
- Wikipedia summary lookup
- Fetch latest toot from a Fediverse user
- Urban Dictionary term search
- Fetch an acronym's meaning, or add an acronym meaning not in the list

Commands:
    {prefix}wikipedia <search term> - lookup a summary for a term using
                                      Wikipedia
    {prefix}fediverse <@user@instance> - fetch latest public toot from a
                                         Fediverse user
    {prefix}udict <term> - search Urban Dictionary for a term
    {prefix}acronyms <ACRONYM> - look up a chat acronym (like 'lgtm')
    {prefix}acronym add <ACRONYM> <DESCRIPTION> - Will be reviewed before
                                                  addition
    {prefix}info on|off|status - to toggle in rooms
"""

import aiohttp
import inspect
import urllib.parse
import html
import logging
import re
import csv
import os

from bs4 import BeautifulSoup

from utils.command import command, Role
from utils.config import config
from utils.formatting import format_page, parse_page_args
from utils.http_fetch import fetch_json, passthrough_validator
from core_plugins._core import (
    handle_room_toggle_command,
    _is_muc_pm,
    _get_enabled_rooms
)

log = logging.getLogger(__name__)


def _command_prefix(bot=None) -> str:
    """Return the currently configured command prefix for usage replies."""
    return str(
        getattr(bot, "prefix", None)
        or config.get("prefix", ",")
        or ","
    )


INFO_KEY = "INFORMATION"
INFO_HTTP_TIMEOUT = float(config.get("http_timeout_seconds", 8) or 8)
INFO_HTTP_USER_AGENT = str(config.get("http_user_agent") or "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)")

PLUGIN_META = {
    "name": "info",
    "version": "0.5.0",
    "description": "Wikipedia, Fediverse, Urban Dictionary and acronym "
                   "lookup.",
    "category": "info",
    "requires": ["_core"],
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


@command(
    "fediverse",
    role=Role.USER,
    aliases=["fedi"],
    short="Show the latest public post from a Fediverse account.",
    usage="{prefix}fediverse <@user@instance>",
    examples=["{prefix}fedi @user@example.org"],
    category="info",
    context="any",
)
async def fediverse_latest(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the latest public toot from a Fediverse user.

    Usage:
        {prefix}fediverse <@user@instance>
        {prefix}fedi <@user@instance>

    Example:
        {prefix}fediverse @Gargron@mastodon.social
    """
    enabled_rooms = await _get_enabled_rooms(bot, INFO_KEY, "information")
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        bot.reply(msg, "ℹ️ Fediverse lookup is disabled in this room.")
        return

    if not args:
        bot.reply(
            msg,
            f"🟡️ Usage: {_command_prefix(bot)}fediverse <@user@instance>"
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
        user_result = await fetch_json(
            url,
            timeout_seconds=INFO_HTTP_TIMEOUT,
            max_bytes=131072,
            session_factory=aiohttp.ClientSession,
            validator=passthrough_validator,
            raise_for_status=False,
        )
        if user_result.status != 200:
            log.warning("[FEDIVERSE] 🔴  User not found on instance.")
            bot.reply(msg, "🔴  User not found on this instance.")
            return
        user = user_result.data
        user_id = user.get("id") if isinstance(user, dict) else None
        if not user_id:
            log.warning("[FEDIVERSE] 🔴  Could not resolve user ID.")
            bot.reply(msg, "🔴  Could not resolve user.")
            return
        timeline_url = (
            f"https://{instance}/api/v1/accounts/{user_id}/statuses"
            "?limit=1&exclude_replies=false&exclude_reblogs=false"
        )
        timeline_result = await fetch_json(
            timeline_url,
            timeout_seconds=INFO_HTTP_TIMEOUT,
            max_bytes=262144,
            session_factory=aiohttp.ClientSession,
            validator=passthrough_validator,
            raise_for_status=False,
        )
        if timeline_result.status != 200:
            log.warning("[FEDIVERSE] 🔴  Could not fetch user timeline.")
            bot.reply(msg, "🔴  Could not fetch user timeline.")
            return
        statuses = timeline_result.data
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


@command(
    "udict",
    role=Role.USER,
    aliases=["ud"],
    short="Search Urban Dictionary.",
    usage="{prefix}udict <term>",
    examples=["{prefix}ud xmpp"],
    category="info",
    context="any",
)
async def udict_search(bot, sender_jid, nick, args, msg, is_room):
    """
    Search Urban Dictionary for a term.

    Usage:
        {prefix}udict <term>
        {prefix}ud <term>

    Example:
        {prefix}udict yeet
    """
    enabled_rooms = await _get_enabled_rooms(bot, INFO_KEY, "information")
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        bot.reply(msg, "ℹ️ Urban Dictionary lookup is disabled in this room.")
        return

    if not args:
        bot.reply(
            msg,
            f"🟡️ Usage: {_command_prefix(bot)}udict <term>"
        )
        return

    term = " ".join(args).strip()
    url = UDICT_API_URL.format(term)

    try:
        result = await fetch_json(
            url,
            timeout_seconds=INFO_HTTP_TIMEOUT,
            max_bytes=262144,
            session_factory=aiohttp.ClientSession,
            validator=passthrough_validator,
            raise_for_status=False,
        )
        if result.status != 200:
            log.warning("[UDICT] 🔴  Failed to fetch definition.")
            bot.reply(msg, "🔴  Failed to fetch definition.")
            return
        data = result.data
    except Exception:
        log.exception("[UDICT] 🚨 Error fetching from Urban Dictionary.")
        bot.reply(msg, "🔴  Error fetching from Urban Dictionary.")
        return

    defs = data.get("list", [])
    if not defs:
        bot.reply(msg, f"ℹ️ No definitions found for '{term}'.")
        return

    entry = defs[0]
    definition = entry.get("definition", "").replace("\r", "").replace(
        "\n", " ")
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

# ---------------- Wikipedia ----------------

WIKIPEDIA_API_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"


async def fetch_wikipedia_summary(term):
    """
    Query the Wikipedia REST API and return extracted data, or None on error.
    """
    url = WIKIPEDIA_API_URL.format(urllib.parse.quote(term))
    result = await fetch_json(
        url,
        headers={"User-Agent": INFO_HTTP_USER_AGENT},
        timeout_seconds=INFO_HTTP_TIMEOUT,
        max_bytes=262144,
        session_factory=aiohttp.ClientSession,
        validator=passthrough_validator,
        raise_for_status=False,
    )
    if result.status == 200 and isinstance(result.data, dict):
        data = result.data
        title = data.get("title")
        summary = data.get("extract")
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page")
        if title and summary and page_url:
            return title, summary, page_url
        # If it's a redirect/disambiguation, may contain other structure
        if data.get("type") == "disambiguation" and "titles" in data:
            return data["titles"].get("canonical"), "Disambiguation page", page_url
    return None


@command(
    "wikipedia",
    role=Role.USER,
    aliases=["wiki"],
    short="Search Wikipedia.",
    usage="{prefix}wikipedia <term>",
    examples=["{prefix}wiki XMPP"],
    category="info",
    context="any",
)
async def wikipedia_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Lookup a summary for a term using Wikipedia.

    Usage:
        {prefix}wikipedia <search term>
        {prefix}wiki <search term>
    """
    enabled_rooms = await _get_enabled_rooms(bot, INFO_KEY, "information")
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        bot.reply(msg, "ℹ️ Wikipedia lookup is disabled in this room.")
        return

    if not args:
        bot.reply(msg, f"Usage: {_command_prefix(bot)}wikipedia <search term>")
        return

    term = " ".join(args)
    result = fetch_wikipedia_summary(term)
    if inspect.isawaitable(result):
        result = await result

    if result:
        title, summary, url = result
        lines = [
            f"📖 Wikipedia: {title}",
            summary,
            f"URL: {url}",
        ]
        bot.reply(msg, lines)
    else:
        bot.reply(msg, f"No Wikipedia summary found for '{term}'.")


# ----------------- Chat Slang Lookup -----------------

# --- Configuration ---
SLANG_CSV = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "chat_slang.csv"
)
SLANG_ADDITIONS_CSV = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "slang_additions.csv"
)
SLANG_REMOVALS_CSV = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "slang_removals.csv"
)



# --- CSV helpers ---

def load_main_definitions():
    """Load all acronyms and their descriptions from main CSV only."""
    defs = {}
    if os.path.exists(SLANG_CSV):
        with open(SLANG_CSV, encoding='utf-8') as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    key = row[0].strip().lower()
                    desc = row[1].strip()
                    defs.setdefault(key, []).append(desc)
    return defs


def all_main_descriptions(acronym):
    results = []
    seen = set()
    for d in load_main_definitions().get(acronym.lower().strip(), []):
        norm = d.strip().lower()
        if norm not in seen:
            results.append(d.strip())
            seen.add(norm)
    return results


def addition_exists(acronym, description):
    acronym = acronym.lower().strip()
    description = description.lower().strip()
    if os.path.exists(SLANG_ADDITIONS_CSV):
        with open(SLANG_ADDITIONS_CSV, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    abbr, desc = row[0].strip().lower(), row[1].strip().lower()
                    if abbr == acronym and desc == description:
                        return True
    return False


def removal_exists(acronym, description):
    acronym = acronym.lower().strip()
    description = description.lower().strip()
    if os.path.exists(SLANG_REMOVALS_CSV):
        with open(SLANG_REMOVALS_CSV, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    abbr, desc = row[0].strip().lower(), row[1].strip().lower()
                    if abbr == acronym and desc == description:
                        return True
    return False


def description_exists_in_main(acronym, description):
    acronym = acronym.lower().strip()
    description = description.lower().strip()
    if os.path.exists(SLANG_CSV):
        with open(SLANG_CSV, encoding='utf-8') as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    abbr, desc = row[0].strip().lower(), row[1].strip().lower()
                    if abbr == acronym and desc == description:
                        return True
    return False


def delete_from_csv(filename, matchfunc):
    removed = 0
    kept = []
    if os.path.exists(filename):
        with open(filename, encoding="utf-8") as f:
            for row in csv.reader(f):
                if not matchfunc(row):
                    kept.append(row)
                else:
                    removed += 1
        with open(filename, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(kept)
    return removed


# --- Acronym Commands ---

@command(
    "acronyms",
    role=Role.USER,
    aliases=["acro", "acronym"],
    short="Look up stored acronym definitions.",
    usage="{prefix}acronyms <acronym>",
    examples=["{prefix}acro XMPP"],
    category="info",
    context="any",
)
async def acronyms_cmd(bot, sender, nick, args, msg, is_room):
    """
    Look up all definitions of a chat acronym from the main list.

    Usage:
        {prefix}acronyms <acronym>
        {prefix}acro <acronym>
        {prefix}acronym <acronym>
    """
    enabled_rooms = await _get_enabled_rooms(bot, INFO_KEY, "information")
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        bot.reply(msg, "ℹ️ Acronyms are disabled in this room.")
        return None

    if not args:
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}acronyms <acronym>"
        )
        return None
    query = args[0].strip().lower()
    definitions = all_main_descriptions(query)
    if definitions:
        lines = [f"{query.upper()}: {d}" for d in definitions]
        log.info(
            f"[ACRONYMS] Returned {len(definitions)} definitions for "
            f"acronym '{query}' from main list."
        )
        bot.reply(msg, lines)
        return None
    else:
        log.info(
            f"[ACRONYMS] User '{sender}' query '{query}' not found in main "
            f"database."
        )
        bot.reply(
            msg,
            f"Sorry, '{query}' is not defined in my slang database."
        )
        return None


@command(
    "acronyms add",
    role=Role.USER,
    aliases=["acro add", "acronym add"],
    short="Suggest a new acronym definition for admin review.",
    usage="{prefix}acronyms add <acronym> <description>",
    examples=["{prefix}acro add XMPP Extensible Messaging and Presence Protocol"],
    category="info",
    context="any",
)
async def acronyms_add_cmd(bot, sender, nick, args, msg, is_room):
    """
    Suggest a new acronym/description. Entry will be reviewed by admins
    before becoming visible.

    Usage:
        {prefix}acronyms add <acronym> <description>
        {prefix}acro add <acronym> <description>
        {prefix}acronym add <acronym> <description>
    """
    enabled_rooms = await _get_enabled_rooms(bot, INFO_KEY, "information")
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        bot.reply(msg, "ℹ️ Acronyms are disabled in this room.")
        return None

    if len(args) < 2:
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}acronyms add <acronym> <description>"
        )
        return None
    abbreviation = args[0].strip()
    description = " ".join(args[1:]).strip()
    if description_exists_in_main(abbreviation, description):
        log.info(
            f"[ACRONYMS] {sender} tried to queue existing main def: "
            f"{abbreviation}:{description}"
        )
        bot.reply(
            msg,
            f"The definition for '{abbreviation}' already exists in the "
            f"database."
        )
        return None
    if addition_exists(abbreviation, description):
        log.info(
            f"[ACRONYMS] {sender} tried to queue existing pending addition: "
            f"{abbreviation}:{description}"
        )
        bot.reply(
            msg,
            "This suggestion is already awaiting admin review."
        )
        return None
    os.makedirs(os.path.dirname(SLANG_ADDITIONS_CSV), exist_ok=True)
    with open(SLANG_ADDITIONS_CSV, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([abbreviation, description, nick or sender])
    log.info(
        f"[ACRONYMS] Queued new addition by {sender}/{nick}: "
        f"{abbreviation}:{description}"
    )
    bot.reply(
        msg,
        f"Suggestion for '{abbreviation}' was queued for admin review. "
        f"Thank you!"
    )
    return None


@command(
    "acronyms remove",
    role=Role.USER,
    aliases=["acro remove", "acronym remove"],
    short="Suggest removing one acronym definition for admin review.",
    usage="{prefix}acronyms remove <acronym> <description>",
    examples=["{prefix}acro remove XMPP old definition"],
    category="info",
    context="any",
)
async def acronyms_remove_cmd(bot, sender, nick, args, msg, is_room):
    """
    Suggest the removal of an existing acronym/description pair. Entry will
    be reviewed by admins.

    Usage:
        {prefix}acronyms remove <acronym> <description>
        {prefix}acro remove <acronym> <description>
        {prefix}acronym remove <acronym> <description>
    """
    enabled_rooms = await _get_enabled_rooms(bot, INFO_KEY, "information")
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        bot.reply(msg, "ℹ️ Acronyms are disabled in this room.")
        return None

    if len(args) < 2:
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}acronyms remove <acronym> <description>"
        )
        return None
    abbreviation = args[0].strip()
    description = " ".join(args[1:]).strip()
    if not description_exists_in_main(abbreviation, description):
        bot.reply(
            msg,
            "That definition doesn't exist in the main list."
        )
        return None
    if removal_exists(abbreviation, description):
        log.info(
            f"[ACRONYMS] {sender} tried to queue existing pending removal: "
            f"{abbreviation}:{description}"
        )
        bot.reply(
            msg,
            "This removal is already awaiting admin review."
        )
        return None
    os.makedirs(os.path.dirname(SLANG_REMOVALS_CSV), exist_ok=True)
    with open(SLANG_REMOVALS_CSV, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([abbreviation, description, nick or sender])
    log.info(
        f"[ACRONYMS] Queued new removal by {sender}/{nick}: "
        f"{abbreviation}:{description}"
    )
    bot.reply(
        msg,
        f"Removal suggestion for '{abbreviation}' was queued for admin "
        f"review. Thank you!"
    )
    return None


@command(
    "acronyms list",
    role=Role.ADMIN,
    aliases=["acro list", "acronym list"],
    short="List pending acronym additions and removals.",
    usage="{prefix}acronyms list [all|page|last]",
    examples=["{prefix}acro list", "{prefix}acro list 2"],
    category="info",
    context="any",
)
async def acronyms_list_cmd(bot, sender, nick, args, msg, is_room):
    """
    Display pending slang additions and removals with proposer nicknames for
    admin review.

    Usage:
        {prefix}acronyms list [all|page|last]
        {prefix}acro list [all|page|last]
        {prefix}acronym list [all|page|last]
    """
    enabled_rooms = await _get_enabled_rooms(bot, INFO_KEY, "information")
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        bot.reply(msg, "ℹ️ Acronyms are disabled in this room.")
        return None

    addition_lines = []
    removal_lines = []
    if os.path.exists(SLANG_ADDITIONS_CSV):
        with open(SLANG_ADDITIONS_CSV, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 3:
                    addition_lines.append(
                        f"{row[0].upper()}: {row[1]} (by {row[2]})"
                    )
    if os.path.exists(SLANG_REMOVALS_CSV):
        with open(SLANG_REMOVALS_CSV, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 3:
                    removal_lines.append(
                        f"{row[0].upper()}: {row[1]} (by {row[2]})"
                    )
    log.info(
        f"[ACRONYMS] Admin {sender} reviewed {len(addition_lines)} "
        f"additions and {len(removal_lines)} removals."
    )
    lines = ["Pending Additions:"]
    lines.extend(f"• {line}" for line in addition_lines)
    if not addition_lines:
        lines.append("—")
    lines.append("")
    lines.append("Pending Removals:")
    lines.extend(f"• {line}" for line in removal_lines)
    if not removal_lines:
        lines.append("—")

    page_request = parse_page_args(args or [])
    bot.reply(
        msg,
        "\n".join(format_page(
            "📚 Pending acronym changes",
            lines,
            page_request=page_request,
            page_size=10,
            command_hint=f"{_command_prefix(bot)}acronyms list",
        )),
    )
    return None


@command(
    "acronyms merge",
    role=Role.ADMIN,
    aliases=["acro merge", "acronym merge"],
    short="Apply pending acronym additions and removals.",
    usage="{prefix}acronyms merge",
    examples=["{prefix}acro merge"],
    category="info",
    context="any",
)
async def acronyms_merge_cmd(bot, sender, nick, args, msg, is_room):
    """
    Admin command to apply pending additions and removals to the main slang
    database.

    Usage:
        {prefix}acronyms merge
        {prefix}acro merge
        {prefix}acronym merge
    """
    enabled_rooms = await _get_enabled_rooms(bot, INFO_KEY, "information")
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        bot.reply(msg, "ℹ️ Acronyms are disabled in this room.")
        return None

    main_entries = []
    if os.path.exists(SLANG_CSV):
        with open(SLANG_CSV, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    acro = row[0].strip()
                    desc = row[1].strip()
                    main_entries.append([acro, desc])
    # Removals
    removals = set()
    if os.path.exists(SLANG_REMOVALS_CSV):
        with open(SLANG_REMOVALS_CSV, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    acro, desc = row[0].strip(), row[1].strip()
                    removals.add((acro.lower(), desc.lower()))
    kept_entries = [
        row for row in main_entries
        if (row[0].lower(), row[1].lower()) not in removals
    ]
    removed_count = len(main_entries) - len(kept_entries)
    # Additions
    new_add_count = 0
    if os.path.exists(SLANG_ADDITIONS_CSV):
        with open(SLANG_ADDITIONS_CSV, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    acro, desc = row[0].strip(), row[1].strip()
                    key = (acro.lower(), desc.lower())
                    if key not in {
                        (row[0].lower(), row[1].lower())
                        for row in kept_entries
                    }:
                        kept_entries.append([acro, desc])
                        new_add_count += 1
                        log.info(
                            f"[ACRONYMS] Added new slang: {acro}:{desc}"
                        )
    with open(SLANG_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(kept_entries)
    if os.path.exists(SLANG_ADDITIONS_CSV):
        os.remove(SLANG_ADDITIONS_CSV)
    if os.path.exists(SLANG_REMOVALS_CSV):
        os.remove(SLANG_REMOVALS_CSV)
    log.info(
        f"[ACRONYMS] Admin {sender} merged: +{new_add_count} additions, "
        f"-{removed_count} removals."
    )
    bot.reply(
        msg,
        f"Merged {new_add_count} additions and {removed_count} removals "
        f"into the slang database."
    )
    return None


@command(
    "acronyms delete",
    role=Role.ADMIN,
    aliases=["acro delete", "acronym delete"],
    short="Delete pending acronym suggestions by nick or definition.",
    usage="{prefix}acronyms delete <nick|acronym description>",
    examples=[
        "{prefix}acro delete Alice",
        "{prefix}acro delete XMPP old definition",
    ],
    category="info",
    context="any",
)
async def acronyms_delete_cmd(bot, sender, nick, args, msg, is_room):
    """
    Admin command to delete from the suggestions/removals queue by
    (acronym, description) or by nick.

    Usage:
        {prefix}acronyms delete <acronym> <description>
        {prefix}acro delete <acronym> <description>
        {prefix}acronym delete <acronym> <description>
        {prefix}acronyms delete <nick>
        {prefix}acro delete <nick>
        {prefix}acronym delete <nick>
    """
    enabled_rooms = await _get_enabled_rooms(bot, INFO_KEY, "information")
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        bot.reply(msg, "ℹ️ Acronyms are disabled in this room.")
        return None

    if not args:
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}acronyms delete <acronym> <description> OR "
            f"{_command_prefix(bot)}acronyms delete <nick>"
        )
        return None
    total_removed = 0
    if len(args) == 1:
        # Delete all additions/removals made by that nick
        nick_arg = args[0].strip().lower()
        for fname in (SLANG_ADDITIONS_CSV, SLANG_REMOVALS_CSV):
            def matchfunc(row):
                return len(row) >= 3 and row[2].strip().lower() == nick_arg
            removed = delete_from_csv(fname, matchfunc)
            if removed:
                log.info(
                    f"[ACRONYMS] Admin {sender} deleted {removed} entries "
                    f"from {fname} for nick {nick_arg}"
                )
            total_removed += removed
        if total_removed:
            bot.reply(
                msg,
                f"Deleted {total_removed} entries for nick "
                f"'{args[0].strip()}' from pending additions/removals."
            )
        else:
            bot.reply(
                msg,
                f"No pending additions/removals found for nick "
                f"'{args[0].strip()}'."
            )
        return None
    else:
        abbreviation = args[0].strip().lower()
        description = " ".join(args[1:]).strip().lower()
        for fname in (SLANG_ADDITIONS_CSV, SLANG_REMOVALS_CSV):
            def matchfunc(row):
                return (
                    len(row) >= 2 and
                    row[0].strip().lower() == abbreviation and
                    row[1].strip().lower() == description
                )
            removed = delete_from_csv(fname, matchfunc)
            if removed:
                log.info(
                    f"[ACRONYMS] Admin {sender} deleted {removed} entries "
                    f"from {fname} for {abbreviation}:{description}"
                )
            total_removed += removed
        if total_removed:
            bot.reply(
                msg,
                f"Deleted {total_removed} entries for "
                f"'{abbreviation}: {description}' from pending "
                f"additions/removals."
            )
        else:
            bot.reply(
                msg,
                f"No pending addition/removal found for "
                f"'{abbreviation}: {description}'."
            )
        return None

# ----------------- Information Plugin Toggle -----------------


@command(
    "info",
    role=Role.MODERATOR,
    short="Enable, disable or show room access to information commands.",
    usage="{prefix}info <on|off|status>",
    examples=["{prefix}info status"],
    category="info",
    context="room or MUC PM",
)
async def information_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Toggle info plugin features in the current room.

    Usage:
        {prefix}info on|off|status
    """
    if not args:
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}info on|off|status"
        )
        return None

    if is_room or _is_muc_pm(msg):
        handled = await handle_room_toggle_command(
            bot,
            msg,
            is_room,
            args,
            store_getter=get_info_store,
            key=INFO_KEY,
            label="Get Urban Dictionary summaries",
            storage="dict",
            log_prefix="[INFORMATION]",
        )
        if handled:
            return None

    bot.reply(
        msg,
        f"Usage: {_command_prefix(bot)}information on|off|status (in a room or PM)"
    )
    return None


async def get_info_store(bot):
    return bot.db.users.plugin("information")


def _diagnostic_enabled_count(enabled_rooms: set[str], room_jid: str | None) -> int:
    if not room_jid:
        return len(enabled_rooms)
    target = str(room_jid).split('/', 1)[0].strip().lower()
    return sum(
        1 for room in enabled_rooms
        if str(room).split('/', 1)[0].strip().lower() == target
    )


def _csv_row_count(path: str) -> int:
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as handle:
            return sum(1 for row in csv.reader(handle) if len(row) >= 2)
    except OSError:
        return 0


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int | float]:
    """Return small info-plugin counters for diagnostics."""
    enabled_rooms = await _get_enabled_rooms(bot, INFO_KEY, "information")
    definitions = load_main_definitions()
    return {
        "enabled_rooms": _diagnostic_enabled_count(enabled_rooms, room_jid),
        "acronyms": len(definitions),
        "definitions": sum(len(items) for items in definitions.values()),
        "pending_additions": _csv_row_count(SLANG_ADDITIONS_CSV),
        "pending_removals": _csv_row_count(SLANG_REMOVALS_CSV),
        "timeout": INFO_HTTP_TIMEOUT,
    }


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return info plugin health lines."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    return [
        f"✅ Info{scope}: enabled_rooms={state['enabled_rooms']}, "
        f"acronyms={state['acronyms']}, definitions={state['definitions']}, "
        f"pending_additions={state['pending_additions']}, "
        f"pending_removals={state['pending_removals']}, "
        f"timeout={state['timeout']:g}s"
    ]
