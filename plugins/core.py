# plugins/core.py

"""
Core utility and shared helpers for all envsbot plugins.
Depends on essential plugins (e.g., "rooms") via PLUGIN_META.

Put any functions or objects here that:
  - are needed by multiple plugins
  - require access to JOINED_ROOMS or runtime bot/plugin state
  - should ONLY be initialized after their dependencies are loaded
"""
import logging
import slixmpp

from plugins.rooms import JOINED_ROOMS
from plugins.vcard import get_user_vcard

PLUGIN_META = {
    "name": "core",
    "version": "0.1.3",
    "description": "Core utilities and shared helpers for other plugins.",
    "category": "internal",
    "requires": ["rooms"],  # Ensure 'rooms' is loaded first
    "hidden": True,         # Optional: Hide from user plugin listings
}

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Expose get_user_vcard as get_profile for easier access across plugins
# Usage:
#   vcard = await core.get_profile(bot, msg, jid)
# Parameters:
#   - bot: The bot instance (for database access)
#   - msg: The message object (for context and replying)
#   - jid: The JID of the user whose profile to fetch
# Fields:
#   - vcard['FN'] - Full name
#   - vcard['NICKNAME'] - Nickname
#   - vcard['BDAY'] - Birthday
#   - vcard['URL'] - URLs
#   - vcard['ORG'] - Organization
#   - vcard['NOTE'] - Notes
#   - vcard['EMAIL'] - Emails
#   - vcard['LOCALITY'] - Locality
#   - vcard['REGION'] - Region
#   - vcard['COUNTRY'] - Country
# ----------------------------------------------------------------------
get_profile = get_user_vcard


# ---------------------------------------------------------------------
# Check if a message is a MUC private message
# (i.e., a direct message from a MUC participant to the bot)
# ---------------------------------------------------------------------
def _is_muc_pm(msg, joined_rooms=None):
    """Return True if message is a MUC private message."""
    # Joined rooms can be passed or imported if not given
    if joined_rooms is None:
        joined_rooms = JOINED_ROOMS
    muc_from = getattr(msg['from'], 'bare', None)
    return (
        msg['type'] in ('chat', 'normal')
        and muc_from in joined_rooms
        and getattr(msg['from'], 'resource', None) is not None
    )


# -----------------------------------------------------------------------
# Get the real JID of the sender, check for MUC private message first,
# then groupchat, then DM
# ----------------------------------------------------------------------
async def get_real_jid(bot, msg):
    """
    Resolve the real sender JID in all contexts (groupchat, MUC PM, or DM).

    returns:
        - jid (str): The resolved JID of the sender
        - is_muc_private (bool): True if this was a MUC private message
        - is_muc_groupchat (bool): True if this was a groupchat message
    """
    jid = None
    is_muc_private = False
    is_muc_groupchat = False

    muc = bot.plugin.get("xep_0045", None)
    result = None
    if muc:
        room = getattr(msg['from'], 'bare', None)
        nick = getattr(msg['from'], 'resource', None)
        # log.info("[CORE] Resolving real JID for room: %s, nick: %s", room, nick)
        try:
            result = JOINED_ROOMS.get(room, {}).get("nicks", {}).get(nick, {}).get("jid", None)
        except Exception as e:
        #    log.warning("[CORE] 🟡 Error resolving real JID for %s in %s: %s", nick, room, e)
            result = None
        # Fallback: try to resolve via UserManager's _nick_index if not found
        if result is None and nick:
            result = await get_real_jids_from_nick(bot, nick)

    if result is not None and _is_muc_pm(msg):
        # MUC private message, try to resolve real JID
        jid = result
        is_muc_private = True
    elif result is not None and msg['type'] == 'groupchat':
        # Groupchat message, use the resolved JID
        jid = result
        is_muc_groupchat = True
    elif msg['to'].bare == bot.boundjid.bare:
        # Direct message to the bot, use the sender's JID
        jid = msg['from'].bare
    else:
        # Fallback: use the sender's JID as-is
        jid = None
    return jid, is_muc_private, is_muc_groupchat


# -----------------------------------------------------------------------
# Helper to look up real JIDs from the UserManager's _nick_index, which is
# populated by the MUC plugin when users join rooms. This allows us to resolve
# real JIDs from nicks in MUC contexts, even if we don't have the full message
# ccontext.
# -----------------------------------------------------------------------
async def get_real_jids_from_nick(bot, nick):
    """Look up the real JID of a nick from the UserManager's _nick_index."""
    idx = getattr(bot.db.users, "_nick_index", {})
    value = idx.get(nick)
    if isinstance(value, set):
        return next(iter(value), None)
    if isinstance(value, list):
        return value
    return value or None


# -----------------------------------------------------------------------
# Helper to check if a user exists in the database, and reply with an error
# -----------------------------------------------------------------------
async def _check_user_exists(bot, sender_jid, msg):
    """
    Check if the user exists in the database.

    Args:
        bot: The bot instance.
        sender_jid: The JID to check.
        msg: The message object.

    Returns:
        bool: True if user exists, False otherwise.
    """
    jid = str(sender_jid)
    user = await bot.db.users.get(jid)
    if not user:
        log.warning(
            "[CORE] 🔴  Unregistered user tried to access: %s", jid
        )
        bot.reply(msg, "🔴  You are not a registered user.")
        return False
    return True
