# plugins/weather_time.py

"""
Info plugin: Show the current weather for a user's configured profile.

Commands:
    {prefix}weather [nick]
"""

import aiohttp
import logging
import urllib
from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "weather_time",
    "version": "0.2.2",
    "description": "Gives weather according to users location (supports PM/DM)",
    "category": "info",
    "requires": ["rooms"],
}

log = logging.getLogger(__name__)


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


@command("weather", role=Role.USER, aliases=["w"])
async def weather_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the current weather for your configured location or another user's location.
    Usage:
        {prefix}weather
        {prefix}weather <nick>
    """
    profile_store = bot.db.users.profile()

    if is_room:
        room = msg["from"].bare
        nicks = JOINED_ROOMS.get(room, {}).get("nicks", {})
        if args:
            target_nick = args[0]
            info = nicks.get(target_nick)
            if not info or not info.get("jid"):
                bot.reply(msg, f"🔴  Nick '{target_nick}' not found in this room.")
                return
            target_jid = str(info["jid"])
            display_name = target_nick
        else:
            info = nicks.get(nick)
            if not info or not info.get("jid"):
                bot.reply(msg, "🔴  Could not determine your JID in this room.")
                return
            target_jid = str(info["jid"])
            display_name = nick
    else:
        # Direct message: allow querying someone else by their nick, fallback to self
        if args:
            target_nick = args[0]
            # DM context: lookup globally
            index = bot.db.users._nick_index
            jids = index.get(target_nick, [])
            if not jids:
                log.warning(
                    "[PROFILE] 🔴  Nick '%s' not found globally",
                    target_nick
                )
                bot.reply(
                    msg,
                    f"🔴  Nick '{target_nick}' not found."
                )
                return
            for jid in jids:
                if jid:
                    target_jid = jid
                    break
            display_name = target_nick
        else:
            target_jid, display_name = get_pm_target(sender_jid, nick)
            display_name = await get_display_name(bot, target_jid)

    location = await profile_store.get(target_jid, "LOCATION")
    timezone = await profile_store.get(target_jid, "TIMEZONE")

    if not location:
        bot.reply(
            msg,
            f"🟡️ No LOCATION set for {display_name}."
            f" Use {config.get('prefix', ',')}config location <your location>"
        )
        return

    enc_location = urllib.parse.quote(location, safe="")
    url = f"https://wttr.in/{enc_location}?format=4&m"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    bot.reply(msg, f"🌦️ Failed to fetch weather for {display_name}.")
                    log.warning(f"[WEATHER] 🌦️ HTTP error {resp.status} for {display_name} ({target_jid}) at {location}")
                    return
                weather = await resp.text()
    except Exception:
        bot.reply(msg, f"🌦️ Failed to fetch weather for {display_name}.")
        log.warning(f"[WEATHER] 🌦️ Exception fetching weather for {display_name} ({target_jid}) at {location}")
        return

    tz_str = f" ({timezone})" if timezone else ""
    log.info(f"[WEATHER] 🌤️ {display_name} ({target_jid}) -> {weather.strip()}{tz_str} ({location})")
    bot.reply(msg, f"🌤️ Weather for {display_name}: {weather.strip()}{tz_str} ({location})", ephemeral=False)
