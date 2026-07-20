"""Split module for plugins/vcard.py: fetch."""

from slixmpp.exceptions import IqError

from core_plugins import _core
from bot.room_state import JOINED_ROOMS
from utils.config import config

from .config import log
from .formatting import _format_vcard_reply

async def get_vcard(bot, msg, jid=None):
    """
    Helper function to fetch vCard for a given JID using the xep_0054 plugin.
    """
    if jid is None:
        jid, _, _ = await _core.get_real_jid(bot, msg)
    try:
        vcard_plugin = bot.plugin.get("xep_0054", None)
        if not vcard_plugin:
            raise RuntimeError(
                "vCard support (xep_0054) is not enabled in this bot.")
        try:
            result = await vcard_plugin.get_vcard(jid=str(jid), cached=False,
                                                  timeout=float(config.get("vcard_fetch_timeout_seconds", 10) or 10))
        except (IqError, Exception) as e:
            log.info(
                f"[VCARD] Exception while fetching vCard for '{jid}': {e}")
            result = None
        else:
            log.debug(f"[VCARD] vCard fetch for '{jid}' completed")
        if not result:
            log.debug(f"[VCARD] No vCard result for '{jid}'.")
            return None
        log.debug(f"[VCARD] vCard for '{jid}' received.")
        return result["vcard_temp"]
    except Exception as e:
        log.error(f"[VCARD] Exception during vCard lookup for '{jid}': {e}")
        raise

async def get_info(bot, msg, jid=None):
    try:
        vcard = await get_user_vcard(bot, msg, jid)
        if not vcard:
            log.info(f"[VCARD] No vCard found for '{jid}'.")
            return None

    except Exception as e:
        log.error(f"[VCARD] Exception during vCard lookup for '{jid}': {e}")
        raise
    return vcard



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
