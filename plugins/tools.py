"""
Tools plugin: Utility commands for bot interaction and timezone-aware time/date lookups.

Provides basic bot health checks and allows users to query the current time and date
in their configured timezone or another user's timezone.

Commands:
    {prefix}ping
    {prefix}time [nick]
    {prefix}date [nick]
    {prefix}utc
    {prefix}tzlist [search]
    {prefix}ts <unix_timestamp>
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


@command("ping", role=Role.USER, aliases=["pong"])
async def ping_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Respond with a pong message to confirm the bot is alive.

    Usage:
        {prefix}ping
    """
    bot.reply(msg, "🏓 Pong!", ephemeral=False)


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


@command("utc", role=Role.USER)
async def utc_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the current UTC time as a quick reference.

    Usage:
        {prefix}utc
    """
    now = datetime.now(pytz.UTC)
    formatted = now.strftime("%Y-%m-%d %H:%M:%S")
    bot.reply(msg, f"🌍 Current UTC time: {formatted}", ephemeral=False)


@command("tzlist", role=Role.USER)
async def tzlist_command(bot, sender_jid, nick, args, msg, is_room):
    """
    List available timezones or search for a specific timezone.

    Usage:
        {prefix}tzlist
        {prefix}tzlist <search_term>

    Examples:
        {prefix}tzlist Europe
        {prefix}tzlist America
    """
    search_term = args[0].lower() if args else None

    if search_term:
        matching = [tz for tz in pytz.all_timezones if search_term in tz.lower()]
    else:
        matching = pytz.all_timezones

    if not matching:
        bot.reply(msg, f"🔴 No timezones found matching '{search_term}'")
        return

    # Limit output to first 50 results to avoid spam
    display = matching[:50]
    tz_list = "\n".join(display)
    result_count = len(matching)

    if result_count > 50:
        tz_list += f"\n\n... and {result_count - 50} more"

    bot.reply(msg, f"📍 Available timezones ({result_count} total):\n{tz_list}", ephemeral=False)


@command("ts", role=Role.USER)
async def timestamp_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Convert a Unix timestamp to human-readable date and time in your timezone.

    Usage:
        {prefix}ts <unix_timestamp>

    Examples:
        {prefix}ts 1704067200
    """
    if not args:
        bot.reply(msg, f"🔴 Usage: {config.get('prefix', ',')}ts <unix_timestamp>")
        return

    try:
        timestamp = int(args[0])
    except ValueError:
        bot.reply(msg, f"🔴 Invalid timestamp. Please provide a valid Unix timestamp (integer).")
        return

    try:
        # Get user's timezone
        profile_store = bot.db.users.profile()
        target_jid, _ = get_pm_target(sender_jid, nick)
        timezone = await profile_store.get(target_jid, "TIMEZONE")

        if timezone:
            try:
                tzinfo = pytz.timezone(timezone)
            except Exception:
                tzinfo = pytz.UTC
        else:
            tzinfo = pytz.UTC

        # Convert timestamp to datetime in user's timezone
        dt = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
        dt_local = dt.astimezone(tzinfo)
        formatted = dt_local.strftime("%Y-%m-%d %H:%M:%S")
        tzone = str(tzinfo) if timezone else "UTC"

        bot.reply(msg, f"⏰ Timestamp {timestamp} = {formatted} ({tzone})", ephemeral=False)
    except (ValueError, OSError):
        bot.reply(msg, f"🔴 Invalid timestamp or out of range.")
    except Exception as e:
        bot.reply(msg, f"🔴 Error converting timestamp: {str(e)}")
