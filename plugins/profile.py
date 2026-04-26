"""
Profile management plugin.

This plugin allows users to request the Fullname, Nicknames, Birthday, Notes,
Organisations and URLs from their own or others vCard (if public).

It also allows users to set their timezone, which is not supported by vCards.
"""

import slixmpp
from utils.command import command, Role
from utils.config import config
import pytz
import datetime
import re
import logging
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "profile",
    "version": "0.2.0",
    "description": "User profile management",
    "category": "info",
    "requires": ["vcard", "rooms"],
}


def resolve_real_jid(bot, msg, is_room):
    """
    Resolve the real sender JID in all contexts (groupchat, MUC PM, or DM).
    """
    jid = None
    muc = bot.plugin.get("xep_0045", None)
    if muc:
        room = msg['from'].bare
        nick = msg["from"].resource
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
            "[PROFILE] 🔴  Unregistered user tried to use config: %s", jid
        )
        bot.reply(msg, "🔴  You are not a registered user.")
        return False
    return True


async def _unset_field(bot, jid, field_name, label, msg):
    """
    Helper to unset (clear) a profile field.

    Args:
        bot: The bot instance.
        jid: The user's JID.
        field_name: The field key (e.g., "FULLNAME").
        label: The display name (e.g., "Full Name").
        msg: The message object.
    """
    profile_store = bot.db.users.profile()
    await profile_store.set(str(jid), field_name, None)
    log.info("[PROFILE] 🗑️ %s unset for %s", field_name, jid)
    bot.reply(msg, f"🗑️ {label} removed.")


@command("timezone set", role=Role.USER, aliases=["tz set"])
async def set_timezone(bot, sender_jid, nick, args, msg, is_room):
    """
    Set your TIMEZONE in Linux format eg. for '{prefix}time [nick]' command.

    Usage:
        {prefix}timezone set <timezone>
        {prefix}tz set <timezone>

    Example:
        {prefix}timezone set Europe/Berlin
        {prefix}tz set Alaska/Anchorage
    """
    jid = resolve_real_jid(bot, msg, is_room)
    log.info("[PROFILE] ✅ set_timezone called by %s", jid)
    if not await _check_user_exists(bot, jid, msg):
        return
    if not args or len(args) != 1:
        log.warning("[PROFILE] 🔴  TIMEZONE missing/invalid args for %s",
                    jid)
        bot.reply(
            msg,
            f"🟡️ Usage: {config.get('prefix', ',')}config timezone "
            "<timezone>",
        )
        return
    timezone = args[0].strip()
    try:
        if timezone not in pytz.all_timezones:
            raise ValueError
    except Exception:
        log.warning("[PROFILE] 🔴  Invalid timezone for %s: %s", jid,
                    timezone)
        bot.reply(
            msg,
            "🟡️ Invalid timezone. Use a valid IANA timezone, "
            "e.g. Europe/Berlin.",
        )
        return
    profile_store = bot.db.users.profile()
    await profile_store.set(str(jid), "TIMEZONE", timezone)
    log.info("[PROFILE] ✅ TIMEZONE set for %s: %s", jid, timezone)
    bot.reply(msg, f"✅ TIMEZONE set to: {timezone}")


