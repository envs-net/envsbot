"""Shared vCard field lookup helpers."""

from core_plugins import _core

from .config import log
from .fetch import _vcard_fetch_value, _vcard_get_joined_nick_info, get_user_vcard
from .formatting import (
    _vcard_handle_missing_nick,
    _vcard_reply_empty_requested_user,
    _vcard_reply_missing_field,
    _vcard_reply_result,
    _vcard_value_is_empty,
)

async def _vcard_handle_room_lookup(bot, sender_jid, msg, field, label,
                                    target_nick, room, own=False):
    nick_info = _vcard_get_joined_nick_info(room, target_nick)
    if not nick_info:
        log.warning("[VCARD] 🔴  Nick '%s' not found in room '%s'",
                    target_nick, room)
        _vcard_handle_missing_nick(bot, msg, target_nick, room, own=own)
        return

    jid = nick_info.get("jid")
    value = await _vcard_fetch_value(bot, msg, field, jid)
    if field == "TIMEZONE":
        if own:
            log.info(f"[VCARD] TIMEZONE lookup for nick '{target_nick}'"
                     f" with JID '{jid}' in room '{room}': {value}")
        else:
            log.info(f"[VCARD] TIMEZONE lookup for nick '{target_nick}'"
                     f" with JID '{jid}' in room '{room}': {value}")

    if _vcard_value_is_empty(value):
        log.warning("[VCARD] 🔴  No vCard field '%s' for nick '%s'"
                    " in room '%s'",
                    label, target_nick, room)
        _vcard_reply_missing_field(bot, msg, label, target_nick, room)
        return

    display_name = target_nick
    if _vcard_value_is_empty(value):
        log.warning("[VCARD] 🔴  No %s for requested user '%s'",
                    field, target_nick)
        _vcard_reply_empty_requested_user(bot, msg, label, target_nick)
        return

    await _vcard_reply_result(bot, msg, sender_jid, field, label, value,
                              display_name, room)

async def _get_vcard_field(bot, sender_jid, nick, args, msg, is_room,
                           field, label):
    """
    Helper to fetch and display a profile field for a user nick.
    """
    is_muc_context = is_room or _core._is_muc_pm(msg)

    if is_muc_context and args:
        target_nick = " ".join(args).strip()
        room = msg["from"].bare
        await _vcard_handle_room_lookup(bot, sender_jid, msg, field, label,
                                        target_nick, room, own=False)
        return

    if is_muc_context and not args:
        target_nick = msg["from"].resource
        room = msg["from"].bare
        await _vcard_handle_room_lookup(bot, sender_jid, msg, field, label,
                                        target_nick, room, own=True)
        return

    target_nick = msg["from"].bare
    room = "Direct Message"

    if args:
        log.info("[VCARD] Direct message with args from "
                 f"'{msg['from'].bare}'")
        bot.reply(msg, "🔴  In direct messages, you can only look up "
                       "your own vCard. Use the command without args.")
        return

    jid = msg["from"].bare
    if field == "TIMEZONE":
        value = await _core._get_user_timezone(bot, str(jid))
    else:
        vcard = await get_user_vcard(bot, msg, msg["from"].bare)
        if vcard[field] is None:
            log.warning("[VCARD] 🔴  No vCard field '%s' for nick '%s'"
                        "in room '%s'",
                        label, target_nick, room)
            _vcard_reply_missing_field(bot, msg, label, target_nick, room)
            return
        value = vcard[field]

    display_name = target_nick
    if _vcard_value_is_empty(value):
        log.warning("[VCARD] 🔴  No %s for requested user '%s'",
                    field, target_nick)
        _vcard_reply_empty_requested_user(bot, msg, label, target_nick)
        return

    await _vcard_reply_result(bot, msg, sender_jid, field, label, value,
                              display_name, room)
    return
