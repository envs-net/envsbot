"""Split module for plugins/vcard.py: commands."""

import datetime
from slixmpp.exceptions import IqError
from core_plugins import _core
from utils.command import command, Role
from utils.config import config
from core_plugins.rooms import JOINED_ROOMS


async def _vcard_handle_room_lookup(bot, sender_jid, msg, field, label,
                                    target_nick, room, own=False):
    nick_info = _vcard_get_joined_nick_info(room, target_nick)
    if not nick_info:
        log.warning("[VCARD] 🔴  Nick '%s' not found in room '%s'",
                    target_nick, room)
        _vcard_handle_missing_nick(bot, msg, target_nick, room, own=own)
        return

    jid = nick_info.get("jid")
    value = await _vcard_fetch_value(bot, msg, field, jid)
    if field == "TIMEZONE":
        if own:
            log.info(f"[VCARD] TIMEZONE lookup for nick '{target_nick}'"
                     f" with JID '{jid}' in room '{room}': {value}")
        else:
            log.info(f"[VCARD] TIMEZONE lookup for nick '{target_nick}'"
                     f" with JID '{jid}' in room '{room}': {value}")

    if _vcard_value_is_empty(value):
        log.warning("[VCARD] 🔴  No vCard field '%s' for nick '%s'"
                    " in room '%s'",
                    label, target_nick, room)
        _vcard_reply_missing_field(bot, msg, label, target_nick, room)
        return

    display_name = target_nick
    if _vcard_value_is_empty(value):
        log.warning("[VCARD] 🔴  No %s for requested user '%s'",
                    field, target_nick)
        _vcard_reply_empty_requested_user(bot, msg, label, target_nick)
        return

    await _vcard_reply_result(bot, msg, sender_jid, field, label, value,
                              display_name, room)


async def _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           field, label):
    """
    Helper to fetch and display a profile field for a user nick.
    """
    is_muc_context = is_room or _core._is_muc_pm(msg)

    if is_muc_context and args:
        target_nick = " ".join(args).strip()
        room = msg["from"].bare
        await _vcard_handle_room_lookup(bot, sender_jid, msg, field, label,
                                        target_nick, room, own=False)
        return

    if is_muc_context and not args:
        target_nick = msg["from"].resource
        room = msg["from"].bare
        await _vcard_handle_room_lookup(bot, sender_jid, msg, field, label,
                                        target_nick, room, own=True)
        return

    target_nick = msg["from"].bare
    room = "Direct Message"

    if args:
        log.info("[VCARD] Direct message with args from "
                 f"'{msg['from'].bare}'")
        bot.reply(msg, "🔴  In direct messages, you can only look up "
                       "your own vCard. Use the command without args.")
        return

    jid = msg["from"].bare
    if field == "TIMEZONE":
        value = await _core._get_user_timezone(bot, str(jid))
    else:
        vcard = await get_user_vcard(bot, msg, msg["from"].bare)
        if vcard[field] is None:
            log.warning("[VCARD] 🔴  No vCard field '%s' for nick '%s'"
                        "in room '%s'",
                        label, target_nick, room)
            _vcard_reply_missing_field(bot, msg, label, target_nick, room)
            return
        value = vcard[field]

    display_name = target_nick
    if _vcard_value_is_empty(value):
        log.warning("[VCARD] 🔴  No %s for requested user '%s'",
                    field, target_nick)
        _vcard_reply_empty_requested_user(bot, msg, label, target_nick)
        return

    await _vcard_reply_result(bot, msg, sender_jid, field, label, value,
                              display_name, room)
    return


async def get_vcard(bot, msg, jid=None):
    """
    Helper function to fetch vCard for a given JID using the xep_0054 plugin.
    """
    if jid is None:
        jid, _, _ = await _core.get_real_jid(bot, msg)
    try:
        vcard_plugin = bot.plugin.get("xep_0054", None)
        if not vcard_plugin:
            raise RuntimeError(
                "vCard support (xep_0054) is not enabled in this bot.")
        try:
            result = await vcard_plugin.get_vcard(jid=str(jid), cached=False,
                                                  timeout=float(config.get("vcard_fetch_timeout_seconds", 10) or 10))
        except (IqError, Exception) as e:
            log.info(
                f"[VCARD] Exception while fetching vCard for '{jid}': {e}")
            result = None
        else:
            log.debug(f"[VCARD] vCard fetch for '{jid}' completed")
        if not result:
            log.debug(f"[VCARD] No vCard result for '{jid}'.")
            return None
        log.debug(f"[VCARD] vCard for '{jid}' received.")
        return result["vcard_temp"]
    except Exception as e:
        log.error(f"[VCARD] Exception during vCard lookup for '{jid}': {e}")
        raise


async def get_info(bot, msg, jid=None):
    try:
        vcard = await get_user_vcard(bot, msg, jid)
        if not vcard:
            log.info(f"[VCARD] No vCard found for '{jid}'.")
            return None

    except Exception as e:
        log.error(f"[VCARD] Exception during vCard lookup for '{jid}': {e}")
        raise
    return vcard


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
        if not child.tag.endswith("EMAIL"):
            continue

        # Find USERID child element within the EMAIL entry.
        for email_child in child:
            if email_child.tag.endswith("USERID") and email_child.text:
                emails.append(email_child.text.strip())
    return emails


