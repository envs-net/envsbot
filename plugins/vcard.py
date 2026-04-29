"""
vCard Lookup Plugin

This plugin allows users to request the fullname, nicknames, birthday,
notes, organisations and urls from their own or others vCard (if public).

The only exception is the "timezone", which has to be set explicitly with the
"{prefix}tz set <IANA timezone>".

You can get your own timezone from the list at:
https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
Use the "TZ identiier" from the list.

The weather plugin now uses the "LOCATION" and/or "CTRY" (country) fields from
your vCard to determine the location for weather reports, if set. If you have
more than one address the first one found will be used.

IMPORTANT: You may have to activate the vcard commands if not activated by
default with the command:
    {prefix}vcard on

"""

import logging
import textwrap
import pytz
import datetime
import urllib
import slixmpp
from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS
from utils.plugin_helper import handle_room_toggle_command

VCARD_KEY = "VCARD"

PLUGIN_META = {
    "name": "vcard",
    "version": "0.3.1",
    "description": "Lookup and display vCard of a MUC occupant by MUC JID only",
    "category": "info",
    "requires": ["rooms"],
}

log = logging.getLogger(__name__)


def _is_muc_pm(msg):
    """Returns True if msg is a MUC direct message (not public groupchat)."""
    return (
        msg.get("type") in ("chat", "normal")
        and hasattr(msg["from"], "bare")
        and "@" in str(msg["from"].bare)
        and str(msg["from"].bare) in JOINED_ROOMS
    )


def resolve_real_jid(bot, msg, is_room):
    """
    Resolve the real sender JID in all contexts (groupchat, MUC PM, or DM).
    """
    jid = None
    muc = bot.plugin.get("xep_0045", None)
    if muc:
        room = msg['from'].bare
        nick = msg["from"].resource
        log.debug("[VCARD] Resolving real JID for room: %s, nick: %s",
                  room, nick)
        jid = muc.get_jid_property(room, nick, "jid")
    if jid is None:
        jid = msg["from"]
    return str(slixmpp.JID(jid).bare)


async def get_real_jid_from_nick(bot, nick):
    """Look up the real JID of a nick from the UserManager's _nick_index."""
    idx = getattr(bot.db.users, "_nick_index", {})
    value = idx.get(nick)
    if isinstance(value, set):
        return next(iter(value), None)
    if isinstance(value, list):
        return value[0] if value else None
    return value or None


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
            "[VCARD] 🔴  Unregistered user tried to use config: %s", jid
        )
        bot.reply(msg, "🔴  You are not a registered user.")
        return False
    return True


async def vcard_field(bot, msg, target_nick, field, is_room=False):
    """
    Helper to fetch a specific vCard field(s) for a given nick.
    Must be called from MUC PM or groupchat context with a valid
    target_nick present in the room.

    Supports fields: "FN", "NICKNAME", "BDAY", "TIMEZONE", "URL", "ORG",
    "NOTE", "EMAIL".

    Returns "None" if field is not present.
    """
    if field not in ["FN", "NICKNAME", "BDAY", "TIMEZONE", "URL", "NICKNAME",
                    "ORG", "NOTE", "EMAIL", "LOCALITY", "CTRY"]:
        log.warning("[VCARD] 🔴  Invalid vCard field requested: %s", field)
        return None
    if field == "TIMEZONE":
        store = await get_vcard_store(bot)
        if not is_room and not _is_muc_pm(msg):
            jid = msg["from"].bare
        else:
            jid = JOINED_ROOMS.get(msg["from"].bare, {}).get("nicks", {}).get(target_nick, {}).get("jid")
        if not jid:
            log.warning(f"[VCARD] 🔴  Nick '{target_nick}' not found in room"
                        f"'{msg['from'].bare}' for TIMEZONE lookup")
            return None
        value = await store.get(str(jid), "TIMEZONE")
        if jid == msg["from"].bare:
            log.info(f"[VCARD] TIMEZONE lookup for sender's own JID '{jid}': {value}")
        else:
            log.info(f"[VCARD] TIMEZONE lookup for nick '{target_nick}'"
                     f" with JID '{jid}' in room '{msg['from'].bare}': {value}")
        if not value:
            return None
        return value
    vcard_info = await get_vcard(bot, msg, target_nick, is_room=is_room)
    _, vcard = _format_vcard_reply(vcard_info, None, None)
    return vcard[field]


