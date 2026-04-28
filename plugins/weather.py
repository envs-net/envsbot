"""
Info plugin: Show the current weather for a user's location configured in
their vCard. Only works in groupchats or MUC DMs where the user has a vCard
with a LOCATION field.

Commands:
    {prefix}weather [nick]
"""

import aiohttp
import logging
import urllib
from utils.command import command, Role
from plugins.rooms import JOINED_ROOMS
from plugins.vcard import get_info
from utils.plugin_helper import handle_room_toggle_command

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "weather",
    "version": "0.3.0",
    "description": ("Gives weather according to users location (supports MUCs"
                    "and MUC DMs)"),
    "category": "info",
    "requires": ["rooms", "vcard"],
}

WEATHER_KEY = "WEATHER"

log = logging.getLogger(__name__)


def _is_muc_pm(msg):
    """Returns True if msg is a MUC direct message (not public groupchat)."""
    return (
        msg.get("type") in ("chat", "normal")
        and hasattr(msg["from"], "bare")
        and "@" in str(msg["from"].bare)
        and str(msg["from"].bare) in JOINED_ROOMS
    )


async def get_display_name(bot, jid):
    store = bot.db.users.plugin("users")
    try:
        roomnicks = await store.get(jid, "roomnicks")
        for room in roomnicks or []:
            if room:
                display_name = roomnicks[room][0]
                break
    except Exception as e:
        log.warning(
                    "[PROFILE] 🔴  Failed to get roomnicks for %s: %s",
                    jid, e
        )
        display_name = "unknown"
    log.info(
        "[PROFILE] 👤 Profile lookup for self: %s",
        display_name
    )
    return display_name


def get_pm_target(sender_jid, nick):
    if hasattr(sender_jid, "bare"):
        bare_jid = sender_jid.bare
    else:
        bare_jid = str(sender_jid).split('/')[0]
    return bare_jid, nick


async def get_weather_store(bot):
    return bot.db.users.plugin("weather")


@command("weather", role=Role.USER, aliases=["w"])
async def weather_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the current weather for a users location set in their vCard. If
    the <nick> is omitted, your own location according to your vCard is
    used. Only works in groupchats or MUC DMs where the user has a vCard
    with a LOCATION and/or COUNTRY (CTRY) field set (must be public).

    Usage:
        {prefix}weather
        {prefix}weather <on|off|status>
        {prefix}weather <nick>
    """

    handled = await handle_room_toggle_command(
        bot,
        msg,
        is_room,
        args,
        store_getter=get_weather_store,
        key=WEATHER_KEY,
        label="Get weather",
        storage="dict",
        log_prefix="[WEATHER]",
    )
    if handled:
        return

    store = await get_weather_store(bot)
    enabled_rooms = await store.get_global(WEATHER_KEY, default={})

    vcard = {}
    display_name = ""
    if is_room:
        log.info((f"[WEATHER] Command invoked in room {msg['from'].bare} by"
                 f"{nick} with args: {args}"))
        muc_jid = msg["from"].bare
        if muc_jid not in enabled_rooms:
            return
        nicks = JOINED_ROOMS.get(muc_jid, {}).get("nicks", {})
        if args:
            target_nick = " ".join(args).strip()
            if target_nick not in nicks:
                log.info((f"[WEATHER] Lookup failed: Nick '{target_nick}'"
                         f"not found in room {muc_jid}"))
                bot.reply(msg, f"🔴  Nick '{target_nick}' not found in this room.")
                return
            display_name, vcard = await get_info(bot, msg, target_nick)
            if vcard is None:
                return
        else:
            target_nick = msg["from"].resource
            if target_nick not in nicks:
                log.info(f"[WEATHER] Lookup failed: Nick '{target_nick}' not found in room {muc_jid}")
                bot.reply(msg, f"🔴  Your Nick '{target_nick}' was not found in this room.")
                return
            display_name, vcard = await get_info(bot, msg, target_nick)
            if vcard is None:
                return

            log.info(f"[VCARD] vCard for '{target_nick}' ({muc_jid}) received (never real jid!).")
    elif _is_muc_pm(msg):
        log.info(f"[WEATHER] No target nick provided, using sender's nick '{nick}' for lookup.")
        target_nick = msg["from"].resource
        muc_jid = msg["from"].bare
        if muc_jid not in enabled_rooms:
            return
        nicks = JOINED_ROOMS.get(msg["from"].bare, {}).get("nicks", {})
        if target_nick not in nicks:
            log.info(f"[WEATHER] Lookup failed: Your Nick '{target_nick}' not found in room {muc_jid}")
            bot.reply(msg, f"🔴  Nick '{target_nick}' not found in this room.")
            return
        display_name, vcard = await get_info(bot, msg, target_nick)
        if vcard is None:
            return

        log.info(f"[VCARD] vCard for '{target_nick}' ({muc_jid}) received (never real jid!).")
    else:
        # DM Weather requests not allowed!
        log.info(f"[WEATHER] Command invoked in DM by {nick} with args: {args}")
        bot.reply(msg, "🔴  Weather command is only available in groupchats or MUC DMs.")
        return

    location = None
    if vcard.get("CTRY") is not None:
        location = vcard.get("CTRY", "")
    if location is not None and vcard.get("LOCALITY") is not None:
        location += f"/{vcard.get('LOCALITY', '')}"
    elif location is None and vcard.get("LOCALITY") is not None:
        location = vcard.get("LOCALITY", "")
    else:
        location = ""

    log.info(f"[WEATHER] Location for {display_name}: {location}")

    if not location or location.strip() == "":
        bot.reply(
            msg,
            f"🟡️ No LOCATION in vCard for {display_name}."
        )
        return

    enc_location = urllib.parse.quote(location, safe="")
    url = f"https://wttr.in/{enc_location}?format=4&m"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    bot.reply(msg, f"🌦️ Failed to fetch weather for {display_name}.")
                    log.warning(f"[WEATHER] 🌦️ HTTP error {resp.status} for {display_name} at {location}")
                    return
                weather = await resp.text()
    except Exception:
        bot.reply(msg, f"🌦️ Failed to fetch weather for {display_name}.")
        log.warning(f"[WEATHER] 🌦️ Exception fetching weather for {display_name} at {location}")
        return

    weather_loc = weather.split(":")[0].strip()
    weather_desc = ":".join(weather.split(":")[1:]).strip()
    bot.reply(msg, f"🌤️ Weather for {display_name}: {weather_loc.title()}: {weather_desc.strip()} ({location})", ephemeral=False)
