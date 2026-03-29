"""
Profile management plugin.

This plugin allows users to set their FULLNAME, LOCATION, TIMEZONE, BIRTHDAY,
PRONOUNS, SPECIES, EMAIL, and manage up to 6 URLs with descriptions in their
profile. It also allows querying some of these fields for yourself or another
user in a room by nickname.
"""

import slixmpp
from utils.command import command, Role
from utils.config import config
import pytz
import datetime
import re
import urllib.parse
import logging
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "profile",
    "version": "0.1.0",
    "description": "User profile management",
    "category": "info",
    "requires": ["rooms"],
}


def resolve_real_jid(bot, msg, is_room):
    """
    Resolve the real sender JID in all contexts (groupchat, MUC PM, or DM).
    """
    jid = None
    muc = bot.plugin.get("xep_0045", None)
    if muc:
        room = msg['from'].bare
        nick = msg.get("mucnick") or msg["from"].resource
        jid = muc.get_jid_property(room, nick, "jid")
    if jid is None:
        jid = msg["from"]
    return str(slixmpp.JID(jid).bare)


async def _check_user_exists(bot, sender_jid, msg):
    """
    Check if the user exists in the database.

    Args:
        bot: The bot instance.
        sender_jid: The JID to check.
        msg: The message object.

    Returns:
        bool: True if user exists, False otherwise.
    """
    jid = str(sender_jid)
    user = await bot.db.users.get(jid)
    if not user:
        log.warning(
            "[PROFILE] ❌ Unregistered user tried to use config: %s", jid
        )
        bot.reply(msg, "❌ You are not a registered user.")
        return False
    return True


@command("config fullname", role=Role.USER, aliases=["c fullname"])
async def set_fullname(bot, sender_jid, nick, args, msg, is_room):
    """
    Set your FULLNAME in your profile.

    Usage:
        {prefix}config fullname <your full name>
        {prefix}c fullname <your full name>

    Example:
        {prefix}config fullname Envsi, the example user
    """
    jid = resolve_real_jid(bot, msg, is_room)
    if not await _check_user_exists(bot, jid, msg):
        return
    if not args:
        log.warning("[PROFILE] ❌ FULLNAME missing args for %s", jid)
        bot.reply(
            msg,
            f"⚠️ Usage: {config.get('prefix', ',')}config fullname "
            "<your full name>",
        )
        return
    fullname = " ".join(args).strip()
    if not fullname:
        log.warning("[PROFILE] ❌ FULLNAME empty for %s", jid)
        bot.reply(msg, "⚠️ Please provide a non-empty full name.")
        return
    profile_store = bot.db.users.profile()
    await profile_store.set(str(jid), "FULLNAME", fullname)
    log.info("[PROFILE] ✅ FULLNAME set for %s: %s", jid, fullname)
    bot.reply(msg, f"✅ FULLNAME set to: {fullname}")


@command("config location", role=Role.USER, aliases=["c location"])
async def set_location(bot, sender_jid, nick, args, msg, is_room):
    """
    Set your LOCATION eg. for '{prefix}weather [nick]' command.


    Usage:
        {prefix}config location <your location>
        {prefix}c location <your location>

    Example:
        {prefix}config location Berlin, Germany
    """
    jid = resolve_real_jid(bot, msg, is_room)
    if not await _check_user_exists(bot, jid, msg):
        return
    if not args:
        log.warning("[PROFILE] ❌ LOCATION missing args for %s", jid)
        bot.reply(
            msg,
            f"⚠️ Usage: {config.get('prefix', ',')}config location "
            "<your location>",
        )
        return
    location = " ".join(args).strip()
    if not location:
        log.warning("[PROFILE] ❌ LOCATION empty for %s", jid)
        bot.reply(msg, "⚠️ Please provide a non-empty location.")
        return
    profile_store = bot.db.users.profile()
    await profile_store.set(str(jid), "LOCATION", location)
    log.info("[PROFILE] ✅ LOCATION set for %s: %s", jid, location)
    bot.reply(msg, f"✅ LOCATION set to: {location}")