@command("timezone set", role=Role.USER, aliases=["tz set"])
async def set_timezone(bot, sender_jid, nick, args, msg, is_room):
    """
    Set your TIMEZONE in Linux format eg. for '{prefix}time [nick]' command.

    Check your timezone at:
    https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
    Use the "TZ identiier" from the list.

    Usage:
        {prefix}timezone set <timezone>
        {prefix}tz set <timezone>

    Example:
        {prefix}timezone set Europe/Berlin
        {prefix}tz set Alaska/Anchorage
    """
    # Check, if command is allowed in this context (room or MUC PM)
    store = await get_vcard_store(bot)
    enabled_rooms = await store.get_global(VCARD_KEY, default={})
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        return

    if not is_room and not _is_muc_pm(msg):
        jid = msg["from"].bare
    else:
        jid = resolve_real_jid(bot, msg, is_room)
    log.info("[VCARD] ✅ set_timezone called by %s", jid)
    if not await _check_user_exists(bot, jid, msg):
        return
    if not args or len(args) != 1:
        log.warning("[VCARD] 🔴  TIMEZONE missing/invalid args for %s",
                    jid)
        bot.reply(
            msg,
            f"🟡️ Usage: {config.get('prefix', ',')}tz set <timezone>",
        )
        return
    timezone = args[0].strip()
    try:
        if timezone not in pytz.all_timezones:
            raise ValueError
    except Exception:
        log.warning("[VCARD] 🔴  Invalid timezone for %s: %s", jid,
                    timezone)
        bot.reply(
            msg,
            "🟡️ Invalid timezone. Use a valid IANA timezone, "
            "e.g. Europe/Berlin.",
        )
        return
    store = await get_vcard_store(bot)
    await store.set(str(jid), "TIMEZONE", timezone)
    log.info("[VCARD] ✅ TIMEZONE set for %s: %s", jid, timezone)
    bot.reply(msg, f"✅ TIMEZONE set to: {timezone}")


async def _format_vcard_field_for_nick(field, label, values,
                                       display_name, rooms=None):
    def indent_lines(lines, indent="    "):
        return [lines[0]] + [indent + l if l.strip() else l for l in lines[1:]]

    if field == "URL":
        lines = []
        if rooms:
            lines.append(f"{label} - {display_name} in {', '.join(rooms)}:")
        else:
            lines.append(f"{label} - {display_name}:")
        if values and isinstance(values, list):
            for v in values:
                lines.append(f"    • {urllib.parse.unquote(v)}")
        else:
            lines.append("    • —")
        return lines
    elif field in ["EMAIL", "NICKNAME", "ORG", "NOTE"]:
        lines = []
        if rooms:
            lines.append(f"{label} - {display_name} in {', '.join(rooms)}:")
        else:
            lines.append(f"{label} - {display_name}:")
        if values and isinstance(values, list):
            for v in values:
                if field == "NOTE":
                    # Preserve newlines in notes, wrap and indent 
                    # each paragraph after the bullet
                    note_paragraphs = v.splitlines() or [""]
                    for i, para in enumerate(note_paragraphs):
                        wrapped = textwrap.wrap(para, width=70)
                        if not wrapped:
                            wrapped = [""]
                        for j, line in enumerate(wrapped):
                            if i == 0 and j == 0:
                                lines.append(f"    • {line}")
                            else:
                                lines.append(f"      {line}")
                else:
                    lines.append(f"    • {v}")
        else:
            lines.append("    • —")
        return lines
    else:
        # For any other field, output the value(s) in a readable way
        lines = []
        if rooms:
            lines.append(f"{label} - {display_name} in {', '.join(rooms)}:")
        else:
            lines.append(f"{label} - {display_name}:")
        if values is None or values == "" or values == []:
            lines.append("    • —")
        elif isinstance(values, list):
            for v in values:
                lines.append(f"    • {v}")
        else:
            lines.append(f"    • {values}")
        return lines


