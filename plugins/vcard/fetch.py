"""Split module for plugins/vcard.py: fetch."""

import logging
import textwrap
import pytz
import datetime
import urllib
from slixmpp.exceptions import IqError
from core_plugins import _core
from utils.command import command, Role
from utils.config import config
from core_plugins.rooms import JOINED_ROOMS


async def get_user_vcard(bot, msg, jid=None):
    """ Fetch and return the vCard information for a user.

    This function retrieves the vCard for the specified JID (or the sender
    if not provided), formats the vCard data, and adds the user's timezone
    from the database if available.

    Args:
        bot: The bot instance.
        msg: The message object (context for resolving JID if not provided).
        jid: (Optional) The JID of the user whose vCard to fetch.
             If None, resolves from msg.

    Returns:
        dict: A dictionary containing vCard fields (e.g., FN, NICKNAME,
        BDAY, URL, ORG, NOTE, EMAIL, LOCALITY, REGION, COUNTRY, TZ).
              The "TZ" field is populated from the database if available.
    """
    vcard_info = await get_vcard(bot, msg, jid)
    _, _vcard = _format_vcard_reply(vcard_info, None, None)

    # add Timezone from DB if available
    timezone = None
    jid, _, _ = await _core.get_real_jid(bot, msg)
    if jid is not None:
        timezone = await _core._get_user_timezone(bot, str(jid))
    else:
        jid, _, _ = await _core.get_real_jid(bot, msg)
        timezone = await _core._get_user_timezone(bot, str(jid))
    _vcard["TZ"] = timezone

    return _vcard


async def vcard_field(bot, msg, target_nick, field, is_room=False):
    """
    Helper to fetch a specific vCard field(s) for a given nick.
    Must be called from MUC PM or groupchat context with a valid
    target_nick present in the room.

    Supports fields: "FN", "NICKNAME", "BDAY", "TIMEZONE", "URL", "ORG",
    "NOTE", "EMAIL".
    Returns "None" if field is not present.
    """
    if field not in ["FN", "NICKNAME", "BDAY", "TIMEZONE", "URL",
                     "ORG", "NOTE", "EMAIL", "LOCALITY", "CTRY"]:
        log.warning("[VCARD] 🔴  Invalid vCard field requested: %s", field)
        return None
    if not is_room and not _core._is_muc_pm(msg):
        jid = msg["from"].bare
    else:
        jid = _core.get_real_jid_from_occupant(bot, msg, target_nick)

    if not jid:
        log.warning(
            "[VCARD] 🔴  Nick '%s' not found in room '%s' for field '%s' lookup",
            target_nick,
            msg["from"].bare,
            field,
        )
        return None

    if field == "TIMEZONE":
        value = await _core._get_user_timezone(bot, str(jid))
        if jid == msg["from"].bare:
            log.info(
                "[VCARD] TIMEZONE lookup for sender's own JID '%s': %s",
                jid,
                value,
            )
        else:
            log.info(
                "[VCARD] TIMEZONE lookup for nick '%s' with JID '%s' in room '%s': %s",
                target_nick,
                jid,
                msg["from"].bare,
                value,
            )
        if not value:
            return None
        return value
    vcard_info = await get_vcard(bot, msg, jid=jid)
    _, vcard = _format_vcard_reply(vcard_info, None, None)
    return vcard[field]


def _vcard_get_joined_nick_info(room, target_nick):
    joined = JOINED_ROOMS.get(room, {})
    nicks = joined.get("nicks", {})
    return nicks.get(target_nick)


async def _vcard_fetch_value(bot, msg, field, jid):
    if field == "TIMEZONE":
        return await _core._get_user_timezone(bot, str(jid))
    vcard = await get_user_vcard(bot, msg, jid)
    return vcard[field]