@command("config birthday", role=Role.USER, aliases=["c birthday"])
async def set_birthday(bot, sender_jid, nick, args, msg, is_room):
    """
    Set your BIRTHDAY in your profile. Format: YYYY-MM-DD or MM-DD.
    Birthday must not be in the future.

    Usage:
        {prefix}config birthday <YYYY-MM-DD|MM-DD>
        {prefix}c birthday <YYYY-MM-DD|MM-DD>

    Example:
        {prefix}config birthday 1990-05-23
        {prefix}config birthday 05-23
    """
    jid = resolve_real_jid(bot, msg, is_room)
    if not await _check_user_exists(bot, jid, msg):
        return
    if not args or len(args) != 1:
        bot.reply(
            msg,
            f"🟡️ Usage: {config.get('prefix', ',')}config birthday " +
            "<YYYY-MM-DD|MM-DD>",
        )
        return
    birthday = args[0].strip()
    if not (re.match(r"^\d{4}-\d{2}-\d{2}$", birthday)
            or re.match(r"^\d{2}-\d{2}$", birthday)):
        bot.reply(msg, "🟡️ Please provide birthday as YYYY-MM-DD or MM-DD.")
        return

    # Validate that birthday is not in the future
    today = datetime.date.today()
    try:
        if len(birthday) == 10:  # YYYY-MM-DD
            year = int(birthday[0:4])
            month = int(birthday[5:7])
            day = int(birthday[8:10])
            birthday_date = datetime.date(year, month, day)
            if birthday_date > today:
                bot.reply(msg, "🟡️ Birthday cannot be in the future.")
                return
        elif len(birthday) == 5:  # MM-DD
            month = int(birthday[0:2])
            day = int(birthday[3:5])
            # For MM-DD format, check if the date is valid but don't check future
            # (since we don't have year, we can't determine if it's in the future)
            try:
                datetime.date(today.year, month, day)
            except ValueError:
                bot.reply(msg, "🟡️ Invalid date.")
                return
    except ValueError:
        bot.reply(msg, "🟡️ Invalid date.")
        return

    profile_store = bot.db.users.profile()
    await profile_store.set(str(jid), "BIRTHDAY", birthday)
    log.info("[PROFILE] ✅ BIRTHDAY set for %s: %s", jid, birthday)
    bot.reply(msg, f"✅ BIRTHDAY set to: {birthday}")


# -------------------------------------------------
# Output of information (complex task)
# -------------------------------------------------

def _is_muc_pm(msg):
    return (
        msg.get("type") in ("chat", "normal")
        and hasattr(msg["from"], "bare")
        and "@" in str(msg["from"].bare)
        and str(msg["from"].bare) in JOINED_ROOMS
    )


@command("config unset", role=Role.USER, aliases=["c unset"])
async def unset_field(bot, sender_jid, nick, args, msg, is_room):
    """
    Unset (clear) a profile field from the bots database.

    Usage:
        {prefix}config unset <field>
        {prefix}c unset <field>

    Available fields:
        fullname, location, timezone, birthday, pronouns, species, email, urls

    Example:
        {prefix}config unset fullname
        {prefix}config unset birthday
    """
    jid = resolve_real_jid(bot, msg, is_room)
    if not await _check_user_exists(bot, jid, msg):
        return

    if not args or len(args) != 1:
        log.warning("[PROFILE] 🔴  UNSET missing/invalid args for %s", jid)
        bot.reply(
            msg,
            f"🟡️ Usage: {config.get('prefix', ',')}config unset "
            "<field>\n"
            "Available fields: fullname, location, timezone, birthday, "
            "pronouns, species, email, urls",
        )
        return

    field_arg = args[0].lower().strip()

    field_map = {
        "fullname": ("FULLNAME", "Full Name"),
        "location": ("LOCATION", "Location"),
        "timezone": ("TIMEZONE", "Timezone"),
        "birthday": ("BIRTHDAY", "Birthday"),
        "pronouns": ("PRONOUNS", "Pronouns"),
        "species": ("SPECIES", "Species"),
        "email": ("EMAIL", "Email"),
        "urls": ("URLS", "URLs"),
    }

    if field_arg not in field_map:
        log.warning("[PROFILE] 🔴  Invalid field for unset for %s: %s",
                    jid, field_arg)
        bot.reply(
            msg,
            f"🟡️ Unknown field '{field_arg}'.\n"
            "Available fields: fullname, location, timezone, birthday, "
            "pronouns, species, email, urls",
        )
        return

    field_name, label = field_map[field_arg]
    await _unset_field(bot, jid, field_name, label, msg)
