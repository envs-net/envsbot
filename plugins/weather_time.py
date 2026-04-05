"""
Info plugin: Show the current time and weather for a user's configured profile.

Commands:
    {prefix}time [nick]
    {prefix}weather [nick]
"""

import pytz
from datetime import datetime
import aiohttp
import logging
from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "weather_time",
    "version": "0.1.0",
    "description": "Gives weather and time according to users location",
    "category": "info",
    "requires": ["rooms"],
}


def _room_context(msg, is_room):
    """Return (room, nicks) if in groupchat or MUC PM, else (None, None)."""
    if is_room or (
        msg.get("type") in ("chat", "normal")
        and hasattr(msg["from"], "bare")
        and "@" in str(msg["from"].bare)
        and str(msg["from"].bare) in JOINED_ROOMS
    ):
        room = msg["from"].bare
        nicks = JOINED_ROOMS.get(room, {}).get("nicks", {})
        return room, nicks
    return None, None


async def _get_target(bot, msg, is_room, nick, args):
    """
    Resolve (jid, display_name, profile_store, nicks) for self or nick in room.
    """
    room, nicks = _room_context(msg, is_room)
    if not room:
        return None, None, None, None
    if args:
        target_nick = args[0]
        info = nicks.get(target_nick)
        if not info or not info.get("jid"):
            return None, f"❌ Nick '{target_nick}' not found in this room.", None, None
        target_jid = str(info["jid"])
        display_name = target_nick
    else:
        info = nicks.get(nick)
        if not info or not info.get("jid"):
            return None, "❌ Could not determine your JID in this room.", None, None
        target_jid = str(info["jid"])
        display_name = nick
    profile_store = bot.db.users.profile()
    return target_jid, display_name, profile_store, nicks


def _not_available(msg, bot):
    bot.reply(msg, ("❌ This command is only available in a room or"
                    " MUC direct message."))


@command("time", role=Role.USER, aliases=["t"])
async def time_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the current time in your configured timezone or another user's
    timezone.

    Usage:
        {prefix}time
        {prefix}time <nick>
    """
    room, _ = _room_context(msg, is_room)
    if not room:
        _not_available(msg, bot)
        return
    target_jid, display_name, profile_store, nicks = await _get_target(bot,
                                                                       msg,
                                                                       is_room,
                                                                       nick,
                                                                       args)
    if not target_jid:
        bot.reply(msg, display_name)  # display_name is error message here
        return
    timezone = await profile_store.get(target_jid, "TIMEZONE")
    location = await profile_store.get(target_jid, "LOCATION")
    if not timezone:
        bot.reply(msg, (f"⚠️ No TIMEZONE set for {display_name}."
                        f" Use {config.get('prefix', ',')}config timezone"
                        f" <zone>"))
        return
    try:
        now = datetime.now(pytz.timezone(timezone))
    except Exception:
        bot.reply(msg, f"⚠️ Invalid timezone '{timezone}' for {display_name}.")
        log.warning(f"[TIME] 🕒 Invalid timezone '{timezone}' for"
                    + f"{display_name} ({target_jid})")
        return
    formatted = now.strftime("%Y-%m-%d %H:%M:%S")
    loc_str = f" ({location})" if location else ""
    log.info(f"[TIME] 🕒 {display_name} ({target_jid}) ->"
             + f" {formatted} ({timezone}){loc_str}")
    bot.reply(msg, f"🕒 Time for {display_name}: {formatted}"
                   + f" ({timezone}){loc_str}",
              ephemeral=False)


@command("weather", role=Role.USER, aliases=["w"])
async def weather_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the current weather for your configured location or another
    user's location.

    Usage:
        {prefix}weather
        {prefix}weather <nick>
    """
    room, _ = _room_context(msg, is_room)
    if not room:
        _not_available(msg, bot)
        return
    target_jid, display_name, profile_store, nicks = await _get_target(bot,
                                                                       msg,
                                                                       is_room,
                                                                       nick,
                                                                       args)
    if not target_jid:
        bot.reply(msg, display_name)  # display_name is error message here
        return
    location = await profile_store.get(target_jid, "LOCATION")
    timezone = await profile_store.get(target_jid, "TIMEZONE")
    if not location:
        bot.reply(msg, f"⚠️ No LOCATION set for {display_name}."
                       + f" Use {config.get('prefix', ',')}config"
                       + " location <your location>")
        return
    url = f"https://wttr.in/{location}?format=4&m"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    bot.reply(msg, "🌦️ Failed to fetch weather for"
                                   + f" {display_name}.")
                    log.warning(f"[WEATHER] 🌦️ HTTP error {resp.status}"
                                f" for {display_name} ({target_jid})"
                                f" at {location}")
                    return
                weather = await resp.text()
    except Exception:
        bot.reply(msg, f"🌦️ Failed to fetch weather for {display_name}.")
        log.warning(f"[WEATHER] 🌦️ Exception fetching weather for"
                    f" {display_name} ({target_jid}) at {location}")
        return
    tz_str = f" ({timezone})" if timezone else ""
    log.info(f"[WEATHER] 🌤️ {display_name} ({target_jid}) ->"
             f" {weather.strip()}{tz_str} ({location})")
    bot.reply(msg, f"🌤️ Weather for {display_name}:"
                   + f" {weather.strip()}{tz_str} ({location})",
              ephemeral=False)
