"""
Tell plugin for Envsbot.

Allows users to leave messages for other users who are not present in a room.
Messages are stored using the recipient's real_jid and delivered the next time
the recipient joins the room via the 'groupchat_presence' event.

Supports nicks with spaces, separated with a colon ":" from the message.

IMPORTANT: You must turn on the plugin for each room where you want to use it,
if not already enabled by default, with:
    {prefix}tell <on|off|status>

Usage:
    {prefix}tell <nick with spaces>: <message>
"""

import datetime
import pytz
import logging
import asyncio
from functools import partial

from utils.command import command, Role
from utils.config import config
from core_plugins._core import (
    handle_room_toggle_command,
    get_jids_from_nick_index,
    _get_enabled_rooms,
    _is_enabled_for_room,
    _is_muc_pm,
    get_user_tzinfo,
)

log = logging.getLogger(__name__)

TELL_KEY = "TELL"
TELL_DELIVERY_DELAY_SECONDS = int(config.get("tell_delivery_delay_seconds", 5) or 5)

PLUGIN_META = {
    "name": "tell",
    "version": "0.2.0",
    "description":
    "Store and deliver messages for users when they join a room again.",
    "category": "utility",
    "requires": ["rooms", "_core"],
}


async def get_tell_store(bot):
    return bot.db.users.plugin("tell")


def parse_nick_and_message(args_str):
    """
    Splits on the first colon.
    Returns (nick, msg) or (None, None) if invalid.
    """
    if ":" not in args_str:
        return None, None
    nick, message = args_str.split(":", 1)
    nick = nick.strip()
    message = message.strip()
    if not nick or not message:
        return None, None
    return nick, message


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


@command(
    "tell",
    role=Role.USER,
    short="Leave a message for another user.",
    usage="{prefix}tell <on|off|status|nick: message>",
    examples=[
        "{prefix}tell status",
        "{prefix}tell alice: I fixed it",
    ],
    category="utility",
    context="any",
)
async def tell_cmd(bot, sender_jid, sender_nick, args, msg, is_room):
    """

    Stores a message for a user (with or without spaces in their nick).
    Will be delivered when they join the room again.
    Only available in groupchats.

    NOTE the colon after the nick to separate the target nick from the message!

    IMPORTANT: You must turn on the plugin for each room where you want to
    use it, if not already enabled by default, with:
        {prefix}tell <on|off|status>

    Usage:
        {prefix}tell <nick (may include spaces)>: <message>
    """

    handled = await handle_room_toggle_command(
        bot,
        msg,
        is_room,
        args,
        store_getter=get_tell_store,
        key=TELL_KEY,
        label="Use 'tell' command",
        plugin="tell",
        storage="dict",
        log_prefix="[TELL]",
    )
    if handled:
        return

    # Check, if command is allowed in this context (room or MUC PM)
    if (
        (is_room or _is_muc_pm(msg))
        and not await _is_enabled_for_room(
            bot, TELL_KEY, "tell", str(msg["from"].bare)
        )
    ):
        return

    prefix = config.get("prefix", ",")
    if not is_room:
        bot.reply(msg, "This command is only available in groupchats.")
        return

    m = msg["body"].replace(f"{prefix}tell ", "", 1).strip()
    rec_nick, message = parse_nick_and_message(m)
    if not rec_nick or not message:
        bot.reply(msg, f"Usage: {prefix}tell <nick>: <message>")
        return

    rec_jids = await get_jids_from_nick_index(bot, rec_nick)
    rec_jid = rec_jids[0] if rec_jids else None
    if not rec_jid:
        bot.reply(msg, f"Could not find user '{
                  rec_nick}'. (Maybe they never spoke?)")
        log.info(f"[TELL] Failed to store message for '{
                 rec_nick}' - user not found.")
        return

    send_jids = await get_jids_from_nick_index(bot, sender_nick)
    send_jid = send_jids[0] if send_jids else None

    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    payload = {
        "room_jid": str(msg["from"].bare),
        "recv_jid": rec_jid,
        "send_jid": send_jid,
        "send_nick": sender_nick,
        "recv_nick": rec_nick,
        "message": message,
        "timestamp": now,
    }
    await tell_store(bot, rec_jid, payload)
    bot.reply(msg, f"[TELL] I'll deliver your message to {
              rec_nick} when they join.")
    log.info(f"[TELL] Stored message for {rec_nick} ({rec_jid}) from {
             sender_nick} ({send_jid}): {message}")


async def deliver_tell_messages(bot, msg):
    """
    Handle slixmpp groupchat_presence event and deliver pending messages.
    Event signature is (bot, msg).
    """
    nick = str(msg["muc"]["nick"])
    rec_jids = await get_jids_from_nick_index(bot, nick)
    rec_jid = rec_jids[0] if rec_jids else None
    if not rec_jid:
        return

    messages = await tell_fetch(bot, rec_jid)
    if not messages:
        return

    tzinfo = await get_user_tzinfo(bot, rec_jid)
    for entry in messages:
        w = datetime.datetime.fromtimestamp(entry["timestamp"],
                                            pytz.timezone("UTC")).astimezone(
            tzinfo
        )
        timestr = w.strftime("%a, %d %b %H:%M %Z")
        await asyncio.sleep(TELL_DELIVERY_DELAY_SECONDS)
        bot.reply(
            {
                "from": msg["from"],
                "type": "groupchat",
                "mucnick": nick,
            },
            f"[TELL] ({timestr}) {entry['send_nick']
                                  } - {entry['recv_nick']}: {
                                  entry['message']}",
            mention=True,
        )
        log.info(f"[TELL] Delivered tell message to {
                 nick} ({rec_jid}): {entry['message']}")


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int]:
    """Return tell counters for diagnostics."""
    store = await get_tell_store(bot)
    enabled = await _get_enabled_rooms(
        bot, TELL_KEY, "tell", [room_jid] if room_jid else ()
    )

    pending = 0
    users = getattr(getattr(bot, "db", None), "users", None)
    list_users = getattr(users, "list", None)
    if callable(list_users):
        for user in await list_users():
            jid = user.get("jid") if isinstance(user, dict) else None
            if not jid or jid == "__GLOBAL__":
                continue
            messages = await store.get(str(jid), "tell_messages") or []
            if isinstance(messages, list):
                if room_jid:
                    target = str(room_jid or "").split("/", 1)[0].strip().lower()
                    pending += sum(
                        1 for item in messages
                        if isinstance(item, dict)
                        and str(item.get("room_jid") or "").split("/", 1)[0].strip().lower() == target
                    )
                else:
                    pending += len(messages)

    if room_jid:
        target = str(room_jid or "").split("/", 1)[0].strip().lower()
        return {
            "enabled_rooms": int(any(str(room).split("/", 1)[0].strip().lower() == target for room in enabled)),
            "pending_messages": pending,
        }
    return {"enabled_rooms": len(enabled), "pending_messages": pending}


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return tell diagnostics."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    return [
        f"✅ Tell{scope}: enabled_rooms={state.get('enabled_rooms', 0)}, pending_messages={state.get('pending_messages', 0)}"
    ]


def on_load(bot):
    """
    Register the presence handler using partial so it has (bot, msg)
    signature when called.
    """
    bot.bot_plugins.register_event(
        "tell_notify", "groupchat_presence",
        partial(deliver_tell_messages, bot)
    )
