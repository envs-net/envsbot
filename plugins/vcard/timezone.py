"""Split module for plugins/vcard.py: timezone."""

import pytz
from core_plugins import _core
from utils.command import command, Role
from utils.config import config


@command("timezone set", role=Role.USER, aliases=["tz set"])
async def set_timezone(bot, sender_jid, nick, args, msg, is_room):
    """
    Set your TIMEZONE in Linux format eg. for '{prefix}time [nick]' command.

    Check your timezone at:
    https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
    Use the "TZ identifier" from the list.

    Usage:
        {prefix}timezone set <timezone>
        {prefix}tz set <timezone>

    Example:
        {prefix}timezone set Europe/Berlin
        {prefix}tz set Alaska/Anchorage
    """
    # Check, if command is allowed in this context (room or MUC PM)
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    if not is_room and not _core._is_muc_pm(msg):
        jid = msg["from"].bare
    else:
        jid, _, _ = await _core.get_real_jid(bot, msg)
    log.info("[VCARD] ✅ set_timezone called by %s", jid)
    if not await _core._check_user_exists(bot, jid, msg):
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


async def _get_vcard_timezone(bot, msg, jid, is_room, args):
    """Fetch timezone for the resolved target, preserving original behavior."""
    if is_room or _core._is_muc_pm(msg):
        if args:
            if jid:
                return await _core._get_user_timezone(bot, str(jid))
            return None
        real_jid, _, _ = await _core.get_real_jid(bot, msg)
        return await _core._get_user_timezone(bot, str(real_jid))

    return await _core._get_user_timezone(bot, str(jid))


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
    enabled_rooms = await _core._get_enabled_rooms(bot, VCARD_KEY, "vcard")
    if msg["from"].bare not in enabled_rooms and (is_room or
                                                  _core._is_muc_pm(msg)):
        return

    await _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           "TIMEZONE", "Timezone")
