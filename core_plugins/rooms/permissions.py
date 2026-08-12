"""Split module for core_plugins/rooms.py: permissions."""

import inspect

from utils.command import Role

from .state import JOINED_ROOMS, _jid_bare, log


async def _maybe_get_user_role(bot, sender_jid: str, room_jid: str) -> Role:
    """Return the sender role for a room without assuming async mocks."""
    get_user_role = getattr(bot, "get_user_role", None)
    if not callable(get_user_role):
        return Role.NONE
    try:
        result = get_user_role(sender_jid, room_jid)
        if inspect.isawaitable(result):
            result = await result
        return result if isinstance(result, Role) else Role.NONE
    except Exception:
        log.debug("[ROOMS] Could not resolve role for %s in %s", sender_jid, room_jid, exc_info=True)
        return Role.NONE


def _sender_has_room_affiliation(sender_jid: str, room_jid: str) -> bool:
    """Return True if sender is visible as room admin/owner in JOINED_ROOMS."""
    sender_bare = _jid_bare(sender_jid)
    if not sender_bare:
        return False
    room_data = JOINED_ROOMS.get(room_jid) or {}
    nicks = room_data.get("nicks") or {}
    if not isinstance(nicks, dict):
        return False
    for occupant in tuple(nicks.values()):
        if not isinstance(occupant, dict):
            continue
        occupant_jid = _jid_bare(occupant.get("jid"))
        affiliation = str(occupant.get("affiliation") or "").lower()
        if occupant_jid == sender_bare and affiliation in {"admin", "owner"}:
            return True
    return False


async def _sender_can_manage_room_settings(bot, sender_jid: str, room_jid: str) -> bool:
    """Return True when sender may manage room-scoped bot settings."""
    sender_bare = _jid_bare(sender_jid)
    if not sender_bare:
        return False
    role = await _maybe_get_user_role(bot, sender_bare, room_jid)
    if role <= Role.MODERATOR:
        return True
    return _sender_has_room_affiliation(sender_bare, room_jid)


def bot_has_privilege(room, required=("admin", "owner")):
    info = JOINED_ROOMS.get(room)
    if not info:
        return False
    return info.get("affiliation") in required
