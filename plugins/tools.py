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
import slixmpp
from datetime import datetime
from utils.command import command, Role
from utils.config import config
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "tools",
    "version": "0.2.1",
    "description": "Utility commands: ping/pong, message echo, timezone-aware time/date lookups, and Unix timestamp conversion",
    "category": "utility",
}


def resolve_real_jid(bot, msg, is_room):
    """
    Resolve the real sender JID in all contexts (groupchat, MUC PM, or DM).
    """
    jid = None
    muc = bot.plugin.get("xep_0045", None)
    if muc:
        room = msg['from'].bare
        nick = msg["from"].resource
        log.debug("[PROFILE] Resolving real JID for room: %s, nick: %s", room, nick)
        jid = muc.get_jid_property(room, nick, "jid")
    if jid is None:
        jid = msg["from"]
    return str(slixmpp.JID(jid).bare)


def _is_muc_pm(msg):
    """Returns True if msg is a MUC direct message (not public groupchat)."""
    return (
        msg.get("type") in ("chat", "normal")
        and hasattr(msg["from"], "bare")
        and "@" in str(msg["from"].bare)
        and str(msg["from"].bare) in JOINED_ROOMS
    )


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
    room = msg["from"].bare
    nicks = JOINED_ROOMS.get(room, {}).get("nicks", {})
    if is_room or _is_muc_pm(msg):
        if args:
            target_nick = " ".join(args).strip()
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
        # Direct messages to bot are vorbidden
        log.info("[TOOLS] Forbidden try to use the 'time' command in DM by %s",
                nicks.get(nick, {}).get("nick", "unknown"))
        bot.reply(msg, "🔴  The 'time' command in DMs is not allowed")
        return

    store = bot.db.users.plugin("vcard")
    timezone = await store.get(target_jid, "TIMEZONE")

    if not timezone:
        bot.reply(msg, f"🟡️ No TIMEZONE set for {display_name}. Using UTC. "
                       f"Set with {config.get('prefix', ',')}tz set <timezone>")
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
    loc_str = ""
    bot.reply(msg, f"⏰ Time for {display_name}: {formatted} {tzone}{loc_str}", ephemeral=False)


@command("date", role=Role.USER)
async def date_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the current date in your configured timezone or another user's timezone.

    Usage:
        {prefix}date
        {prefix}date <nick>
    """
    room = msg["from"].bare
    nicks = JOINED_ROOMS.get(room, {}).get("nicks", {})
    if is_room or _is_muc_pm(msg):
        if args:
            target_nick = " ".join(args).strip()
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
        # Direct messages are not allowed
        log.info("[TOOLS] Forbidden try to use the 'date' command in DM by %s",
                nicks.get(nick, {}).get("nick", "unknown"))
        bot.reply(msg, "🔴  The 'date' command in DMs is not allowed")
        return

    store = bot.db.users.plugin("vcard")
    timezone = await store.get(target_jid, "TIMEZONE")

    if not timezone:
        bot.reply(msg, f"🟡️ No TIMEZONE set for {display_name}. Using UTC. "
                       f"Set with {config.get('prefix', ',')}tz set <timezone>")
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
    loc_str = ""
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
        store = bot.db.users.plugin("vcard")
        target_jid = resolve_real_jid(bot, msg, is_room)
        timezone = await store.get(target_jid, "TIMEZONE")

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
