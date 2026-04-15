# plugins/weather_time.py

"""
Info plugin: Show the current weather for a user's configured profile.

Commands:
    {prefix}weather [nick]
"""

import aiohttp
import logging
from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "weather_time",
    "version": "0.2.0",
    "description": "Gives weather according to users location (supports PM/DM)",
    "category": "info",
    "requires": ["rooms"],
}


def get_pm_target(sender_jid, nick):
    """
    Returns (bare_jid, nick_for_display)
    """
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
    if is_room:
        # Multi-User Chat: get target jid from nick
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
        target_jid, display_name = get_pm_target(sender_jid, nick)

    profile_store = bot.db.users.profile()
    location = await profile_store.get(target_jid, "LOCATION")
    timezone = await profile_store.get(target_jid, "TIMEZONE")

    if not location:
        bot.reply(
            msg,
            f"🟡️ No LOCATION set for {display_name}."
            f" Use {config.get('prefix', ',')}config location <your location>"
        )
        return

    url = f"https://wttr.in/{location}?format=4&m"
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