async def _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           field, label):
    """
    Helper to fetch and display a profile field for a user nick.
    """
    # 1. Room context (groupchat) or MUC PM: lookup nick in room
    if (is_room or _is_muc_pm(msg)) and args:
        target_nick = " ".join(args).strip()
        room = msg["from"].bare
        joined = JOINED_ROOMS.get(room, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            log.warning("[VCARD] 🔴  Nick '%s' not found in room '%s'",
                        target_nick, room)
            bot.reply(msg, f"🔴  Nick '{target_nick}' not found in this room.")
            return
        if field == "TIMEZONE":
            store = bot.db.users.plugin("vcard")
            jid = JOINED_ROOMS.get(room, {}).get("nicks", {}).get(target_nick, {}).get("jid")
            value = await store.get(str(jid), "TIMEZONE")
            log.info(f"[VCARD] TIMEZONE lookup for nick '{target_nick}' with JID '{jid}' in room '{room}': {value}")
        else:
            _, vcard = await get_info(bot, msg, target_nick, is_room=is_room)
            value = vcard[field]
        if value is None or value == "" or value == []:
            log.warning("[VCARD] 🔴  No vCard field '%s' for nick '%s' in room '%s'",
                        label, target_nick, room)
            bot.reply(msg, f"🔴  No {label} found in vCard for nick '{target_nick}'.")
            return
        display_name = target_nick
        log.info(f"[VCARD] {sender_jid} looking up {field} for "
                 f"'{target_nick}'")
        if value is None or value == "" or value == []:
            log.warning("[VCARD] 🔴  No %s for requested user '%s'",
                        field, target_nick)
            bot.reply(msg, f"ℹ️ No {label} set for nick '{target_nick}'.")
            return
        if field in ["FN", "NICKNAME", "BDAY", "TIMEZONE", "URL", "NICKNAME",
                     "ORG", "NOTE", "EMAIL"]:
            lines = await _format_vcard_field_for_nick(field, label,
                                                        value,
                                                        display_name,
                                                        [room])

            bot.reply(msg, lines)
        return
    # 2. Request own vCard information
    elif (is_room or _is_muc_pm(msg)) and not args:
        target_nick = msg["from"].resource
        room = msg["from"].bare
        joined = JOINED_ROOMS.get(room, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            log.warning("[VCARD] 🔴  Nick '%s' not found in room '%s'",
                        target_nick, room)
            bot.reply(msg, f"🔴  Your Nick '{target_nick}' not found in this room.")
            return
        if field == "TIMEZONE":
            store = bot.db.users.plugin("vcard")
            jid = resolve_real_jid(bot, msg, is_room)
            value = await store.get(str(jid), "TIMEZONE")
        else:
            _, vcard = await get_info(bot, msg, target_nick, is_room=is_room)
            if vcard[field] is None:
                log.warning("[VCARD] 🔴  No vCard field '%s' for nick '%s' in room '%s'",
                            label, target_nick, room)
                bot.reply(msg, f"🔴  No {label} found in vCard for nick '{target_nick}'.")
                return
            value = vcard[field]
        display_name = target_nick
        log.info(f"[VCARD] {sender_jid} looking up {field} for"
                 f"'{target_nick}'")
        if value is None or value == "" or value == []:
            log.warning("[VCARD] 🔴  No %s for requested user '%s'",
                        field, target_nick)
            bot.reply(msg, f"ℹ️ No {label} set for nick '{target_nick}'.")
            return
        if field in ["FN", "NICKNAME", "BDAY", "TIMEZONE", "URL", "NICKNAME",
                     "ORG", "NOTE", "EMAIL"]:
            lines = await _format_vcard_field_for_nick(field, label,
                                                        value,
                                                        display_name,
                                                        [room])
            bot.reply(msg, lines)

        else:
            bot.reply(msg, f"{label} for {display_name}: {value}")
        return

    # 2. Direct message to bot JID: lookup nick globally, group by JID/rooms
    else:
        target_nick = msg["from"].bare
        room = "Direct Message"
        if args:
            log.info(f"[VCARD] Direct message with args from '{msg['from'].bare}'")
            bot.reply(msg, "🔴  In direct messages, you can only look up your own vCard. Use the command without args.")
            return
        if field == "TIMEZONE":
            store = bot.db.users.plugin("vcard")
            jid = msg["from"].bare
            value = await store.get(str(jid), "TIMEZONE")
        else:
            _, vcard = await get_info(bot, msg, target_nick, is_room=False)
            if vcard[field] is None:
                log.warning("[VCARD] 🔴  No vCard field '%s' for nick '%s' in room '%s'",
                            label, target_nick, room)
                bot.reply(msg, f"🔴  No {label} found in vCard for nick '{target_nick}'.")
                return
            value = vcard[field]
        display_name = target_nick
        log.info(f"[VCARD] {sender_jid} looking up {field} for"
                 f"'{target_nick}'")
        if value is None or value == "" or value == []:
            log.warning("[VCARD] 🔴  No %s for requested user '%s'",
                        field, target_nick)
            bot.reply(msg, f"ℹ️ No {label} set for nick '{target_nick}'.")
            return
        if field in ["FN", "NICKNAME", "BDAY", "TIMEZONE", "URL", "NICKNAME",
                     "ORG", "NOTE", "EMAIL"]:
            lines = await _format_vcard_field_for_nick(field, label,
                                                        value,
                                                        display_name,
                                                        [room])
            bot.reply(msg, lines)

        else:
            bot.reply(msg, f"{label} for {display_name}: {value}")
        return


async def get_vcard(bot, msg, target_nick, is_room=False):
    """
    Helper function to fetch vCard for a given JID using the xep_0054 plugin.
    """
    if is_room or _is_muc_pm(msg):
        print(f"[VCARD] get_vcard called with target_nick: {target_nick} in room context")
        room = msg["from"].bare  # MUC JID
        joined = JOINED_ROOMS.get(room, {})
        nicks = joined.get("nicks", {})
        if target_nick not in nicks:
            log.info(f"[VCARD] Lookup failed: Nick '{target_nick}' not found in room {room}")
            return None

        jid = f"{room}/{target_nick}"
        log.info(f"[VCARD] Attempting vCard lookup for nick '{target_nick}' with MUC JID '{jid}' in room '{room}'")
    else:
        jid = str(msg["from"].bare)
        log.info(f"[VCARD] Attempting vCard lookup for direct message sender JID '{jid}'")

    try:
        vcard_plugin = bot.plugin.get("xep_0054", None)
        if not vcard_plugin:
            raise RuntimeError("vCard support (xep_0054) is not enabled in this bot.")
        result = await vcard_plugin.get_vcard(jid=jid, cached=False, timeout=10)
        if not result:
            log.info(f"[VCARD] No vCard result for {target_nick if
                     msg['to'].bare != bot.boundjid.bare else ''} '{jid}'.")
            return None
        log.info(f"[VCARD] ✅ vCard for {target_nick if msg['to'].bare !=
                 bot.boundjid.bare else ''} '{jid}' received.")
        return result["vcard_temp"]
    except Exception as e:
        log.error(f"[VCARD] Exception during vCard lookup for '{target_nick}' ({jid}): {e}")
        raise


async def get_info(bot, msg, target_nick, is_room=False):
    jid = None
    if is_room or _is_muc_pm(msg):
        muc_jid = msg["from"].bare
        try:
            vcard_info = await get_vcard(bot, msg, target_nick,is_room=is_room)
            if not vcard_info:
                bot.reply(msg, f"ℹ️ No vCard found for {target_nick}.")
                log.info(f"[VCARD] No vCard found for '{target_nick}'.")
                return None, None

            _, vcard = _format_vcard_reply(vcard_info, target_nick, muc_jid)

        except Exception as e:
            bot.reply(msg, f"🔴 Failed to fetch vCard for {target_nick}: {e}")
            log.error(f"[VCARD] Exception during vCard lookup for '{target_nick}': {e}")
            return None, None
        if not vcard:
            log.warning(f"[VCARD] Lookup failed: No vCard found for sender's nick '{target_nick}'.")
            bot.reply(msg, f"🔴  Your vcard for '{target_nick}' not found in this room.")
            return None, None
        return target_nick, vcard
    else:
        jid = msg["from"].bare
        try:
            vcard_info = await get_vcard(bot, msg, None, is_room=False)
            if not vcard_info:
                bot.reply(msg, f"ℹ️ No vCard found for {jid}.")
                log.info(f"[VCARD] No vCard found for '{jid}'.")
                return None, None

            _, vcard = _format_vcard_reply(vcard_info, None, None)

        except Exception as e:
            log.error(f"[VCARD] Exception during vCard lookup for '{jid}': {e}")
            bot.reply(msg, f"🔴 Failed to fetch vCard for '{jid}': {e}")
            return None, None
        if not vcard:
            lwarn = f"[VCARD] Lookup failed: No vCard found for sender '{jid}'"
            log.warm(lwarn)
            wmsg = f"🔴  Your vcard for '{jid}' was not found."
            return None, None
        return target_nick, vcard



def _get_all_field_values_by_tag(vcard, tag):
    """
    Extract all string values for the field 'tag' from vcard stanza children.
    """
    values = []
    for child in vcard.xml:
        # Check both namespace-tag form and plain tag
        if child.tag.endswith(tag) and child.text:
            values.append(child.text.strip())
    return values


def _get_nested_field_values_by_tag(vcard, parent_tag, child_tag):
    """Get all child_tag values under parent_tag elements in vcard XML."""
    values = []
    for field in vcard.xml:
        if field.tag.endswith(parent_tag):
            for child in field:
                if child.tag.endswith(child_tag) and child.text:
                    values.append(child.text.strip())
    return values


def _extract_email_addresses(vcard):
    """Extract USERID from all EMAIL fields in the vCard XML."""
    emails = []
    for child in vcard.xml:
        if child.tag.endswith("EMAIL"):
            # Find USERID child element within the EMAIL
            for email_child in child:
                if email_child.tag.endswith("USERID") and email_child.text:
                    # find USERID element and extract email address
                    for email_child in child:
                        if (email_child.tag.endswith("USERID")
                                and email_child.text):
                            emails.append(email_child.text.strip())
    return emails


def _format_vcard_reply(vcard, nick, muc_jid):
    # log vcard.xml to file
    # log.info("[VCARD] Raw vCard XML: %s",
    #          ET.tostring(vcard.xml, encoding="unicode"))
    c = {}
    lines = [f"📄 vCard for {nick} ({muc_jid}):"]

    fn = vcard.get("FN")
    c["FN"] = None
    if fn:
        lines.append(f"• Name: {fn}")
        c["FN"] = fn
    nicknames = _get_all_field_values_by_tag(vcard, "NICKNAME")
    c["NICKNAME"] = []
    if nicknames:
        lines.append(f"• Nicknames: {nicknames}")
        c["NICKNAME"] = nicknames
    c["BDAY"] = None
    bday = vcard["BDAY"]
    if bday:
        lines.append(f"• Birthday: {bday}")
        c["BDAY"] = bday

    # All URLs
    c["URL"] = []
    urls = _get_all_field_values_by_tag(vcard, "URL")
    if urls:
        lines.append("")
        c["URL"] = urls
    for url in urls:
        lines.append(f"• URL: {url}")

    c["ORG"] = []
    org_names = _get_nested_field_values_by_tag(vcard, "ORG", "ORGNAME")
    if org_names:
        lines.append("")
        for org in org_names:
            lines.append(f"• Organization: {org}")
            c["ORG"].append(org)

    # All Notes with wrapping
    c["NOTE"] = []
    notes = _get_all_field_values_by_tag(vcard, "NOTE")
    if notes:
        lines.append("")
        c["NOTE"] = notes
    for note in notes:
        note_paragraphs = note.splitlines() or [""]
        first_line = True
        for para in note_paragraphs:
            wrapped = textwrap.wrap(para, width=70)
            if not wrapped:
                wrapped = [""]
            for i, line in enumerate(wrapped):
                if first_line:
                    lines.append(f"• Note: {line}")
                    first_line = False
                else:
                    lines.append(f"        {line}")

    # Multiple emails support
    c["EMAIL"] = []
    emails = _extract_email_addresses(vcard)
    if emails:
        lines.append("")
        c["EMAIL"] = emails
        for email_addr in emails:
            lines.append(f"• Email: {email_addr}")

    adr = vcard.get("ADR")
    c["LOCALITY"] = None
    c["CTRY"] = None
    if adr:
        locality = adr.get("LOCALITY")
        if locality:
            lines.append("")  # Blank line before address
            c["LOCALITY"] = locality
        ctry = adr.get("CTRY")
        c["CTRY"] = ctry
        vals = [val for val in (locality, ctry) if val]
        if vals:
            lines.append(f"• Address: {' '.join(vals)}")

    if len(lines) == 1:
        lines.append("  (no public vCard fields found)")
    return lines, c


async def get_vcard_store(bot):
    return bot.db.users.plugin("vcard")


@command("vcard", role=Role.USER, aliases=["v"])
async def vcard_command(bot, sender_jid, sender_nick, args, msg, is_room):
    """
    Look up the vCard of a user by MUC nick (MUC JID only), never real JID!

    Usage: {prefix}vcard [<nick>|on|off|status]

    IMPORTANT: You may have to activate the vcard commands if not activated
    by default with the command:
        {prefix}vcard on

    Usage:
        {prefix}vcard on|off|status
            - Enable, disable or check status of vCard commands in this room.
        {prefix}vcard [nick]
            - Look up the vCard of a user by their MUC nickname in this room.
              or omit the nick for your own vCard

    """

    jid = None
    if is_room or _is_muc_pm(msg):
        handled = await handle_room_toggle_command(
            bot,
            msg,
            is_room,
            args,
            store_getter=get_vcard_store,
            key=VCARD_KEY,
            label="Get vCard data",
            storage="dict",
            log_prefix="[VCARD]",
        )
        if handled:
            return

    store = await get_vcard_store(bot)
    enabled_rooms = await store.get_global(VCARD_KEY, default={})

    if (is_room or _is_muc_pm(msg)) and not args:
        muc_jid = msg["from"].bare
        target_nick = sender_nick

        if muc_jid not in enabled_rooms:
            return
    elif (is_room or _is_muc_pm(msg)) and args:
        target_nick = " ".join(args).strip()
        muc_jid = f"{msg['from'].bare}"

        if muc_jid not in enabled_rooms:
            return
    else:
        # DM context: lookup sender's own vCard by JID
        if args:
            log.info(f"[VCARD] Direct message with args from '{msg['from'].bare}'")
            bot.reply(msg, "🔴  In direct messages, you can only look up your own vCard. Use the command without args.")
            return
        jid = msg["from"].bare
        target_nick = jid
        muc_jid = "Direct Message"

    try:
        vcard = await get_vcard(bot, msg, target_nick, is_room=is_room)

        if not vcard:
            bot.reply(msg, f"ℹ️ No vCard found for {target_nick} ({muc_jid}).")
            log.info(f"[VCARD] No vCard found for '{target_nick}' ({muc_jid})")
            return

        lines, vcard = _format_vcard_reply(vcard, target_nick, muc_jid)

        # add Timezone from DB if available
        store = await get_vcard_store(bot)
        timezone = None
        if is_room or _is_muc_pm(msg):
            if args:
                jid = JOINED_ROOMS.get(muc_jid, {}).get("nicks", {}).get(target_nick, {}).get("jid")
                if jid:
                    timezone = await store.get(str(jid), "TIMEZONE")
            else:
                timezone = await store.get(resolve_real_jid(bot, msg, is_room), "TIMEZONE")
        else:
            timezone = await store.get(str(jid), "TIMEZONE")
        if timezone:
            lines.append("")  # Blank line before timezone
            lines.append(f"• Timezone: {timezone}")

        bot.reply(msg, lines)
    except Exception as e:
        bot.reply(msg, f"🔴 Failed to fetch vCard for {target_nick}: {e}")
        log.error(f"[VCARD] Exception during vCard lookup for '{target_nick}' ({muc_jid}): {e}")


@command("fullname", role=Role.USER, aliases=["f"])
async def get_fullname(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the FULLNAME of a user from their vCard.

    Usage:
        {prefix}fullname [nick]
        {prefix}f [nick]

    Example:
        {prefix}fullname Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    store = await get_vcard_store(bot)
    enabled_rooms = await store.get_global(VCARD_KEY, default={})
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                             "FN", "Full Name")


@command("nicknames", role=Role.USER, aliases=["nicks"])
async def get_nicknames(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the nicknames from a user's vCard.

    Usage:
        {prefix}nicknames [nick]
        {prefix}nicks [nick]

    Example:
        {prefix}nicknames Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    store = await get_vcard_store(bot)
    enabled_rooms = await store.get_global(VCARD_KEY, default={})
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                             "NICKNAME", "Nicknames")


@command("timezone", role=Role.USER, aliases=["tz"])
async def get_timezone(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the TIMEZONE of a user from their DB entry (TZ not available
    on vCard).

    Usage:
        {prefix}timezone [nick]
        {prefix}tz [nick]

    Example:
        {prefix}timezone Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    store = await get_vcard_store(bot)
    enabled_rooms = await store.get_global(VCARD_KEY, default={})
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                             "TIMEZONE", "Timezone")

@command("organisations", role=Role.USER, aliases=["orgs"])
async def get_organisations(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the organisations from a user's vCard.

    Usage:
        {prefix}organisations [nick]
        {prefix}orgs [nick]

    Example:
        {prefix}orgs Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    store = await get_vcard_store(bot)
    enabled_rooms = await store.get_global(VCARD_KEY, default={})
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                             "ORG", "Organisations")


@command("notes", role=Role.USER)
async def get_notes(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the notes from a user's vCard.

    Usage:
        {prefix}notes [nick]

    Example:
        {prefix}notes Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    store = await get_vcard_store(bot)
    enabled_rooms = await store.get_global(VCARD_KEY, default={})
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                             "NOTE", "Notes")


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
    # Check, if command is allowed in this context (room or MUC PM)
    store = await get_vcard_store(bot)
    enabled_rooms = await store.get_global(VCARD_KEY, default={})
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                             "EMAIL", "Emails")


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
    # Check, if command is allowed in this context (room or MUC PM)
    store = await get_vcard_store(bot)
    enabled_rooms = await store.get_global(VCARD_KEY, default={})
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                             "URL", "URLs")