@command("config timezone", role=Role.USER, aliases=["c timezone"])
async def set_timezone(bot, sender_jid, nick, args, msg, is_room):
    """
    Set your TIMEZONE in Linux format eg. for '{prefix}time [nick]' command.

    Usage:
        {prefix}config timezone <timezone>
        {prefix}c timezone <timezone>

    Example:
        {prefix}config timezone Europe/Berlin
    """
    jid = resolve_real_jid(bot, msg, is_room)
    log.info("[PROFILE] ✅ set_timezone called by %s", jid)
    if not await _check_user_exists(bot, jid, msg):
        return
    if not args or len(args) != 1:
        log.warning("[PROFILE] ❌ TIMEZONE missing/invalid args for %s",
                    jid)
        bot.reply(
            msg,
            f"⚠️ Usage: {config.get('prefix', ',')}config timezone "
            "<timezone>",
        )
        return
    timezone = args[0].strip()
    try:
        if timezone not in pytz.all_timezones:
            raise ValueError
    except Exception:
        log.warning("[PROFILE] ❌ Invalid timezone for %s: %s", jid,
                    timezone)
        bot.reply(
            msg,
            "⚠️ Invalid timezone. Use a valid IANA timezone, "
            "e.g. Europe/Berlin.",
        )
        return
    profile_store = bot.db.users.profile()
    await profile_store.set(str(jid), "TIMEZONE", timezone)
    log.info("[PROFILE] ✅ TIMEZONE set for %s: %s", jid, timezone)
    bot.reply(msg, f"✅ TIMEZONE set to: {timezone}")


@command("config pronouns", role=Role.USER, aliases=["c pronouns"])
async def set_pronouns(bot, sender_jid, nick, args, msg, is_room):
    """
    Set your PRONOUNS in your profile.

    Usage:
        {prefix}config pronouns <your pronouns>
        {prefix}c pronouns <your pronouns>

    Example:
        {prefix}config pronouns they/them
    """
    jid = resolve_real_jid(bot, msg, is_room)
    if not await _check_user_exists(bot, jid, msg):
        return
    if not args:
        log.warning("[PROFILE] ❌ PRONOUNS missing args for %s", jid)
        bot.reply(
            msg,
            f"⚠️ Usage: {config.get('prefix', ',')}config pronouns "
            "<your pronouns>",
        )
        return
    pronouns = " ".join(args).strip()
    if not pronouns:
        log.warning("[PROFILE] ❌ PRONOUNS empty for %s", jid)
        bot.reply(msg, "⚠️ Please provide non-empty pronouns.")
        return
    profile_store = bot.db.users.profile()
    await profile_store.set(str(jid), "PRONOUNS", pronouns)
    log.info("[PROFILE] ✅ PRONOUNS set for %s: %s", jid, pronouns)
    bot.reply(msg, f"✅ PRONOUNS set to: {pronouns}")


@command("config species", role=Role.USER, aliases=["c species"])
async def set_species(bot, sender_jid, nick, args, msg, is_room):
    """
    Set your SPECIES in your profile.

    Usage:
        {prefix}config species <your species>
        {prefix}c species <your species>

    Example:
        {prefix}config species Human
    """
    jid = resolve_real_jid(bot, msg, is_room)
    if not await _check_user_exists(bot, jid, msg):
        return
    if not args:
        log.warning("[PROFILE] ❌ SPECIES missing args for %s", jid)
        bot.reply(
            msg,
            f"⚠️ Usage: {config.get('prefix', ',')}config species "
            "<your species>",
        )
        return
    species = " ".join(args).strip()
    if not species:
        log.warning("[PROFILE] ❌ SPECIES empty for %s", jid)
        bot.reply(msg, "⚠️ Please provide a non-empty species.")
        return
    profile_store = bot.db.users.profile()
    await profile_store.set(str(jid), "SPECIES", species)
    log.info("[PROFILE] ✅ SPECIES set for %s: %s", jid, species)
    bot.reply(msg, f"✅ SPECIES set to: {species}")


