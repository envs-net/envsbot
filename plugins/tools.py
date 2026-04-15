# plugins/tools.py

"""
Tools plugin: Show the current time and date for a user's configured profile.

Commands:
    {prefix}time [nick]
    {prefix}date [nick]
"""

import pytz
from datetime import datetime
from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS


def get_pm_target(sender_jid, nick):
    """
    Returns (bare_jid, nick_for_display)
    """
    if hasattr(sender_jid, "bare"):
        bare_jid = sender_jid.bare
    else:
        bare_jid = str(sender_jid).split('/')[0]
    return bare_jid, nick


@command("time", role=Role.USER, aliases=["t"])
async def time_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the current time in your configured timezone or another user's timezone.

    Usage:
        {prefix}time
        {prefix}time <nick>

    """
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
        target_jid, display_name = get_pm_target(sender_jid, nick)

    profile_store = bot.db.users.profile()
    timezone = await profile_store.get(target_jid, "TIMEZONE")
    location = await profile_store.get(target_jid, "LOCATION")

    if not timezone:
        bot.reply(msg, f"🟡️ No TIMEZONE set for {display_name}. Using UTC. "
                       f"Set with {config.get('prefix', ',')}config timezone <zone>")
        tzinfo = pytz.UTC
        tzone = "UTC"
    else:
        try:
            tzinfo = pytz.timezone(timezone)
            tzone = timezone
        except Exception:
            bot.reply(msg, f"🟡️ Invalid timezone '{timezone}' for {display_name}. Using UTC.")
            tzinfo = pytz.UTC
            tzone = "UTC"

    now = datetime.now(tzinfo)
    formatted = now.strftime("%Y-%m-%d %H:%M:%S")
    loc_str = f" ({location})" if location else ""
    bot.reply(msg, f"🕒 Time for {display_name}: {formatted} ({tzone}){loc_str}", ephemeral=False)


@command("date", role=Role.USER)
async def date_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the current date in your configured timezone or another user's timezone.

    Usage:
        {prefix}date
        {prefix}date <nick>
    """
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
        target_jid, display_name = get_pm_target(sender_jid, nick)

    profile_store = bot.db.users.profile()
    timezone = await profile_store.get(target_jid, "TIMEZONE")
    location = await profile_store.get(target_jid, "LOCATION")

    if not timezone:
        bot.reply(msg, f"🟡️ No TIMEZONE set for {display_name}. Using UTC. "
                       f"Set with {config.get('prefix', ',')}config timezone <zone>")
        tzinfo = pytz.UTC
        tzone = "UTC"
    else:
        try:
            tzinfo = pytz.timezone(timezone)
            tzone = timezone
        except Exception:
            bot.reply(msg, f"🟡️ Invalid timezone '{timezone}' for {display_name}. Using UTC.")
            tzinfo = pytz.UTC
            tzone = "UTC"

    now = datetime.now(tzinfo)
    formatted = now.strftime("%Y-%m-%d")
    loc_str = f" ({location})" if location else ""
    bot.reply(msg, f"📅 Date for {display_name}: {formatted} ({tzone}){loc_str}", ephemeral=False)
