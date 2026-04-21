"""
Tools plugin: Utility commands for bot interaction including ping/pong, message echo,
timezone-aware time/date lookups, and Unix timestamp conversion.

Provides basic bot health checks, message echoing, and allows users to query the current
time and date in their configured timezone or another user's timezone, as well as convert
Unix timestamps.

Commands:
    {prefix}ping
    {prefix}echo <message>
    {prefix}time [nick]
    {prefix}date [nick]
    {prefix}utc
    {prefix}ts <unix_timestamp>
"""

import pytz
import logging
from datetime import datetime
from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "tools",
    "version": "0.1.2",
    "description": "Utility commands: ping/pong, message echo, timezone-aware time/date lookups, and Unix timestamp conversion",
    "category": "utility",
}


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


@command("echo", role=Role.USER)
async def echo_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Repeat a message back to the user.

    Usage:
        {prefix}echo <message>

    Examples:
        {prefix}echo Hello World!
    """
    if not args:
        bot.reply(msg, f"🔴 Usage: {config.get('prefix', ',')}echo <message>")
        return

    # Join all arguments to handle multi-word messages
    message = " ".join(args)

    # Escape any special characters for safety if needed
    bot.reply(msg, f"🔊 {message}", ephemeral=False)


@command("time", role=Role.USER, aliases=["t"])
async def time_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the current time in your configured timezone or another user's timezone.

    Usage:
        {prefix}time
        {prefix}time <nick>
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
    bot.reply(msg, f"⏰ Time for {display_name}: {formatted} {tzone}{loc_str}", ephemeral=False)


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