@command("config email", role=Role.USER, aliases=["c email"])
async def set_email(bot, sender_jid, nick, args, msg, is_room):
    """
    Set your EMAIL in your profile.

    Usage:
        {prefix}config email <your@email>
        {prefix}c email <your@email>

    Example:
        {prefix}config email daniel@example.org
    """
    jid = resolve_real_jid(bot, msg, is_room)
    if not await _check_user_exists(bot, jid, msg):
        return
    if not args or len(args) != 1:
        log.warning("[PROFILE] ❌ EMAIL missing/invalid args for %s",
                    jid)
        bot.reply(
            msg,
            f"⚠️ Usage: {config.get('prefix', ',')}config email <your@email>",
        )
        return
    email = args[0].strip()
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        log.warning("[PROFILE] ❌ Invalid email for %s: %s", jid, email)
        bot.reply(msg, "⚠️ Please provide a valid email address.")
        return
    profile_store = bot.db.users.profile()
    await profile_store.set(str(jid), "EMAIL", email)
    log.info("[PROFILE] ✅ EMAIL set for %s: %s", jid, email)
    bot.reply(msg, f"✅ EMAIL set to: {email}")


@command("config url", role=Role.USER, aliases=["c url"])
async def config_url(bot, sender_jid, nick, args, msg, is_room):
    """
    Manage up to 6 URLs with descriptions.

    Usage:
        {prefix}config url add <url> [description]
        {prefix}config url list
        {prefix}config url delete <url>
        {prefix}c url add <url> [description]
        {prefix}c url list
        {prefix}c url delete <url>

    Examples:
        {prefix}config url add https://username.example.com/ My homepage
        {prefix}config url list
        {prefix}config url delete https://username.example.com/
    """
    jid = resolve_real_jid(bot, msg, is_room)
    if not await _check_user_exists(bot, jid, msg):
        return

    if not args or args[0] not in ("add", "list", "delete"):
        log.warning("[PROFILE] ❌ Invalid url subcommand for %s: %s",
                    jid, args)
        bot.reply(
            msg,
            f"⚠️ Usage: {config.get('prefix', ',')}config url "
            "<add|list|delete> ...",
        )
        return

    subcmd = args[0]
    profile_store = bot.db.users.profile()
    jid_str = str(jid)
    urls = await profile_store.get(jid_str, "URLS") or []

    if subcmd == "add":
        if len(args) < 2:
            log.warning("[PROFILE] ❌ URL add missing args for %s",
                        jid)
            bot.reply(
                msg,
                f"⚠️ Usage: {config.get('prefix', ',')}config url add "
                "<url> [description]",
            )
            return
        url = args[1]
        if any(c.isspace() for c in url):
            log.warning("[PROFILE] ❌ URL add whitespace in url for %s",
                        jid)
            bot.reply(msg, "⚠️ URL must not contain whitespace.")
            return
        try:
            url_enc = urllib.parse.quote(
                url, safe=":/?#[]@!$&'()*+,;=%"
            )
            parsed = urllib.parse.urlparse(url_enc)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError
        except Exception:
            log.warning("[PROFILE] ❌ Invalid URL for %s: %s", jid, url)
            bot.reply(msg, "⚠️ Invalid URL.")
            return
        description = " ".join(args[2:]).strip() if len(args) > 2 else ""
        urls = [item for item in urls if item[0] != url_enc]
        if len(urls) >= 6:
            log.warning("[PROFILE] ❌ URL add limit reached for %s", jid)
            bot.reply(msg, "⚠️ You can only store up to 6 URLs.")
            return
        urls.append((url_enc, description))
        await profile_store.set(jid_str, "URLS", urls)
        log.info(
            "[PROFILE] ✅ URL added for %s: %s (%s)",
            jid, url_enc, description
        )
        bot.reply(msg, f"✅ URL added: {url_enc} ({description})")
        return

    if subcmd == "list":
        if len(args) != 1:
            log.warning("[PROFILE] ❌ URL list invalid args for %s", jid)
            bot.reply(
                msg,
                f"⚠️ Usage: {config.get('prefix', ',')}config url list",
            )
            return
        if not urls:
            log.info("[PROFILE] ✅ URL list empty for %s", jid)
            bot.reply(msg, "ℹ️ No URLs stored.")
            return
        lines = ["🔗 Your URLs:"]
        for url, desc in urls[:6]:
            if desc:
                lines.append(
                    f"- {urllib.parse.unquote(url)} — {desc}"
                )
            else:
                lines.append(f"- {urllib.parse.unquote(url)}")
        log.info("[PROFILE] ✅ URL list for %s: %s", jid, lines)
        bot.reply(msg, lines)
        return

    if subcmd == "delete":
        if len(args) != 2:
            log.warning("[PROFILE] ❌ URL delete invalid args for %s",
                        jid)
            bot.reply(
                msg,
                f"⚠️ Usage: {config.get('prefix', ',')}config url delete "
                "<url>",
            )
            return
        url = args[1]
        url_enc = urllib.parse.quote(
            url, safe=":/?#[]@!$&'()*+,;=%"
        )
        new_urls = [item for item in urls if item[0] != url_enc]
        if len(new_urls) == len(urls):
            log.warning("[PROFILE] ❌ URL not found for delete for %s: %s",
                        jid, url)
            bot.reply(msg, "⚠️ URL not found.")
            return
        await profile_store.set(jid_str, "URLS", new_urls)
        log.info(
            "[PROFILE] ✅ URL deleted for %s: %s", jid, url_enc
        )
        bot.reply(msg, f"🗑️ URL deleted: {url_enc}")
        return


