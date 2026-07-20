"""Split module for plugins/reminder.py: formatting."""

from bot.room_state import JOINED_ROOMS
from core_plugins._core import _is_muc_pm, _normalize_bare_jid

from .parsing import _timezone_lookup_jid
from .store import _get_room_reminder_state


def _display_nick(sender_jid, nick: str | None = None) -> str:
    """Best-effort display name for reminder messages."""
    if nick:
        return str(nick)

    value = str(sender_jid)

    if "/" in value:
        resource = value.rsplit("/", 1)[-1]
        if resource:
            return resource

    if "@" in value:
        return value.split("@", 1)[0]

    return value


def _reminder_context(bot, sender_jid, nick, msg, is_room: bool):
    """Build stable ownership and delivery context.

    Cases:
    - normal DM: send chat to bare user JID
    - MUC: send groupchat to room bare JID
    - MUC-PM: send chat to full occupant JID room@conference/nick
    """
    if is_room:
        room_jid = msg["from"].bare
        user_jid = _normalize_bare_jid(sender_jid)
        display_nick = _display_nick(sender_jid, nick)

        return {
            "user_jid": user_jid,
            "timezone_jid": _timezone_lookup_jid(bot, sender_jid,
                                                 msg, is_room),
            "display_nick": display_nick,
            "room_jid": room_jid,
            "msg_mto": room_jid,
            "msg_type": "groupchat",
        }

    if _is_muc_pm(msg, is_room):
        muc_occupant_jid = str(msg["from"])
        display_nick = msg["from"].resource or _display_nick(sender_jid, nick)

        return {
            "user_jid": muc_occupant_jid,
            "timezone_jid": _timezone_lookup_jid(bot, sender_jid,
                                                 msg, is_room),
            "display_nick": display_nick,
            "room_jid": None,
            "msg_mto": muc_occupant_jid,
            "msg_type": "chat",
        }

    user_jid = _normalize_bare_jid(sender_jid)

    return {
        "user_jid": user_jid,
        "timezone_jid": user_jid,
        "display_nick": _display_nick(sender_jid, nick),
        "room_jid": None,
        "msg_mto": user_jid,
        "msg_type": "chat",
    }


def _room_jid_from_context(msg, is_room: bool) -> str | None:
    """Return the room JID for groupchat or MUC-PM contexts.

    The other room-controlled plugins use MUC-PM room management, where
    is_room is False but msg["from"].bare is the room JID. Public groupchat
    messages have is_room=True. Normal DMs return None.
    """
    try:
        room_jid = str(msg["from"].bare)
    except Exception:
        return None

    if is_room:
        return room_jid

    if room_jid in JOINED_ROOMS:
        return room_jid

    return None


async def _is_reminder_enabled_for_context(bot, msg, is_room: bool) -> bool:
    """Return whether reminders may be used in the current context.

    Normal DMs are allowed. Groupchat and MUC-PM contexts must be enabled via
    the room control state.
    """
    room_jid = _room_jid_from_context(msg, is_room)
    if not room_jid:
        return True

    return await _get_room_reminder_state(bot, room_jid)


async def _send_reminder_message(bot, mto: str, mbody: str, mtype: str):
    """Send reminder as a fresh message.

    Do not use bot.reply() here because delayed reminders should not depend on
    an old message object or client-specific reply/thread rendering.
    """
    msg = bot.make_message(
        mto=mto,
        mbody=mbody,
        mtype=mtype,
    )

    if hasattr(bot, "_safe_send_message"):
        await bot._safe_send_message(msg)
    else:
        msg.send()
