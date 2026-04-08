"""
XMPP tools plugin.

This plugin provides various utility commands for interacting with XMPP
servers and users, such as pinging a JID or server to measure round-trip
time. More XMPP-related tools will be added in the future.

Commands:
    {prefix}ping <jid|nick>
"""
import time
import slixmpp
from utils.command import command, Role
from plugins.rooms import JOINED_ROOMS

PLUGIN_META = {
    "name": "tools",
    "version": "0.1.1",
    "description": "XMPP utility tools (ping, diagnostics, etc.)",
    "category": "tools",
    "Requires": ["rooms"],
}


def _resolve_ping_target(bot, args, msg, is_room, nick):
    """
    Resolve the ping target: JID, room JID/nick, or nick in room context.
    Returns (target, error_message) tuple.
    """
    if not args or len(args) != 1:
        return None, "Usage: {prefix}ping <jid|nick>"
    target = args[0]
    # If in room or MUC PM and target is a nick, resolve to room_jid/nick
    if (is_room or (
        msg.get("type") in ("chat", "normal")
        and hasattr(msg["from"], "bare")
        and str(msg["from"].bare) in JOINED_ROOMS
    )):
        room = msg["from"].bare
        nicks = JOINED_ROOMS.get(room, {}).get("nicks", {})
        if target in nicks:
            return f"{room}/{target}", None
    return target, None


@command("ping", role=Role.USER)
async def ping_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Ping an XMPP JID, room JID/nick, or nick in the current room and report
    round-trip time.

    Usage:
        {prefix}ping <jid|nick>
    Example:
        {prefix}ping user@example.org
        {prefix}ping conference.example.org
        {prefix}ping Alice
    """
    target, error = _resolve_ping_target(bot, args, msg, is_room, nick)
    if error:
        bot.reply(msg, error)
        return

    try:
        start = time.monotonic()
        await bot.plugin["xep_0199"].ping(jid=target, timeout=8)
        rtt = (time.monotonic() - start) * 1000
        bot.reply(msg, f"🏓 Pong from {target} in {rtt:.1f} ms")
    except slixmpp.exceptions.IqTimeout:
        bot.reply(msg, f"🔴  Ping to {target} timed out.")
    except slixmpp.exceptions.IqError as e:
        err = e.iq['error']
        err_type = err.get('type', 'unknown')
        err_condition = err.get('condition', 'unknown')
        err_text = err.get('text', '')
        bot.reply(
            msg,
            f"🔴  Ping to {target} failed: {err_type}/"
            f"{err_condition} {err_text}".strip()
        )
    except Exception as e:
        bot.reply(msg, f"🔴  Ping to {target} failed: {e}")