@command("config birthday", role=Role.USER, aliases=["c birthday"])
async def set_birthday(bot, sender_jid, nick, args, msg, is_room):
    """
    Set your BIRTHDAY in your profile. Format: YYYY-MM-DD or MM-DD.
    Usage:
        {prefix}config birthday <YYYY-MM-DD|MM-DD>
        {prefix}c birthday <YYYY-MM-DD|MM-DD>
    Example:
        {prefix}config birthday 1990-05-23
        {prefix}config birthday 05-23
    """
    import re
    jid = resolve_real_jid(bot, msg, is_room)
    if not await _check_user_exists(bot, jid, msg):
        return
    if not args or len(args) != 1:
        bot.reply(
            msg,
            f"⚠️ Usage: {config.get('prefix', ',')}config birthday" +
            "<YYYY-MM-DD|MM-DD>",
        )
        return
    birthday = args[0].strip()
    if not (re.match(r"^\d{4}-\d{2}-\d{2}$", birthday)
            or re.match(r"^\d{2}-\d{2}$", birthday)):
        bot.reply(msg, "⚠️ Please provide birthday as YYYY-MM-DD or MM-DD.")
        return
    profile_store = bot.db.users.profile()
    await profile_store.set(str(jid), "BIRTHDAY", birthday)
    log.info("[PROFILE] ✅ BIRTHDAY set for %s: %s", jid, birthday)
    bot.reply(msg, f"✅ BIRTHDAY set to: {birthday}")


