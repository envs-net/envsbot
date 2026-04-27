"""
Tell plugin for Envsbot.

Allows users to leave messages for other users who are not present in a room.
Messages are stored using the recipient's real_jid and delivered the next time the
recipient joins the room via the 'groupchat_presence' event.

Supports nicks with spaces. Command format: {prefix}tell <nick with spaces>: <message>
"""

import datetime
import pytz
import logging
import asyncio
from functools import partial

from utils.command import command, Role
from utils.config import config

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "tell",
    "version": "0.1.0",
    "description": "Store and deliver messages for users when they join a room again.",
    "category": "utility",
    "requires": [],
}


def parse_nick_and_message(args_str):
    """
    Splits on the first colon.
    Returns (nick, msg) or (None, None) if invalid.
    """
    if ":" not in args_str:
        return None, None
    nick, message = args_str.split(":", 1)
    nick = nick.strip()
    message = message.lstrip()
    if not nick or not message:
        return None, None
    return nick, message


async def get_real_jid(bot, nick):
    """Look up the real JID of a nick from the UserManager's _nick_index."""
    idx = getattr(bot.db.users, "_nick_index", {})
    value = idx.get(nick)
    if isinstance(value, set):
        return next(iter(value), None)
    if isinstance(value, list):
        return value[0] if value else None
    return value or None


async def get_timezone(bot, jid):
    """
    Get the user's timezone from the global PluginRuntimeStore,
    fallback to UTC.
    """
    store = await bot.db.users.plugin("vcard")
    tzname = None
    if store:
        tzname = store.get(jid, "TIMEZONE")
    if tzname:
        try:
            return pytz.timezone(tzname)
        except Exception:
            pass
    return pytz.utc


async def tell_store(bot, recv_jid, payload):
    store = bot.db.users.plugin("tell")
    messages = await store.get(recv_jid, "tell_messages") or []
    messages.append(payload)
    await store.set(recv_jid, "tell_messages", messages)


async def tell_fetch(bot, recv_jid):
    store = bot.db.users.plugin("tell")
    messages = await store.get(recv_jid, "tell_messages") or []
    await store.set(recv_jid, "tell_messages", [])
    return messages


@command("tell", role=Role.USER)
async def tell_cmd(bot, sender_jid, sender_nick, args, msg, is_room):
    """
    {prefix}tell <nick (may include spaces)>: <message>

    Stores a message for a user (with or without spaces in their nick).
    Will be delivered when they join the room again.
    Only available in groupchats.
    """
    prefix = config.get("prefix", ",")
    if not is_room:
        bot.reply(msg, f"This command is only available in groupchats.")
        return

    raw_args = " ".join(args)
    rec_nick, message = parse_nick_and_message(raw_args)
    if not rec_nick or not message:
        bot.reply(msg, f"Usage: {prefix}tell <nick>: <message>")
        return

    rec_jid = await get_real_jid(bot, rec_nick)
    if not rec_jid:
        bot.reply(msg, f"Could not find user '{rec_nick}'. (Maybe they never spoke?)")
        log.info(f"[TELL] Failed to store message for '{rec_nick}' - user not found.")
        return

    send_jid = await get_real_jid(bot, sender_nick)
    send_jid = send_jid or sender_jid

    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    payload = {
        "recv_jid": rec_jid,
        "send_jid": send_jid,
        "send_nick": sender_nick,
        "recv_nick": rec_nick,
        "message": message,
        "timestamp": now,
    }
    await tell_store(bot, rec_jid, payload)
    bot.reply(msg, f"[TELL] I'll deliver your message to {rec_nick} when they join.")
    log.info(f"[TELL] Stored message for {rec_nick} ({rec_jid}) from {sender_nick} ({send_jid}): {message}")


async def deliver_tell_messages(bot, msg):
    """
    Handle slixmpp groupchat_presence event and deliver pending messages.
    Event signature is (bot, msg).
    """
    room = str(msg["from"].bare)
    nick = str(msg["muc"]["nick"])
    rec_jid = await get_real_jid(bot, nick)
    if not rec_jid:
        return

    messages = await tell_fetch(bot, rec_jid)
    if not messages:
        return

    tzinfo = await get_timezone(bot, rec_jid)
    for entry in messages:
        when = datetime.datetime.fromtimestamp(entry["timestamp"], pytz.utc).astimezone(
            tzinfo
        )
        timestr = when.strftime("%a, %d %b %H:%M %Z")
        await asyncio.sleep(1)  # slight delay to avoid flooding on join
        bot.reply(
            {
                "from": msg["from"],
                "type": "groupchat",
                "mucnick": nick,
            },
            f"[TELL] ({timestr}) {entry['send_nick']} - {entry['recv_nick']}: {entry['message']}",
            mention=True,
        )
        log.info(f"[TELL] Delivered tell message to {nick} ({rec_jid}): {entry['message']}")


def on_load(bot):
    """
    Register the presence handler using partial so it has (bot, msg)
    signature when called.
    """
    bot.bot_plugins.register_event(
        "tell_notify", "groupchat_presence",
        partial(deliver_tell_messages, bot)
    )