async def get_vcard_store(bot):
    return bot.db.users.plugin("vcard")


async def _resolve_vcard_target(bot, msg, args, is_room, enabled_rooms):
    """Resolve lookup target for room/PM/DM contexts.

    Returns:
        (jid, target_nick, muc_jid) or (None, None, None) if command should
        stop.
    """
    in_room_context = is_room or _core._is_muc_pm(msg)

    if in_room_context and args:
        target_nick = " ".join(args).strip()
        muc_jid = f"{msg['from'].bare}"
        if muc_jid not in enabled_rooms:
            return None, None, None

        joined = JOINED_ROOMS.get(muc_jid, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            bot.reply(msg, f"🔴  Nick '{target_nick}' not found in this room.")
            return None, None, None

        jid = nick_info.get("jid")
        if not jid:
            bot.reply(msg, "🔴  Could not resolve JID for nick"
                           f" '{target_nick}'.")
            return None, None, None

        return jid, target_nick, muc_jid

    if in_room_context and not args:
        target_nick = msg["from"].resource
        muc_jid = f"{msg['from'].bare}"
        if muc_jid not in enabled_rooms:
            return None, None, None

        joined = JOINED_ROOMS.get(muc_jid, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            bot.reply(msg, f"🔴  Your Nick '{target_nick}' not found"
                           " in this room.")
            return None, None, None

        jid = nick_info.get("jid")
        if not jid:
            bot.reply(msg, "🔴  Could not resolve your JID for"
                           f" nick '{target_nick}'.")
            return None, None, None

        return jid, target_nick, muc_jid

    # DM context
    if args:
        log.info(f"[VCARD] Direct message with args from '{msg['from'].bare}'")
        bot.reply(
            msg,
            "🔴  In direct messages, you can only look up your own vCard."
            " Use the command without args.",
        )
        return None, None, None

    jid = msg["from"].bare
    return jid, jid, "Direct Message"


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
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    in_room_context = is_room or _core._is_muc_pm(msg)

    if msg["from"].bare not in enabled_rooms and in_room_context:
        return

    if in_room_context:
        handled = await _core.handle_room_toggle_command(
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

    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")

    jid, target_nick, muc_jid = await _resolve_vcard_target(
        bot, msg, args, is_room, enabled_rooms
    )
    if jid is None:
        return

    try:
        vcard_info = await get_vcard(bot, msg, jid=jid)

        if not vcard_info:
            bot.reply(msg, f"ℹ️ No vCard found for {target_nick} ({muc_jid}).")
            log.info(f"[VCARD] No vCard found for '{target_nick}' ({muc_jid})")
            return

        lines, vcard = _format_vcard_reply(vcard_info, target_nick, muc_jid)

        timezone = await _get_vcard_timezone(bot, msg, jid, is_room, args)
        if timezone:
            if lines[-1] != "":
                lines.append("")
            lines.append(f"• Timezone: {timezone}")

        bot.reply(msg, lines)
    except Exception as e:
        bot.reply(msg, f"🔴 Failed to fetch vCard for {target_nick}: {e}")
        log.error("[VCARD] Exception during vCard lookup"
                  f" for '{target_nick}' ({muc_jid}): {e}")


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
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
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
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           "NICKNAME", "Nicknames")


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
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
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
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           "NOTE", "Notes")


@command("emails", role=Role.USER, aliases=["e"])
async def get_email(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the EMAILs of a user.

    Usage:
        {prefix}emails [nick]
        {prefix}e [nick]

    Example:
        {prefix}email Envsi
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
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
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
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
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    # 1. Room context (groupchat) or MUC PM: lookup nick in room
    if (is_room or _core._is_muc_pm(msg)) and args:
        target_nick = " ".join(args).strip()
        room = msg["from"].bare
        joined = JOINED_ROOMS.get(room, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            bot.reply(msg, f"🔴  Nick '{target_nick}' not found in this room.")
            return
        display_name = target_nick
        jid = nick_info.get("jid")
    elif (is_room or _core._is_muc_pm(msg)) and not args:
        target_nick = msg["from"].resource
        room = msg["from"].bare
        joined = JOINED_ROOMS.get(room, {})
        nicks = joined.get("nicks", {})
        nick_info = nicks.get(target_nick)
        if not nick_info:
            bot.reply(msg,
                      f"🔴  Your Nick '{target_nick}' not found in this room.")
            return
        jid = nick_info.get("jid")
        display_name = target_nick
    else:
        if args:
            log.info(f"[VCARD] Direct message with args from '{
                     msg['from'].bare}'")
            bot.reply(
                msg,
                "🔴  In direct messages, you can only look up your own"
                " birthday. Use the command without args.")
            return
        jid = str(msg["from"].bare)
        display_name = jid

    vcard = await get_info(bot, msg, jid)
    value = None
    if vcard and vcard["BDAY"] is not None:
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