@command("birthday", role=Role.USER, aliases=["b"])
async def get_birthday(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the BIRTHDAY of a user and days until next birthday from their vCard.

    Usage:
        {prefix}birthday [nick]
        {prefix}b [nick]
    Example:
        {prefix}birthday Envsi
    """
    jid = None
    # Check, if command is allowed in this context (room or MUC PM)
    store = await get_vcard_store(bot)
    enabled_rooms = await store.get_global(VCARD_KEY, default={})
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        return

    # 1. Room context (groupchat) or MUC PM: lookup nick in room
    if (is_room or _is_muc_pm(msg)) and args:
        target_nick = " ".join(args).strip()
        room = msg["from"].bare
        joined = JOINED_ROOMS.get(room, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            bot.reply(msg, f"🔴  Nick '{target_nick}' not found in this room.")
            return
        display_name = target_nick
    elif (is_room or _is_muc_pm(msg)) and not args:
        target_nick = msg["from"].resource
        room = msg["from"].bare
        joined = JOINED_ROOMS.get(room, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            bot.reply(msg, f"🔴  Your Nick '{target_nick}' not found in this room.")
            return
        display_name = target_nick
    else:
        if args:
            log.info(f"[VCARD] Direct message with args from '{msg['from'].bare}'")
            bot.reply(msg, "🔴  In direct messages, you can only look up your own birthday. Use the command without args.")
            return
        target_nick = None
        room = None
        jid = msg["from"].bare
        display_name = jid

    _, vcard = await get_info(bot, msg, target_nick, is_room=is_room)
    value = None
    if vcard["BDAY"] is not None:
        value = vcard["BDAY"]
    if value is None or value == "" or value == []:
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