@command("fullname", role=Role.USER, aliases=["f"])
async def get_fullname(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the FULLNAME of a user.

    Usage:
        {prefix}fullname [nick]
        {prefix}f [nick]

    Example:
        {prefix}fullname Envsi
    """
    await _get_profile_field(bot, sender_jid, nick, args, msg, is_room,
                             "FULLNAME", "Full Name")


@command("pronouns", role=Role.USER, aliases=["p"])
async def get_pronouns(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the PRONOUNS of a user.

    Usage:
        {prefix}pronouns [nick]
        {prefix}p [nick]

    Example:
        {prefix}pronouns Envsi
    """
    await _get_profile_field(bot, sender_jid, nick, args, msg, is_room,
                             "PRONOUNS", "Pronouns")


@command("species", role=Role.USER, aliases=["s"])
async def get_species(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the SPECIES of a user.

    Usage:
        {prefix}species [nick]
        {prefix}s [nick]

    Example:
        {prefix}species Envsi
    """
    await _get_profile_field(bot, sender_jid, nick, args, msg, is_room,
                             "SPECIES", "Species")


@command("email", role=Role.USER, aliases=["e"])
async def get_email(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the EMAIL of a user.

    Usage:
        {prefix}email [nick]
        {prefix}e [nick]

    Example:
        {prefix}email Envsi
    """
    await _get_profile_field(bot, sender_jid, nick, args, msg, is_room,
                             "EMAIL", "Email")


@command("urls", role=Role.USER, aliases=["u"])
async def get_urls(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the URLS of a user.

    Usage:
        {prefix}urls [nick]
        {prefix}u [nick]

    Example:
        {prefix}urls Envsi
    """
    await _get_profile_field(bot, sender_jid, nick, args, msg, is_room,
                             "URLS", "URLs")


# -------------------------------------------------
# Output of information (complex task)
# -------------------------------------------------

def _is_muc_pm(msg):
    return (
        msg.get("type") == "chat"
        and hasattr(msg["from"], "bare")
        and "@" in str(msg["from"].bare)
        and str(msg["from"].bare) in JOINED_ROOMS
    )


def _group_rooms_by_jid(target_nick, joined_rooms):
    """
    Return {jid: [room, ...]} for all rooms where target_nick is present.
    """
    jid_to_rooms = {}
    for room, data in joined_rooms.items():
        nicks = data.get("nicks", {})
        info = nicks.get(target_nick)
        if info and info.get("jid"):
            jid = str(info["jid"])
            jid_to_rooms.setdefault(jid, []).append(room)
    return jid_to_rooms


async def _format_profile_field_for_jid(profile_store, jid, field, label,
                                        display_name, rooms=None):
    value = await profile_store.get(jid, field)
    if field == "URLS":
        lines = []
        if rooms:
            lines.append(f"- {display_name} in {', '.join(rooms)}:")
        else:
            lines.append(f"- {display_name}:")
        if value and isinstance(value, list):
            for url, desc in value:
                if desc:
                    lines.append(f"    • {urllib.parse.unquote(url)} — {desc}")
                else:
                    lines.append(f"    • {urllib.parse.unquote(url)}")
        else:
            lines.append("    • —")
        return lines
    else:
        if value is None or value == "" or value == []:
            value = "—"
        if rooms:
            return [f"- {display_name} in {', '.join(rooms)}: {value}"]
        else:
            return [f"- {display_name}: {value}"]


async def _handle_multiple_nick_matches(bot, target_nick, jids, field, label):
    """
    Format output for multiple JIDs using the same nick, grouped by rooms.
    """
    profile_store = bot.db.users.profile()
    jid_to_rooms = _group_rooms_by_jid(target_nick, JOINED_ROOMS)
    lines = [f"🔎 Multiple users found for nick '{target_nick}':"]
    matched_jids = set()
    for jid, rooms in jid_to_rooms.items():
        matched_jids.add(jid)
        lines.extend(await _format_profile_field_for_jid(profile_store, jid,
                                                         field, label,
                                                         target_nick, rooms))
    # Handle JIDs not present in any joined room (offline, etc.)
    for jid in jids:
        sjid = str(jid)
        if sjid not in matched_jids:
            lines.extend(await _format_profile_field_for_jid(profile_store,
                                                             sjid, field,
                                                             label,
                                                             target_nick,
                                                             None))
    return lines


async def _get_profile_field(bot, sender_jid, nick, args, msg, is_room,
                             field, label):
    """
    Helper to fetch and display a profile field for a user or nick.
    """
    # 1. Room context (groupchat) or MUC PM: lookup nick in room
    user_jid = resolve_real_jid(bot, msg, is_room)
    if (is_room or _is_muc_pm(msg)) and args:
        target_nick = args[0]
        room = msg["from"].bare
        joined = JOINED_ROOMS.get(room, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            log.warning("[PROFILE] ❌ Nick '%s' not found in room '%s'",
                        target_nick, room)
            bot.reply(msg, f"❌ Nick '{target_nick}' not found in this room.")
            return
        target_jid = nick_info.get("jid")
        if not target_jid:
            log.warning("[PROFILE] ❌ No JID for nick '%s' in room '%s'",
                        target_nick, room)
            bot.reply(msg, f"❌ No JID found for nick '{target_nick}'.")
            return
        target_jid = str(target_jid)
        display_name = target_nick
        profile_store = bot.db.users.profile()
        value = await profile_store.get(target_jid, field)
        log.info(f"[PROFILE] {user_jid} looking up {field} for"
                 f"'{target_jid}'")
        if value is None or value == "" or value == []:
            log.warning("[PROFILE] ❌ No %s for requested user '%s'",
                        field, target_jid)
            bot.reply(msg, f"ℹ️ No {label} set for nick '{args[0]}'.")
            return
        if field == "URLS":
            lines = await _format_profile_field_for_jid(profile_store,
                                                        target_jid, field,
                                                        label, display_name,
                                                        [room])
            bot.reply(msg, lines)
        else:
            bot.reply(msg, f"{label} for {display_name}: {value}")
        return

    # 2. Direct message to bot JID: lookup nick globally, group by JID/rooms
    elif not is_room and not _is_muc_pm(msg) and args:
        target_nick = args[0]
        index = bot.db.users._nick_index
        jids = index.get(target_nick, [])
        if not jids:
            log.warning("[PROFILE] ❌ Nick '%s' not found globally",
                        target_nick)
            bot.reply(msg, f"❌ Nick '{target_nick}' not found.")
            return
        if len(jids) > 1:
            lines = await _handle_multiple_nick_matches(bot, target_nick,
                                                        jids, field, label)
            bot.reply(msg, lines)
            return
        # Only one JID found
        target_jid = str(jids[0])
        display_name = target_nick
        profile_store = bot.db.users.profile()
        value = await profile_store.get(target_jid, field)
        log.info(f"[PROFILE] {user_jid} looking up {field} for"
                 f" '{target_jid}'")
        if value is None or value == "" or value == []:
            log.warning("[PROFILE] ❌ No %s for requested user '%s'",
                        field, target_jid)
            bot.reply(msg, f"ℹ️ No {label} set for nick '{args[0]}'.")
            return
        if field == "URLS":
            lines = await _format_profile_field_for_jid(profile_store,
                                                        target_jid, field,
                                                        label, display_name)
            bot.reply(msg, lines)
        else:
            bot.reply(msg, f"{label} for {display_name}: {value}")
        return

    # 3. No args: use requesting user
    else:
        target_jid = resolve_real_jid(bot, msg, is_room)
        display_name = nick
        profile_store = bot.db.users.profile()
        value = await profile_store.get(target_jid, field)
        log.info(f"[PROFILE] {user_jid} looking up {field} for"
                 f" '{target_jid}'")
        if value is None or value == "" or value == []:
            log.warning("[PROFILE] ❌ No %s for requested user '%s'",
                        field, target_jid)
            bot.reply(msg, f"ℹ️ No {label} set for this user.")
            return
        if field == "URLS":
            lines = await _format_profile_field_for_jid(profile_store,
                                                        target_jid, field,
                                                        label, display_name)
            bot.reply(msg, lines)
        else:
            bot.reply(msg, f"{label} for {display_name}: {value}")


@command("birthday", role=Role.USER, aliases=["b"])
async def get_birthday(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the BIRTHDAY of a user and days until next birthday.
    Usage:
        {prefix}birthday [nick]
        {prefix}b [nick]
    Example:
        {prefix}birthday Envsi
    """
    # 1. Room context (groupchat) or MUC PM: lookup nick in room
    if (is_room or _is_muc_pm(msg)) and args:
        target_nick = args[0]
        room = msg["from"].bare
        joined = JOINED_ROOMS.get(room, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            bot.reply(msg, f"❌ Nick '{target_nick}' not found in this room.")
            return
        target_jid = nick_info.get("jid")
        if not target_jid:
            bot.reply(msg, f"❌ No JID found for nick '{target_nick}'.")
            return
        target_jid = str(target_jid)
        display_name = target_nick
    elif not is_room and not _is_muc_pm(msg) and args:
        target_nick = args[0]
        index = bot.db.users._nick_index
        jids = index.get(target_nick, [])
        if not jids:
            bot.reply(msg, f"❌ Nick '{target_nick}' not found.")
            return
        if len(jids) > 1:
            bot.reply(msg, "🔎 Multiple users found for nick " +
                      f"'{target_nick}':\n" +
                      "\n".join(f"- {jid}" for jid in jids))
            return
        target_jid = str(jids[0])
        display_name = target_nick
    else:
        target_jid = resolve_real_jid(bot, msg, is_room)
        display_name = nick
    profile_store = bot.db.users.profile()
    value = await profile_store.get(target_jid, "BIRTHDAY")
    if not value:
        bot.reply(msg, f"ℹ️ No Birthday set for {display_name}.")
        return
    # Calculate days until next birthday
    today = datetime.date.today()
    try:
        if len(value) == 10:  # YYYY-MM-DD
            month = int(value[5:7])
            day = int(value[8:10])
        elif len(value) == 5:  # MM-DD
            month = int(value[0:2])
            day = int(value[3:5])
        else:
            raise ValueError
        this_year = today.year
        next_birthday = datetime.date(this_year, month, day)
        if next_birthday < today:
            next_birthday = datetime.date(this_year + 1, month, day)
        days_left = (next_birthday - today).days
        days_str = f"{days_left} day{'s' if days_left != 1 else ''}"
        bot.reply(msg, f"🎂 Birthday for {display_name}: {value}"
                       + f" ({days_str} until next birthday)")
    except Exception:
        bot.reply(msg, f"🎂 Birthday for {display_name}: {value}")


@command("profile", role=Role.USER, aliases=["whois"])
async def show_profile(bot, sender_jid, nick, args, msg, is_room):
    """
    Show all profile data for yourself or another user by nick.

    Usage:
        {prefix}profile
        {prefix}profile <nick>

    Example:
        {prefix}profile
        {prefix}profile Envsi
    """
    # Determine target JID and display name
    if args:
        # Try to resolve by nick in room or globally
        target_nick = args[0]
        # Room context
        if (
            is_room or (
                msg.get("type") in ["chat", "normal"]
                and hasattr(msg["from"], "bare")
                and "@" in str(msg["from"].bare)
                and str(msg["from"].bare) in JOINED_ROOMS
            )
        ):
            room = msg["from"].bare
            nicks = JOINED_ROOMS.get(room, {}).get("nicks", {})
            info = nicks.get(target_nick)
            if not info or not info.get("jid"):
                log.warning(
                    "[PROFILE] ❌ Nick '%s' not found in room '%s'",
                    target_nick, room
                )
                bot.reply(
                    msg,
                    f"❌ Nick '{target_nick}' not found in this room."
                )
                return
            target_jid = str(info["jid"])
            display_name = target_nick
            log.info(
                "[PROFILE] 👤 Profile lookup for nick '%s' in room '%s'",
                target_nick, room
            )
        else:
            # DM context: lookup globally
            index = bot.db.users._nick_index
            jids = index.get(target_nick, [])
            if not jids:
                log.warning(
                    "[PROFILE] ❌ Nick '%s' not found globally",
                    target_nick
                )
                bot.reply(
                    msg,
                    f"❌ Nick '{target_nick}' not found."
                )
                return
            if len(jids) > 1:
                log.info(
                    "[PROFILE] 🔎 Multiple users found for nick '%s': %s",
                    target_nick, jids
                )
                bot.reply(
                    msg,
                    f"🔎 Multiple users found for nick '{target_nick}':\n"
                    + "\n".join(f"- {jid}" for jid in jids)
                )
                return
            target_jid = str(jids[0])
            display_name = target_nick
            log.info(
                "[PROFILE] 👤 Profile lookup for nick '%s' (global)",
                target_nick
            )
    else:
        # No args: show own profile
        target_jid = resolve_real_jid(bot, msg, is_room)
        display_name = nick
        log.info(
            "[PROFILE] 👤 Profile lookup for self: %s",
            display_name
        )

    profile_store = bot.db.users.profile()
    fields = [
        ("FULLNAME", "Full Name"),
        ("LOCATION", "Location"),
        ("TIMEZONE", "Timezone"),
        ("BIRTHDAY", "Birthday"),
        ("PRONOUNS", "Pronouns"),
        ("SPECIES", "Species"),
        ("EMAIL", "Email"),
        ("URLS", "URLs"),
    ]
    lines = [f"👤 Profile for {display_name}:"]
    for field, label in fields:
        value = await profile_store.get(target_jid, field)
        if field == "URLS":
            if value and isinstance(value, list):
                if value:
                    lines.append(f"- {label}:")
                    for url, desc in value:
                        if desc:
                            lines.append(
                                f"    • {urllib.parse.unquote(url)} — {desc}"
                            )
                        else:
                            lines.append(
                                f"    • {urllib.parse.unquote(url)}"
                            )
                else:
                    lines.append(f"- {label}: —")
            else:
                lines.append(f"- {label}: —")
        else:
            if value is None or value == "" or value == []:
                value = "—"
            lines.append(f"- {label}: {value}")
    log.info(
        "[PROFILE] 📄 Profile output for %s",
        display_name
    )
    bot.reply(msg, lines)
