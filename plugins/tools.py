"""
XMPP tools plugin.

This plugin provides various utility commands for interacting with XMPP
servers and users, such as pinging a JID or server to measure round-trip
time. More XMPP-related tools will be added in the future.

Commands:
    {prefix}ping <jid>
"""

import time
import slixmpp
from utils.command import command, Role

PLUGIN_META = {
    "name": "tools",
    "version": "0.1.0",
    "description": "XMPP utility tools (ping, diagnostics, etc.)",
    "category": "tools",
}


@command("ping", role=Role.USER)
async def ping_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Ping an XMPP JID or server and report round-trip time.

    Usage:
        {prefix}ping <jid>
    Example:
        {prefix}ping user@example.org
        {prefix}ping conference.example.org
    """
    if not args or len(args) != 1:
        bot.reply(msg, "Usage: {prefix}ping <jid>")
        return

    target = args[0]

    try:
        start = time.monotonic()
        await bot.plugin["xep_0199"].ping(jid=target, timeout=8)
        rtt = (time.monotonic() - start) * 1000
        bot.reply(msg, f"🏓 Pong from {target} in {rtt:.1f} ms")
    except slixmpp.exceptions.IqTimeout:
        bot.reply(msg, f"❌ Ping to {target} timed out.")
    except slixmpp.exceptions.IqError as e:
        err = e.iq['error']
        err_type = err.get('type', 'unknown')
        err_condition = err.get('condition', 'unknown')
        err_text = err.get('text', '')
        bot.reply(
            msg,
            f"❌ Ping to {target} failed: {err_type}/{err_condition} {err_text}".strip()
        )
    except Exception as e:
        bot.reply(msg, f"❌ Ping to {target} failed: {e}")
